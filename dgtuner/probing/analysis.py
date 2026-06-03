from collections import defaultdict
import math
import statistics

import numpy as np

from dgtuner.probing.sampling import default_sample_value, normalize_range, parameter_id, parameter_key


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


def rank_sql_by_sensitivity(selected_sql, sample_results, keep_ratio, min_sql, baseline_query_info=None):
    per_sql = defaultdict(list)
    for result in sample_results:
        for item in result["query_info"]:
            per_sql[item["sql"]].append(item)
    baseline_times = baseline_query_times(baseline_query_info)

    decisions = []
    for item in selected_sql:
        times = [
            float(row["execution_time"])
            for row in per_sql[item["sql_id"]]
            if int(row.get("status", 0)) == 0
        ]
        avg_time = statistics.fmean(times) if times else 0.0
        cv = coefficient_of_variation(times)
        baseline_time = baseline_times.get(item["sql_id"], avg_time if avg_time > 0 else 1e-9)
        log_ratios = [math.log(max(value, 1e-9) / baseline_time) for value in times]
        log_ratio_mean = statistics.fmean(log_ratios) if log_ratios else 0.0
        log_ratio_stdev = statistics.pstdev(log_ratios) if len(log_ratios) > 1 else 0.0
        decisions.append({
            "record_type": "sql_decision",
            "sql_id": item["sql_id"],
            "keep": 0,
            "cv": cv,
            "avg_execution_time": avg_time,
            "baseline_execution_time": baseline_time,
            "log_ratio_mean": log_ratio_mean,
            "log_ratio_stdev": log_ratio_stdev,
            "sensitivity_score": log_ratio_stdev * math.log1p(baseline_time),
            "sql": item["sql"],
        })

    keep_count = min(len(decisions), max(min_sql, math.ceil(len(decisions) * keep_ratio)))
    ranked = sorted(decisions, key=lambda row: row["sensitivity_score"], reverse=True)
    keep_ids = {item["sql_id"] for item in ranked[:keep_count]}
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
        item["keep_count"] = keep_count
    for item in decisions:
        item["keep"] = 1 if item["sql_id"] in keep_ids else 0
    return sorted(decisions, key=lambda row: row["sql_id"])


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


def narrow_range(record, elite_values):
    value_range = normalize_range(record)
    if not elite_values or value_range is None or value_range["kind"] != "numeric":
        return record.get("range")

    low = value_range["low"]
    high = value_range["high"]
    padding = (high - low) * 0.05
    narrowed_low = max(low, min(elite_values) - padding)
    narrowed_high = min(high, max(elite_values) + padding)
    if str(record.get("type", "")).lower() in {"int", "integer", "string"}:
        narrowed_low = int(round(narrowed_low))
        narrowed_high = int(round(narrowed_high))
    result = {"min": narrowed_low, "max": narrowed_high}
    if value_range.get("step") is not None:
        result["step"] = value_range["step"]
    return result


def scaled_parameter_delta(record, value):
    value_range = normalize_range(record)
    if value_range is None:
        return 0.0
    default_value = numeric_sample_value(default_sample_value(record), record)
    numeric_value = numeric_sample_value(value, record)
    width = max(float(value_range["high"]) - float(value_range["low"]), 1.0)
    return (numeric_value - default_value) / width


def ridge_coefficients(matrix, targets, ridge_alpha):
    if matrix.size == 0:
        return np.array([])
    rows, columns = matrix.shape
    augmented_x = np.vstack([matrix, math.sqrt(ridge_alpha) * np.eye(columns)])
    augmented_y = np.concatenate([targets, np.zeros(columns)])
    coefficients, *_ = np.linalg.lstsq(augmented_x, augmented_y, rcond=None)
    return coefficients


def bootstrap_sparse_scores(matrix, targets, ridge_alpha, bootstrap_rounds, seed):
    rng = np.random.RandomState(seed)
    sample_count = matrix.shape[0]
    if sample_count == 0:
        return []
    scores = []
    for _round in range(max(1, int(bootstrap_rounds))):
        row_ids = rng.randint(0, sample_count, size=sample_count)
        scores.append(np.abs(ridge_coefficients(matrix[row_ids], targets[row_ids], ridge_alpha)))
    return np.asarray(scores)


def rank_parameters_by_sparse_effect(
    parameters,
    sample_results,
    threshold,
    elite_ratio,
    ridge_alpha=1.0,
    bootstrap_rounds=30,
    selection_prob_threshold=0.6,
    seed=2026,
):
    keys = [parameter_key(record) for record in parameters]
    record_by_key = {parameter_key(record): record for record in parameters}
    rows = []
    targets = []
    coverage = defaultdict(int)
    values_by_parameter = defaultdict(list)
    for result in sample_results:
        params = result.get("params") or {}
        varied = set(result.get("varied_parameters") or [])
        row = []
        for key in keys:
            record = record_by_key[key]
            value = params.get(key, default_sample_value(record))
            delta = scaled_parameter_delta(record, value) if key in varied else 0.0
            row.append(delta)
            if key in varied:
                coverage[key] += 1
                values_by_parameter[key].append(numeric_sample_value(value, record))
        rows.append(row)
        targets.append(float(result.get("target", 0.0)))

    matrix = np.asarray(rows, dtype=float)
    target_array = np.asarray(targets, dtype=float)
    if len(target_array) > 0:
        target_array = target_array - float(np.mean(target_array))

    coefficients = ridge_coefficients(matrix, target_array, ridge_alpha)
    bootstrap_scores = bootstrap_sparse_scores(matrix, target_array, ridge_alpha, bootstrap_rounds, seed)
    median_bootstrap_scores = np.median(bootstrap_scores, axis=0) if len(bootstrap_scores) else np.abs(coefficients)
    selection_probs = (
        np.mean(bootstrap_scores >= threshold, axis=0)
        if len(bootstrap_scores)
        else np.zeros(len(keys))
    )

    decisions = []
    for index, record in enumerate(parameters):
        key = parameter_key(record)
        score = float(median_bootstrap_scores[index]) if len(median_bootstrap_scores) else 0.0
        coefficient = float(coefficients[index]) if len(coefficients) else 0.0
        selection_prob = float(selection_probs[index]) if len(selection_probs) else 0.0
        sampled_values = values_by_parameter[key]
        changed = bool(sampled_values)
        passes_threshold = changed and (score >= threshold or selection_prob >= selection_prob_threshold)
        elite_count = max(1, math.ceil(len(sample_results) * elite_ratio)) if sample_results else 0
        elite_sample_ids = {
            item["sample_id"]
            for item in sorted(sample_results, key=lambda row: row.get("target", 0.0), reverse=True)[:elite_count]
        }
        elite_values = [
            numeric_sample_value(row.get("params", {}).get(key), record)
            for row in sample_results
            if row.get("sample_id") in elite_sample_ids and key in (row.get("varied_parameters") or [])
        ]
        decisions.append({
            "record_type": "parameter_decision",
            "id": parameter_id(record),
            "name": key,
            "display_name": record.get("name") or key,
            "format": record.get("format"),
            "type": record.get("type"),
            "default": record.get("default"),
            "range": record.get("range"),
            "keep": 0,
            "sample_count": coverage[key],
            "changed": changed,
            "coefficient": coefficient,
            "bootstrap_median_abs_coefficient": score,
            "selection_probability": selection_prob,
            "score": score,
            "threshold": threshold,
            "selection_probability_threshold": selection_prob_threshold,
            "passes_threshold": passes_threshold,
            "narrowed_range": narrow_range(record, elite_values),
        })

    ranked = sorted(decisions, key=lambda row: row["score"], reverse=True)
    rank_by_name = {item["name"]: rank for rank, item in enumerate(ranked, 1)}
    for item in decisions:
        item["rank"] = rank_by_name[item["name"]]
        item["keep"] = 1 if item["passes_threshold"] else 0
        if item["keep"]:
            item["reason"] = "Kept because sparse screening showed a stable workload effect."
        elif item["sample_count"] == 0:
            item["reason"] = "Removed because this parameter was not sampled within the probing budget."
        elif not item["changed"]:
            item["reason"] = "Removed because sampled values did not vary during probing."
        else:
            item["reason"] = "Removed because sparse screening showed weak or unstable workload effect."
    return decisions

