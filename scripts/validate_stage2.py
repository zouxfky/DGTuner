"""Offline validation for the rewritten Stage 2 (no database required).

Run with:  .venv/bin/python scripts/validate_stage2.py
"""
import random

import numpy as np

from dgtuner.common.paths import database_knowledge_paths
from dgtuner.probing.analysis import select_reduced_sql_by_rank_correlation
from dgtuner.probing.importance import rank_parameters_by_importance
from dgtuner.probing.io import read_jsonl
from dgtuner.probing.sampling import generate_sobol_samples, normalize_range


def test_parameter_importance():
    parameters = [
        {"id": f"p{i}", "name": f"p{i}", "type": "int", "range": {"min": 0, "max": 100}}
        for i in range(20)
    ]
    important = {"p3": 3.0, "p7": -2.5, "p11": 1.8}
    planned = generate_sobol_samples(parameters, 64, seed=7)
    rng = random.Random(7)
    sample_results = []
    for sample in planned:
        params = sample["params"]
        target = sum(weight * (params[name] / 100.0) for name, weight in important.items())
        target += rng.gauss(0, 0.02)
        sample_results.append({"params": params, "target": target})

    decisions = rank_parameters_by_importance(
        parameters, sample_results, keep_top_k=5, bagging_rounds=3, seed=7
    )
    kept = {d["name"] for d in decisions if d["keep"] == 1}
    top3 = {d["name"] for d in sorted(decisions, key=lambda r: r["rank"])[:3]}
    print("kept knobs:", sorted(kept))
    print("top-3 by importance:", sorted(top3))
    assert set(important) <= kept, f"important knobs not all kept: {set(important) - kept}"
    assert set(important) == top3, f"important knobs are not the top-3: {top3}"
    print("[OK] parameter importance recovers the truly influential knobs\n")


def test_sql_rank_correlation():
    n_sql, n_config = 10, 40
    sensitive = {2, 5, 8}  # -> sql_id 3, 6, 9
    initial_sql = [
        {"sql_id": i + 1, "sql": f"select {i}", "features": {}} for i in range(n_sql)
    ]
    rng = random.Random(11)
    sample_results = []
    for _config in range(n_config):
        query_info = []
        total = 0.0
        for i in range(n_sql):
            latency = rng.uniform(1.0, 10.0) if i in sensitive else 5.0
            query_info.append({"sql": i + 1, "status": 0, "execution_time": latency})
            total += latency
        sample_results.append({"target": -total, "query_info": query_info})

    decisions = select_reduced_sql_by_rank_correlation(
        initial_sql, sample_results, keep_threshold=0.95, min_sql=1
    )
    kept = {d["sql_id"] for d in decisions if d["keep"] == 1}
    best_corr = max((d["spearman_at_select"] or -1) for d in decisions)
    print("kept sql_ids:", sorted(kept), "best spearman:", round(best_corr, 4))
    assert kept and kept <= {3, 6, 9}, f"selected a non-sensitive SQL: {kept}"
    assert best_corr >= 0.95, f"final rank correlation too low: {best_corr}"
    print("[OK] SQL selection keeps only config-sensitive queries\n")


def test_sobol_sampler_validity():
    parameters = read_jsonl(str(database_knowledge_paths("dingodb")))
    samples = generate_sobol_samples(parameters, 30, seed=2026)
    assert len(samples) == 30
    for sample in samples:
        for record in parameters:
            key = record.get("id") or record.get("name")
            value_range = normalize_range(record)
            if value_range is None or key not in sample["params"]:
                continue
            value = sample["params"][key]
            if value_range["kind"] == "choice":
                assert int(value_range["low"]) <= value <= int(value_range["high"]), (key, value)
            else:
                assert value_range["low"] <= value <= value_range["high"], (key, value)
    print(f"[OK] Sobol sampler produced 30 in-range configs over {len(parameters)} knobs\n")


if __name__ == "__main__":
    test_parameter_importance()
    test_sql_rank_correlation()
    test_sobol_sampler_validity()
    print("All offline Stage 2 checks passed.")
