import argparse
import json
import math
from pathlib import Path
import statistics
import tempfile

from databases.factory import create_database_adapter
from dgtuner.common.paths import (
    default_workload_path,
    llm_pruning_path,
    probing_path,
    reduced_workload_path,
)
from dgtuner.probing.analysis import (
    normalize_query_info,
    rank_parameters_by_sparse_effect,
    rank_sql_by_sensitivity,
)
from dgtuner.probing.io import read_jsonl, split_sql_file, write_jsonl, write_sql_file
from dgtuner.probing.sampling import (
    default_sample_value,
    generate_sparse_screening_samples,
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
    adapter.clear_output_log()
    workload_result = run_workload_repeats(adapter, workload_path, concurrency, repeats)
    total_time = float(workload_result["total_time"])
    baseline_time = max(float(baseline_time), 1e-9)
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


def run_samples(adapter, planned_samples, sample_range, workload_path, concurrency, initial_sql, repeats, baseline_time):
    sample_results = []
    for sample_id in sample_range:
        sample_entry = planned_samples[sample_id]
        sample = sample_entry.get("params", sample_entry) if isinstance(sample_entry, dict) else sample_entry
        run_result = apply_and_run(adapter, sample, workload_path, concurrency, repeats, baseline_time)
        remap_probe_sql_ids(run_result["query_info"], initial_sql)
        record = {
            "record_type": "sample_result",
            "sample_id": sample_id,
            "workload_repeats": repeats,
            "params": sample,
            **run_result,
        }
        if isinstance(sample_entry, dict) and "params" in sample_entry:
            for key in ("varied_parameters", "screening_sample_index", "parameter_coverage"):
                if key in sample_entry:
                    record[key] = sample_entry[key]
        sample_results.append(record)
    return sample_results


def run_sparse_screening(adapter, parameters, initial_sql, workload_path, settings, baseline_result):
    planned_samples = generate_sparse_screening_samples(
        parameters,
        settings["max_samples"],
        active_parameters_per_sample=settings["active_parameters_per_sample"],
        seed=settings["seed"],
    )
    sample_results = run_samples(
        adapter,
        planned_samples,
        range(len(planned_samples)),
        workload_path,
        settings["concurrency"],
        initial_sql,
        settings["workload_repeats"],
        baseline_result["total_time"],
    )
    sql_decisions = rank_sql_by_sensitivity(
        initial_sql,
        sample_results,
        settings["keep_sql_ratio"],
        settings["min_sql"],
        baseline_result["query_info"],
    )
    parameter_decisions = rank_parameters_by_sparse_effect(
        parameters,
        sample_results,
        settings["knob_effect_threshold"],
        settings["elite_ratio"],
        ridge_alpha=settings["ridge_alpha"],
        bootstrap_rounds=settings["bootstrap_rounds"],
        selection_prob_threshold=settings["selection_probability_threshold"],
        seed=settings["seed"],
    )
    return sample_results, sql_decisions, parameter_decisions


def run_probing(
    database,
    llm_pruning_path,
    workload_path,
    output_path,
    reduced_workload_path,
    max_samples,
    concurrency,
    adapter_options,
    similarity_threshold,
    initial_sql_percent,
    keep_sql_ratio,
    min_sql,
    elite_ratio,
    workload_repeats,
    baseline_repeats,
    active_parameters_per_sample,
    ridge_alpha,
    bootstrap_rounds,
    selection_probability_threshold,
    knob_effect_threshold,
    seed,
):
    adapter = create_adapter(database, adapter_options)
    llm_parameters = load_kept_parameters(llm_pruning_path)
    parameters, no_range_parameters = filter_tunable_parameters(llm_parameters)
    if not parameters:
        raise ValueError("No tunable parameters remain for probing.")

    statements = split_sql_file(workload_path)
    initial_sql, sql_groups = select_initial_sql(statements, similarity_threshold, initial_sql_percent)
    settings = {
        "max_samples": max_samples,
        "concurrency": concurrency,
        "similarity_threshold": similarity_threshold,
        "initial_sql_percent": initial_sql_percent,
        "keep_sql_ratio": keep_sql_ratio,
        "min_sql": min_sql,
        "elite_ratio": elite_ratio,
        "workload_repeats": workload_repeats,
        "baseline_repeats": baseline_repeats,
        "active_parameters_per_sample": active_parameters_per_sample,
        "ridge_alpha": ridge_alpha,
        "bootstrap_rounds": bootstrap_rounds,
        "selection_probability_threshold": selection_probability_threshold,
        "knob_effect_threshold": knob_effect_threshold,
        "seed": seed,
    }

    temp_workload_path = probing_temp_workload(initial_sql)
    try:
        default_sample = default_parameter_sample(parameters)
        baseline_applied = adapter.get_true_values(default_sample) if hasattr(adapter, "get_true_values") else default_sample
        adapter.apply_config(default_sample)
        if hasattr(adapter, "restart"):
            adapter.restart()
        adapter.clear_output_log()
        baseline_workload = run_workload_repeats(adapter, temp_workload_path, concurrency, baseline_repeats)
        remap_probe_sql_ids(baseline_workload["query_info"], initial_sql)
        baseline_result = {
            "record_type": "baseline_result",
            "sample_id": "baseline",
            "params": default_sample,
            "applied_params": baseline_applied,
            "total_time": baseline_workload["total_time"],
            "baseline_time": baseline_workload["total_time"],
            "target": 0.0,
            "workload_repeats": baseline_repeats,
            "repeat_times": baseline_workload["repeat_times"],
            "query_info": baseline_workload["query_info"],
        }
        sample_results, sql_decisions, parameter_decisions = run_sparse_screening(
            adapter,
            parameters,
            initial_sql,
            temp_workload_path,
            settings,
            baseline_result,
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
        "stop_reason": "fixed_sample_count_completed",
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
    parser = argparse.ArgumentParser(description="Run adaptive empirical probing for Stage 2.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--llm-pruning", default=None)
    parser.add_argument("--workload", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--reduced-workload", default=None)
    parser.add_argument("--max-samples", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--adapter-option", action="append", default=[])
    parser.add_argument("--similarity-threshold", type=float, default=0.9)
    parser.add_argument("--initial-sql-percent", type=float, default=10.0)
    parser.add_argument("--keep-sql-ratio", type=float, default=0.6)
    parser.add_argument("--min-sql", type=int, default=1)
    parser.add_argument("--elite-ratio", type=float, default=0.2)
    parser.add_argument("--workload-repeats", type=int, default=3)
    parser.add_argument("--baseline-repeats", type=int, default=3)
    parser.add_argument("--active-parameters-per-sample", type=int, default=8)
    parser.add_argument("--ridge-alpha", type=float, default=1.0)
    parser.add_argument("--bootstrap-rounds", type=int, default=30)
    parser.add_argument("--selection-probability-threshold", type=float, default=0.6)
    parser.add_argument("--knob-effect-threshold", type=float, default=0.02)
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
        max_samples=args.max_samples,
        concurrency=args.concurrency,
        adapter_options=parse_adapter_options(args.adapter_option),
        similarity_threshold=args.similarity_threshold,
        initial_sql_percent=args.initial_sql_percent,
        keep_sql_ratio=args.keep_sql_ratio,
        min_sql=args.min_sql,
        elite_ratio=args.elite_ratio,
        workload_repeats=args.workload_repeats,
        baseline_repeats=args.baseline_repeats,
        active_parameters_per_sample=args.active_parameters_per_sample,
        ridge_alpha=args.ridge_alpha,
        bootstrap_rounds=args.bootstrap_rounds,
        selection_probability_threshold=args.selection_probability_threshold,
        knob_effect_threshold=args.knob_effect_threshold,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
