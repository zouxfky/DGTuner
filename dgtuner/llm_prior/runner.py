import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from dgtuner.llm_prior.client import call_llm
from dgtuner.llm_prior.config import llm_config
from dgtuner.llm_prior.io import load_text, read_jsonl, write_jsonl
from dgtuner.common.paths import database_knowledge_paths, llm_pruning_path
from dgtuner.llm_prior.paths import DEFAULT_DATABASE
from dgtuner.llm_prior.prompt import build_prompt, parameter_id
from dgtuner.llm_prior.response import normalize_response


def runtime_run_paths(database):
    from dgtuner.run_config import resolve_run_config
    from dgtuner.common.paths import PROJECT_ROOT

    config_path = PROJECT_ROOT / "configs" / "runs" / f"{database}_tpch.yaml"
    if not config_path.exists():
        return None
    return resolve_run_config(config_path)


def chunked(items, chunk_size):
    for start in range(0, len(items), chunk_size):
        yield items[start:start + chunk_size]


def load_existing_decisions(output_path, parameter_ids):
    path = Path(output_path)
    if not path.exists():
        return {}
    decisions = {}
    valid_ids = set(parameter_ids)
    for record in read_jsonl(path):
        param_id = parameter_id(record)
        if param_id in valid_ids and "keep" in record and record.get("reason"):
            decisions[param_id] = {
                "keep": int(record.get("keep", 1)),
                "reason": record.get("reason", ""),
            }
    return decisions


def build_records(parameters, decisions):
    records = []
    for record in parameters:
        param_id = parameter_id(record)
        decision = decisions.get(param_id, {
            "keep": 1,
            "reason": "Pending LLM decision; keep conservatively until this chunk completes.",
        })
        output_record = dict(record)
        output_record["keep"] = decision["keep"]
        output_record["reason"] = decision["reason"]
        records.append(output_record)
    return records


def flush_records(output_path, parameters, decisions):
    write_jsonl(output_path, build_records(parameters, decisions))


def run_pruning(parameters_path, context_path, output_path, params_per_prompt, llm_j):
    parameters = read_jsonl(parameters_path)
    context = load_text(context_path)
    config = llm_config()
    parameter_ids = [parameter_id(record) for record in parameters]
    decisions = load_existing_decisions(output_path, parameter_ids)
    pending_parameters = [record for record in parameters if parameter_id(record) not in decisions]
    chunks = list(chunked(pending_parameters, params_per_prompt))
    flush_records(output_path, parameters, decisions)

    def run_chunk(index, chunk):
        response = call_llm(build_prompt(context, chunk), config)
        return index, normalize_response(response)

    workers = max(1, int(llm_j))
    total_chunks = len(chunks)
    print(
        f"[stage1] {len(parameters)} params | {len(pending_parameters)} pending | "
        f"{total_chunks} chunks x {params_per_prompt} | {workers} workers | model={config['model']}",
        flush=True,
    )
    if total_chunks == 0:
        print("[stage1] nothing pending; all decisions resumed from existing output", flush=True)

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_chunk, index, chunk): index
            for index, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            index = futures[future]
            completed += 1
            try:
                _, chunk_decisions = future.result()
            except Exception as error:
                print(f"[stage1] chunk {completed}/{total_chunks} (#{index + 1}) FAILED: {error}", flush=True)
                continue
            decisions.update(chunk_decisions)
            flush_records(output_path, parameters, decisions)
            kept = sum(1 for decision in decisions.values() if decision["keep"] == 1)
            removed = sum(1 for decision in decisions.values() if decision["keep"] == 0)
            print(
                f"[stage1] chunk {completed}/{total_chunks} done | decided={len(decisions)} "
                f"keep={kept} remove={removed}",
                flush=True,
            )

    records = build_records(parameters, decisions)
    keep_count = sum(1 for record in records if record["keep"] == 1)
    remove_count = sum(1 for record in records if record["keep"] == 0)
    completed_count = sum(
        1
        for record in records
        if record.get("reason") != "Pending LLM decision; keep conservatively until this chunk completes."
    )
    return {
        "output": str(output_path),
        "candidate_count": len(records),
        "completed_count": completed_count,
        "keep_count": keep_count,
        "remove_count": remove_count,
        "params_per_prompt": params_per_prompt,
        "prompt_count": len(chunks),
        "resumed_count": len(parameters) - len(pending_parameters),
        "llm_j": workers,
        "model": config["model"],
        "api_base_url": config["api_base_url"],
    }


def main():
    parser = argparse.ArgumentParser(description="Run LLM-based parameter pruning.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--parameters", default=None)
    parser.add_argument("--context", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--params-per-prompt", type=int, default=10)
    parser.add_argument("--llm-j", type=int, default=1)
    args = parser.parse_args()

    default_parameters = database_knowledge_paths(args.database)
    run_paths = runtime_run_paths(args.database)
    parameters_path = args.parameters or str(default_parameters)
    if args.context:
        context_path = args.context
    elif run_paths:
        context_path = str(run_paths["context"])
    else:
        raise ValueError("Missing --context. No workload context can be inferred without a runtime benchmark config.")
    output_path = args.output or str(run_paths["llm_pruning"] if run_paths else llm_pruning_path(args.database))
    result = run_pruning(
        parameters_path=parameters_path,
        context_path=context_path,
        output_path=output_path,
        params_per_prompt=args.params_per_prompt,
        llm_j=args.llm_j,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
