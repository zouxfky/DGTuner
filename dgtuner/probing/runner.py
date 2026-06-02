import argparse
import json
import tempfile

from databases.factory import create_database_adapter
from dgtuner.common.paths import (
    PROJECT_ROOT,
    default_workload_path,
    llm_pruning_path,
    probing_path,
    reduced_workload_path,
)
from dgtuner.probing.analysis import (
    normalize_query_info,
    rank_parameters_by_correlation,
    rank_sql_by_sensitivity,
    stability_status,
)
from dgtuner.probing.io import read_jsonl, split_sql_file, write_jsonl, write_sql_file
from dgtuner.probing.sampling import generate_lhs_samples, normalize_range, parameter_id, parameter_key
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


def apply_and_run(adapter, sample, workload_path, concurrency):
    applied = adapter.get_true_values(sample) if hasattr(adapter, "get_true_values") else sample
    adapter.apply_config(sample)
    adapter.clear_output_log()
    total_time, query_info = adapter.run_workload_with_query_info(str(workload_path), concurrency)
    return {
        "applied_params": applied,
        "total_time": float(total_time),
        "target": -float(total_time) if abs(float(total_time)) >= 1 else -999,
        "query_info": normalize_query_info(query_info),
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


def run_samples(adapter, planned_samples, sample_range, workload_path, concurrency, initial_sql):
    sample_results = []
    for sample_id in sample_range:
        sample = planned_samples[sample_id]
        run_result = apply_and_run(adapter, sample, workload_path, concurrency)
        remap_probe_sql_ids(run_result["query_info"], initial_sql)
        sample_results.append({
            "record_type": "sample_result",
            "sample_id": sample_id,
            "params": sample,
            **run_result,
        })
    return sample_results


def build_round_summary(round_id, previous_sample_count, current_sample_count, sql_decisions, parameter_decisions, stability, stable_count):
    return {
        "record_type": "round_summary",
        "round": round_id,
        "sample_count": current_sample_count,
        "new_sample_count": current_sample_count - previous_sample_count,
        "kept_sql_count": sum(1 for item in sql_decisions if item["keep"] == 1),
        "kept_parameter_count": sum(1 for item in parameter_decisions if item["keep"] == 1),
        "removed_parameter_count": sum(1 for item in parameter_decisions if item["keep"] == 0),
        "stable": stability["stable"],
        "consecutive_stable_rounds": stable_count,
        "sql_jaccard": stability["sql_jaccard"],
        "knob_jaccard": stability["knob_jaccard"],
        "rank_jaccard": stability["rank_jaccard"],
    }


def run_adaptive_rounds(adapter, parameters, initial_sql, planned_samples, workload_path, settings):
    sample_results = []
    round_summaries = []
    sql_decisions = []
    parameter_decisions = []
    previous_stability_base = None
    stable_count = 0
    stop_reason = "max_samples"
    next_sample_id = 0
    round_id = 0

    while next_sample_id < len(planned_samples):
        round_id += 1
        previous_sample_count = next_sample_id
        target_sample_count = (
            min(settings["initial_samples"], len(planned_samples))
            if next_sample_id == 0
            else min(next_sample_id + settings["batch_size"], len(planned_samples))
        )

        sample_results.extend(run_samples(
            adapter,
            planned_samples,
            range(next_sample_id, target_sample_count),
            workload_path,
            settings["concurrency"],
            initial_sql,
        ))
        next_sample_id = target_sample_count

        cumulative_samples = planned_samples[:next_sample_id]
        sql_decisions = rank_sql_by_sensitivity(initial_sql, sample_results, settings["keep_sql_ratio"], settings["min_sql"])
        parameter_decisions = rank_parameters_by_correlation(
            parameters,
            cumulative_samples,
            sample_results,
            settings["knob_correlation_threshold"],
            settings["elite_ratio"],
        )
        previous_stability_base, stability = stability_status(
            previous_stability_base,
            sql_decisions,
            parameter_decisions,
            {
                "sql": settings["sql_stability_threshold"],
                "knob": settings["knob_stability_threshold"],
                "rank": settings["rank_stability_threshold"],
            },
            settings["top_k_knobs"],
        )
        stable_count = stable_count + 1 if stability["stable"] else 0
        round_summaries.append(build_round_summary(
            round_id,
            previous_sample_count,
            next_sample_id,
            sql_decisions,
            parameter_decisions,
            stability,
            stable_count,
        ))

        if stable_count >= settings["stable_rounds"]:
            stop_reason = "stable"
            break

    return sample_results, round_summaries, sql_decisions, parameter_decisions, stop_reason


def run_probing(
    database,
    llm_pruning_path,
    workload_path,
    output_path,
    reduced_workload_path,
    initial_samples,
    batch_size,
    max_samples,
    stable_rounds,
    concurrency,
    adapter_options,
    similarity_threshold,
    initial_sql_percent,
    keep_sql_ratio,
    min_sql,
    knob_correlation_threshold,
    elite_ratio,
    sql_stability_threshold,
    knob_stability_threshold,
    rank_stability_threshold,
    top_k_knobs,
    seed,
):
    adapter = create_adapter(database, adapter_options)
    llm_parameters = load_kept_parameters(llm_pruning_path)
    parameters, no_range_parameters = filter_tunable_parameters(llm_parameters)
    planned_samples = generate_lhs_samples(parameters, max_samples, seed=seed)
    if not planned_samples:
        raise ValueError("No tunable parameters remain for probing.")

    statements = split_sql_file(workload_path)
    initial_sql, sql_groups = select_initial_sql(statements, similarity_threshold, initial_sql_percent)
    settings = {
        "initial_samples": initial_samples,
        "batch_size": batch_size,
        "max_samples": max_samples,
        "stable_rounds": stable_rounds,
        "concurrency": concurrency,
        "similarity_threshold": similarity_threshold,
        "initial_sql_percent": initial_sql_percent,
        "keep_sql_ratio": keep_sql_ratio,
        "min_sql": min_sql,
        "knob_correlation_threshold": knob_correlation_threshold,
        "elite_ratio": elite_ratio,
        "sql_stability_threshold": sql_stability_threshold,
        "knob_stability_threshold": knob_stability_threshold,
        "rank_stability_threshold": rank_stability_threshold,
        "top_k_knobs": top_k_knobs,
        "seed": seed,
    }

    temp_workload_path = probing_temp_workload(initial_sql)
    try:
        sample_results, round_summaries, sql_decisions, parameter_decisions, stop_reason = run_adaptive_rounds(
            adapter,
            parameters,
            initial_sql,
            planned_samples,
            temp_workload_path,
            settings,
        )
    finally:
        temp_workload_path.unlink(missing_ok=True)

    kept_sql = [item["sql"] for item in sql_decisions if item["keep"] == 1]
    write_sql_file(reduced_workload_path, kept_sql)

    summary = {
        "record_type": "summary",
        "database": database,
        "llm_parameter_count": len(llm_parameters),
        "sampled_parameter_count": len(parameters),
        "skipped_parameter_count": len(no_range_parameters),
        "sample_count": len(sample_results),
        "round_count": len(round_summaries),
        "stop_reason": stop_reason,
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
    records.extend(sample_results)
    records.extend(round_summaries)
    records.extend(sql_decisions)
    records.extend(parameter_decisions)
    records.append(summary)
    write_jsonl(output_path, records)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run adaptive empirical probing for Stage 2.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--llm-pruning", default=None)
    parser.add_argument("--workload", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--reduced-workload", default=None)
    parser.add_argument("--initial-samples", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--max-samples", type=int, default=30)
    parser.add_argument("--stable-rounds", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--adapter-option", action="append", default=[])
    parser.add_argument("--similarity-threshold", type=float, default=0.9)
    parser.add_argument("--initial-sql-percent", type=float, default=10.0)
    parser.add_argument("--keep-sql-ratio", type=float, default=0.6)
    parser.add_argument("--min-sql", type=int, default=1)
    parser.add_argument("--knob-correlation-threshold", type=float, default=0.05)
    parser.add_argument("--elite-ratio", type=float, default=0.2)
    parser.add_argument("--sql-stability-threshold", type=float, default=0.9)
    parser.add_argument("--knob-stability-threshold", type=float, default=0.9)
    parser.add_argument("--rank-stability-threshold", type=float, default=0.8)
    parser.add_argument("--top-k-knobs", type=int, default=10)
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
        initial_samples=args.initial_samples,
        batch_size=args.batch_size,
        max_samples=args.max_samples,
        stable_rounds=args.stable_rounds,
        concurrency=args.concurrency,
        adapter_options=parse_adapter_options(args.adapter_option),
        similarity_threshold=args.similarity_threshold,
        initial_sql_percent=args.initial_sql_percent,
        keep_sql_ratio=args.keep_sql_ratio,
        min_sql=args.min_sql,
        knob_correlation_threshold=args.knob_correlation_threshold,
        elite_ratio=args.elite_ratio,
        sql_stability_threshold=args.sql_stability_threshold,
        knob_stability_threshold=args.knob_stability_threshold,
        rank_stability_threshold=args.rank_stability_threshold,
        top_k_knobs=args.top_k_knobs,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
