import argparse
import json
import math
from pathlib import Path
import statistics
import tempfile
import time

from databases.factory import create_database_adapter
from dgtuner.common.paths import (
    default_workload_path,
    llm_pruning_path,
    probing_path,
    reduced_workload_path,
)
from dgtuner.probing.analysis import (
    normalize_query_info,
    select_reduced_sql_by_rank_correlation,
)
from dgtuner.probing.importance import rank_parameters_by_importance
from dgtuner.probing.io import read_jsonl, split_sql_file, write_jsonl, write_sql_file
from dgtuner.probing.sampling import (
    default_sample_value,
    generate_sobol_samples,
    normalize_range,
    parameter_id,
    parameter_key,
)
from dgtuner.probing.workload import select_initial_sql


DEFAULT_DATABASE = "dingodb"
DEFAULT_LLM_PRUNING_PATH = llm_pruning_path(DEFAULT_DATABASE)
DEFAULT_WORKLOAD_PATH = default_workload_path(DEFAULT_DATABASE)
DEFAULT_OUTPUT_PATH = probing_path(DEFAULT_DATABASE)
DEFAULT_REDUCED_WORKLOAD_PATH = reduced_workload_path(DEFAULT_DATABASE)


def load_kept_parameters(path):
    return [record for record in read_jsonl(path) if int(record.get("keep", 1)) == 1]


def filter_tunable_parameters(parameters):
    tunable = []
    skipped = []
    for record in parameters:
        if normalize_range(record) is not None:
            tunable.append(record)
        else:
            skipped.append({
                "id": parameter_id(record),
                "name": parameter_key(record),
                "reason": "Supported by adapter, but no tunable range is available for empirical probing.",
            })
    return tunable, skipped


def parse_adapter_options(values):
    options = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"adapter option must be KEY=VALUE, got: {value}")
        key, raw = value.split("=", 1)
        options[key] = parse_scalar(raw)
    return options


def parse_scalar(value):
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def create_adapter(database, adapter_options):
    return create_database_adapter(database, **adapter_options)


def aggregate_repeated_workload(repeat_results):
    total_times = [float(item["total_time"]) for item in repeat_results]
    per_sql = {}
    for repeat in repeat_results:
        for item in repeat["query_info"]:
            bucket = per_sql.setdefault(int(item["sql"]), {"times": [], "status": 0})
            bucket["times"].append(float(item["execution_time"]))
            if int(item.get("status", 0)) != 0:
                bucket["status"] = 1
    query_info = [
        {
            "sql": sql_id,
            "status": data["status"],
            "execution_time": float(statistics.median(data["times"])) if data["times"] else 0.0,
        }
        for sql_id, data in sorted(per_sql.items())
    ]
    return {
        "total_time": float(sum(item["execution_time"] for item in query_info)),
        "repeat_times": total_times,
        "query_info": query_info,
    }


def run_workload_repeats(adapter, workload_path, concurrency, repeats):
    repeat_results = []
    for repeat_id in range(max(1, int(repeats))):
        total_time, query_info = adapter.run_workload_with_query_info(str(workload_path), concurrency)
        repeat_results.append({
            "repeat": repeat_id + 1,
            "total_time": float(total_time),
            "query_info": normalize_query_info(query_info),
        })
    return aggregate_repeated_workload(repeat_results)


def default_parameter_sample(parameters):
    return {parameter_key(record): default_sample_value(record) for record in parameters}


def apply_and_run(adapter, sample, workload_path, concurrency, repeats, baseline_time):
    applied = adapter.get_true_values(sample) if hasattr(adapter, "get_true_values") else sample
    adapter.apply_config(sample)
    if hasattr(adapter, "restart"):
        adapter.restart()
    baseline_time = max(float(baseline_time), 1e-9)
    if not adapter.health_check():
        # The DB did not start with this config: the sampled values/combination are
        # out of MySQL's accepted bounds. That is a knowledge-base range problem to
        # fix, not a "bad config" to swallow — fail loudly with the offending values.
        logs = adapter.recent_logs() if hasattr(adapter, "recent_logs") else ""
        raise UnhealthyConfigError(applied, logs)
    adapter.clear_output_log()
    workload_result = run_workload_repeats(adapter, workload_path, concurrency, repeats)
    total_time = float(workload_result["total_time"])
    return {
        "applied_params": applied,
        "total_time": total_time,
        "baseline_time": baseline_time,
        "target": -math.log(max(total_time, 1e-9) / baseline_time),
        "repeat_times": workload_result["repeat_times"],
        "query_info": workload_result["query_info"],
    }


def probing_temp_workload(initial_sql):
    temp_file = tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8")
    with temp_file:
        for item in initial_sql:
            temp_file.write(item["sql"].rstrip(";") + ";\n")
    return Path(temp_file.name)


def remap_probe_sql_ids(query_info, initial_sql):
    original_sql_id_by_probe_id = {
        probe_id: item["sql_id"]
        for probe_id, item in enumerate(initial_sql, 1)
    }
    for item in query_info:
        item["probe_sql"] = item["sql"]
        item["sql"] = original_sql_id_by_probe_id.get(item["probe_sql"], item["sql"])


def run_samples(adapter, planned_samples, workload_path, concurrency, initial_sql, repeats, baseline_time):
    sample_results = []
    total = len(planned_samples)
    for sample_id, sample_entry in enumerate(planned_samples):
        sample = sample_entry["params"]
        start = time.time()
        try:
            run_result = apply_and_run(adapter, sample, workload_path, concurrency, repeats, baseline_time)
        except UnhealthyConfigError as error:
            print(
                f"[stage2] sample {sample_id + 1}/{total} ABORTED: database failed to start "
                f"with this config — a knob range produced a rejected value/combination. "
                f"Tighten the offending range(s) in the knowledge base and rerun.",
                flush=True,
            )
            print("[stage2] offending applied values:", flush=True)
            for key in sorted(error.applied_params):
                print(f"    {key} = {error.applied_params[key]}", flush=True)
            if error.logs:
                print("[stage2] --- database log (tail) ---", flush=True)
                print(error.logs, flush=True)
            raise
        remap_probe_sql_ids(run_result["query_info"], initial_sql)
        sample_results.append({
            "record_type": "sample_result",
            "sample_id": sample_id,
            "workload_repeats": repeats,
            "params": sample,
            **run_result,
        })
        print(
            f"[stage2] sample {sample_id + 1}/{total} done | "
            f"total_time={run_result['total_time']:.2f}s target={run_result['target']:+.4f} | "
            f"{time.time() - start:.1f}s",
            flush=True,
        )
    return sample_results


MIN_SAMPLES = 8
CONCURRENCY = 1


class UnhealthyConfigError(RuntimeError):
    """Raised when a sampled config prevents the DB from starting (range problem)."""

    def __init__(self, applied_params, logs=""):
        self.applied_params = applied_params
        self.logs = logs
        super().__init__("Database did not start with a sampled config.")


def run_probing(
    database,
    llm_pruning_path,
    workload_path,
    output_path,
    reduced_workload_path,
    samples,
    adapter_options,
    similarity_threshold,
    initial_sql_percent,
    importance_threshold,
    bagging_rounds,
    sql_corr_threshold,
    min_sql,
    max_sql,
    workload_repeats,
    seed,
):
    adapter = create_adapter(database, adapter_options)
    llm_parameters = load_kept_parameters(llm_pruning_path)
    parameters, no_range_parameters = filter_tunable_parameters(llm_parameters)
    if not parameters:
        raise ValueError("No tunable parameters remain for probing.")

    # Fixed evaluation budget, decoupled from the parameter count: Stage 2 must
    # cost far fewer evaluations than Stage 3, so the budget is capped, not scaled.
    samples = max(MIN_SAMPLES, int(samples))

    statements = split_sql_file(workload_path)
    initial_sql, sql_groups = select_initial_sql(statements, similarity_threshold, initial_sql_percent)
    settings = {
        "samples": samples,
        "similarity_threshold": similarity_threshold,
        "initial_sql_percent": initial_sql_percent,
        "importance_threshold": importance_threshold,
        "bagging_rounds": bagging_rounds,
        "sql_corr_threshold": sql_corr_threshold,
        "min_sql": min_sql,
        "max_sql": max_sql,
        "workload_repeats": workload_repeats,
        "seed": seed,
    }

    print(
        f"[stage2] {len(parameters)} tunable params | {samples} samples (budget) | "
        f"initial_sql={len(initial_sql)}/{len(statements)} | workload_repeats={workload_repeats}",
        flush=True,
    )

    temp_workload_path = probing_temp_workload(initial_sql)
    try:
        default_sample = default_parameter_sample(parameters)
        baseline_applied = adapter.get_true_values(default_sample) if hasattr(adapter, "get_true_values") else default_sample
        print("[stage2] running baseline (default config)...", flush=True)
        adapter.apply_config(default_sample)
        if hasattr(adapter, "restart"):
            adapter.restart()
        if not adapter.health_check():
            logs = adapter.recent_logs() if hasattr(adapter, "recent_logs") else ""
            if logs:
                print("[stage2] --- database log (tail) ---", flush=True)
                print(logs, flush=True)
            raise RuntimeError(
                "Database did not start with the default parameter set. A kept knob may "
                "not be a valid startup option, or the default config is rejected. See the "
                "database log above."
            )
        adapter.clear_output_log()
        baseline_workload = run_workload_repeats(adapter, temp_workload_path, CONCURRENCY, workload_repeats)
        remap_probe_sql_ids(baseline_workload["query_info"], initial_sql)
        baseline_result = {
            "record_type": "baseline_result",
            "sample_id": "baseline",
            "params": default_sample,
            "applied_params": baseline_applied,
            "total_time": baseline_workload["total_time"],
            "baseline_time": baseline_workload["total_time"],
            "target": 0.0,
            "workload_repeats": workload_repeats,
            "repeat_times": baseline_workload["repeat_times"],
            "query_info": baseline_workload["query_info"],
        }
        print(f"[stage2] baseline total_time={baseline_result['total_time']:.2f}s; sampling {samples} configs...", flush=True)
        planned_samples = generate_sobol_samples(parameters, samples, seed=seed)
        sample_results = run_samples(
            adapter,
            planned_samples,
            temp_workload_path,
            CONCURRENCY,
            initial_sql,
            workload_repeats,
            baseline_result["total_time"],
        )
    finally:
        temp_workload_path.unlink(missing_ok=True)

    print("[stage2] ranking parameters (ARD-GP relevance + per-SQL recall net)...", flush=True)
    parameter_decisions = rank_parameters_by_importance(
        parameters,
        sample_results,
        baseline_query_info=baseline_result["query_info"],
        importance_threshold=importance_threshold,
        bagging_rounds=bagging_rounds,
        seed=seed,
    )
    print("[stage2] selecting representative SQL (rank correlation)...", flush=True)
    sql_decisions = select_reduced_sql_by_rank_correlation(
        initial_sql,
        sample_results,
        keep_threshold=sql_corr_threshold,
        min_sql=min_sql,
        max_sql=max_sql,
    )

    kept_sql = [item["sql"] for item in sql_decisions if item["keep"] == 1]
    write_sql_file(reduced_workload_path, kept_sql)
    kept_params = sum(1 for item in parameter_decisions if item["keep"] == 1)
    print(
        f"[stage2] done | kept_params={kept_params}/{len(parameter_decisions)} | "
        f"kept_sql={len(kept_sql)}/{len(initial_sql)}",
        flush=True,
    )

    summary = {
        "record_type": "summary",
        "database": database,
        "llm_parameter_count": len(llm_parameters),
        "sampled_parameter_count": len(parameters),
        "skipped_parameter_count": len(no_range_parameters),
        "sample_count": len(sample_results),
        "stop_reason": "param_scaled_sampling_completed",
        "baseline_time": baseline_result["total_time"],
        "original_sql_count": len(statements),
        "similarity_group_count": len(sql_groups),
        "initial_sql_count": len(initial_sql),
        "kept_sql_count": len(kept_sql),
        "kept_parameter_count": sum(1 for item in parameter_decisions if item["keep"] == 1),
        "removed_parameter_count": sum(1 for item in parameter_decisions if item["keep"] == 0),
        "output": str(output_path),
        "reduced_workload": str(reduced_workload_path),
    }

    records = [{
        "record_type": "meta",
        "database": database,
        "workload": str(workload_path),
        "llm_pruning": str(llm_pruning_path),
        "reduced_workload": str(reduced_workload_path),
        "settings": settings,
    }]
    records.extend({"record_type": "skipped_parameter", **item} for item in no_range_parameters)
    records.append(baseline_result)
    records.extend(sample_results)
    records.extend(sql_decisions)
    records.extend(parameter_decisions)
    records.append(summary)
    write_jsonl(output_path, records)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run empirical probing for Stage 2 (knob and SQL reduction).")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--llm-pruning", default=None)
    parser.add_argument("--workload", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--reduced-workload", default=None)
    parser.add_argument("--samples", type=int, default=40,
                        help="evaluation budget for Stage 2; keep it well below Stage 3 iterations")
    parser.add_argument("--adapter-option", action="append", default=[])
    parser.add_argument("--similarity-threshold", type=float, default=0.9)
    parser.add_argument("--initial-sql-percent", type=float, default=10.0)
    parser.add_argument("--importance-threshold", type=float, default=0.01)
    parser.add_argument("--bagging-rounds", type=int, default=5)
    parser.add_argument("--sql-corr-threshold", type=float, default=0.95)
    parser.add_argument("--min-sql", type=int, default=1)
    parser.add_argument("--max-sql", type=int, default=None)
    parser.add_argument("--workload-repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    llm_path = args.llm_pruning or str(llm_pruning_path(args.database))
    workload = args.workload or str(default_workload_path(args.database))
    output = args.output or str(probing_path(args.database))
    reduced_workload = args.reduced_workload or str(reduced_workload_path(args.database))
    summary = run_probing(
        database=args.database,
        llm_pruning_path=llm_path,
        workload_path=workload,
        output_path=output,
        reduced_workload_path=reduced_workload,
        samples=args.samples,
        adapter_options=parse_adapter_options(args.adapter_option),
        similarity_threshold=args.similarity_threshold,
        initial_sql_percent=args.initial_sql_percent,
        importance_threshold=args.importance_threshold,
        bagging_rounds=args.bagging_rounds,
        sql_corr_threshold=args.sql_corr_threshold,
        min_sql=args.min_sql,
        max_sql=args.max_sql,
        workload_repeats=args.workload_repeats,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
