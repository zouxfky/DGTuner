import statistics

import numpy as np
from scipy.stats import spearmanr

from dgtuner.probing.sampling import normalize_range


def normalize_query_info(query_info):
    normalized = []
    for item in query_info or []:
        sql_index = item.get("sql") or item.get("sql_id")
        if sql_index is None:
            continue
        status = item.get("status")
        if status is None:
            status = item.get("status_code", 0)
        time_value = item.get("avg_execution_time")
        if time_value is None:
            time_value = item.get("execution_time")
        if time_value is None:
            continue
        normalized.append({
            "sql": int(sql_index),
            "status": int(status),
            "execution_time": float(time_value),
        })
    return normalized


def coefficient_of_variation(values):
    if not values:
        return 0.0
    mean = statistics.fmean(values)
    return 0.0 if mean == 0 else statistics.pstdev(values) / mean


def baseline_query_times(baseline_query_info):
    return {
        int(item["sql"]): max(float(item.get("execution_time", 0.0)), 1e-9)
        for item in baseline_query_info or []
        if item.get("sql") is not None
    }


def choice_index(value, choices):
    for index, choice in enumerate(choices):
        if value == choice:
            return float(index)
        if str(value).strip().lower() == str(choice).strip().lower():
            return float(index)
    try:
        numeric = int(round(float(value)))
        if 0 <= numeric < len(choices):
            return float(numeric)
    except (TypeError, ValueError):
        pass
    return None


def numeric_sample_value(value, record=None):
    if record is not None:
        value_range = normalize_range(record)
        if value_range is not None and value_range["kind"] == "choice":
            index = choice_index(value, value_range["choices"])
            if index is not None:
                return index
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    lowered = str(value).strip().lower()
    if lowered in {"true", "on", "yes"}:
        return 1.0
    if lowered in {"false", "off", "no"}:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return float(sum((index + 1) * ord(char) for index, char in enumerate(lowered)))


def _per_sql_latency(initial_sql, sample_results):
    """Latency of every initial SQL across configs; failed runs become a slow penalty."""
    sql_ids = [item["sql_id"] for item in initial_sql]
    config_count = len(sample_results)
    successful = {sql_id: [] for sql_id in sql_ids}
    raw = {sql_id: [None] * config_count for sql_id in sql_ids}

    for config_index, result in enumerate(sample_results):
        for item in result.get("query_info", []):
            sql_id = int(item["sql"])
            if sql_id not in raw:
                continue
            time_value = float(item["execution_time"])
            if int(item.get("status", 0)) == 0:
                successful[sql_id].append(time_value)
                raw[sql_id][config_index] = time_value

    latency = {}
    for sql_id in sql_ids:
        times = successful[sql_id]
        if not times:
            continue
        penalty = max(times) * 2.0
        latency[sql_id] = np.array(
            [value if value is not None else penalty for value in raw[sql_id]],
            dtype=float,
        )
    return latency


def _spearman(left, right):
    if len(left) < 2 or np.ptp(left) == 0 or np.ptp(right) == 0:
        return -1.0
    correlation, _ = spearmanr(left, right)
    return -1.0 if np.isnan(correlation) else float(correlation)


def select_reduced_sql_by_rank_correlation(
    initial_sql,
    sample_results,
    keep_threshold=0.95,
    min_sql=1,
    max_sql=None,
):
    """Greedily pick the smallest SQL subset whose config ranking matches the full set.

    The full per-config ``target`` already reflects the whole (deduplicated) initial
    SQL set, so a subset that reproduces its Spearman ranking across the sampled
    configs is provably representative for the downstream search.
    """
    sql_by_id = {item["sql_id"]: item for item in initial_sql}
    latency = _per_sql_latency(initial_sql, sample_results)
    full_target = np.array([float(result.get("target", 0.0)) for result in sample_results], dtype=float)

    candidates = [sql_id for sql_id in sql_by_id if sql_id in latency]
    cap = len(candidates) if max_sql is None else min(int(max_sql), len(candidates))
    floor = max(1, min(int(min_sql), cap)) if cap else 0

    selected = []
    selected_spearman = {}
    running_score = np.zeros(len(sample_results), dtype=float)
    remaining = set(candidates)
    while remaining and len(selected) < cap:
        best_id = None
        best_corr = -2.0
        for sql_id in remaining:
            score = running_score - latency[sql_id]
            corr = _spearman(score, full_target)
            if corr > best_corr:
                best_corr = corr
                best_id = sql_id
        if best_id is None:
            break
        selected.append(best_id)
        selected_spearman[best_id] = best_corr
        running_score = running_score - latency[best_id]
        remaining.discard(best_id)
        if best_corr >= keep_threshold and len(selected) >= floor:
            break

    keep_ids = set(selected)
    rank_by_id = {sql_id: rank for rank, sql_id in enumerate(selected, 1)}
    decisions = []
    for item in initial_sql:
        sql_id = item["sql_id"]
        times = latency.get(sql_id)
        decisions.append({
            "record_type": "sql_decision",
            "sql_id": sql_id,
            "keep": 1 if sql_id in keep_ids else 0,
            "rank": rank_by_id.get(sql_id),
            "spearman_at_select": selected_spearman.get(sql_id),
            "avg_execution_time": float(np.mean(times)) if times is not None else 0.0,
            "cv": coefficient_of_variation(list(times)) if times is not None else 0.0,
            "sql": item["sql"],
        })
    return sorted(decisions, key=lambda row: row["sql_id"])
