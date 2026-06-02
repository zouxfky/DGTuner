import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

from dgtuner.llm_prior.client import call_llm
from dgtuner.llm_prior.config import llm_config
from dgtuner.llm_prior.io import load_text, read_jsonl, write_jsonl
from dgtuner.common.paths import database_knowledge_paths, llm_pruning_path
from dgtuner.llm_prior.paths import DEFAULT_CONTEXT_PATH, DEFAULT_DATABASE, DEFAULT_OUTPUT_PATH, DEFAULT_PARAMETERS_PATH
from dgtuner.llm_prior.prompt import build_prompt, parameter_id
from dgtuner.llm_prior.response import normalize_response


def chunked(items, chunk_size):
    for start in range(0, len(items), chunk_size):
        yield items[start:start + chunk_size]


def run_pruning(parameters_path, context_path, output_path, params_per_prompt, llm_j):
    parameters = read_jsonl(parameters_path)
    context = load_text(context_path)
    config = llm_config()
    chunks = list(chunked(parameters, params_per_prompt))

    def run_chunk(index, chunk):
        response = call_llm(build_prompt(context, chunk), config)
        return index, normalize_response(response)

    decisions = {}
    workers = max(1, int(llm_j))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_chunk, index, chunk): index
            for index, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            _, chunk_decisions = future.result()
            decisions.update(chunk_decisions)

    records = []
    for record in parameters:
        param_id = parameter_id(record)
        decision = decisions.get(param_id, {
            "keep": 1,
            "reason": "No LLM decision found; keep conservatively.",
        })
        output_record = dict(record)
        output_record["keep"] = decision["keep"]
        output_record["reason"] = decision["reason"]
        records.append(output_record)

    write_jsonl(output_path, records)
    keep_count = sum(1 for record in records if record["keep"] == 1)
    remove_count = sum(1 for record in records if record["keep"] == 0)
    return {
        "output": str(output_path),
        "candidate_count": len(records),
        "keep_count": keep_count,
        "remove_count": remove_count,
        "params_per_prompt": params_per_prompt,
        "prompt_count": len(chunks),
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

    default_parameters, default_context = database_knowledge_paths(args.database)
    parameters_path = args.parameters or str(default_parameters)
    context_path = args.context or str(default_context)
    output_path = args.output or str(llm_pruning_path(args.database))
    result = run_pruning(
        parameters_path=parameters_path,
        context_path=context_path,
        output_path=output_path,
        params_per_prompt=args.params_per_prompt,
        llm_j=args.llm_j,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
