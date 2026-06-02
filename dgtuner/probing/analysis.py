from collections import defaultdict
import math
import statistics

from dgtuner.probing.sampling import normalize_range, parameter_id, parameter_key


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


def rank_sql_by_sensitivity(selected_sql, sample_results, keep_ratio, min_sql):
    per_sql = defaultdict(list)
    for result in sample_results:
        for item in result["query_info"]:
            per_sql[item["sql"]].append(item)

    decisions = []
    for item in selected_sql:
        times = [
            float(row["execution_time"])
            for row in per_sql[item["sql_id"]]
            if int(row.get("status", 0)) == 0
        ]
        avg_time = statistics.fmean(times) if times else 0.0
        cv = coefficient_of_variation(times)
        decisions.append({
            "record_type": "sql_decision",
            "sql_id": item["sql_id"],
            "keep": 0,
            "cv": cv,
            "avg_execution_time": avg_time,
            "sensitivity_score": cv * math.log1p(avg_time),
            "sql": item["sql"],
        })

    keep_count = min(len(decisions), max(min_sql, math.ceil(len(decisions) * keep_ratio)))
    keep_ids = {
        item["sql_id"]
        for item in sorted(decisions, key=lambda row: row["sensitivity_score"], reverse=True)[:keep_count]
    }
    for item in decisions:
        item["keep"] = 1 if item["sql_id"] in keep_ids else 0
    return sorted(decisions, key=lambda row: row["sql_id"])


def pearson_correlation(xs, ys):
    if len(xs) != len(ys) or len(xs) < 4:
        return 0.0
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denominator_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    return 0.0 if denominator_x == 0 or denominator_y == 0 else numerator / (denominator_x * denominator_y)


def numeric_sample_value(value):
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
        return float(abs(hash(lowered)) % 100000)


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


def rank_parameters_by_correlation(parameters, samples, sample_results, threshold, elite_ratio):
    targets = [result["target"] for result in sample_results]
    elite_count = max(1, math.ceil(len(sample_results) * elite_ratio))
    elite_sample_ids = {
        item["sample_id"]
        for item in sorted(sample_results, key=lambda row: row["target"], reverse=True)[:elite_count]
    }
    decisions = []
    for record in parameters:
        key = parameter_key(record)
        values = [numeric_sample_value(sample[key]) for sample in samples if key in sample]
        elite_values = [
            numeric_sample_value(samples[result["sample_id"]][key])
            for result in sample_results
            if result["sample_id"] in elite_sample_ids and key in samples[result["sample_id"]]
        ]
        correlation = pearson_correlation(values, targets)
        changed = len(set(values)) > 1
        keep = 1 if not changed or abs(correlation) >= threshold else 0
        decisions.append({
            "record_type": "parameter_decision",
            "id": parameter_id(record),
            "name": key,
            "display_name": record.get("name") or key,
            "format": record.get("format"),
            "type": record.get("type"),
            "default": record.get("default"),
            "range": record.get("range"),
            "keep": keep,
            "correlation": correlation,
            "narrowed_range": narrow_range(record, elite_values),
            "reason": (
                "Kept because sampled values correlate with workload target."
                if keep else
                "Removed because sampled values show weak correlation with workload target."
            ),
        })
    return decisions


def kept_ids(decisions, key):
    return {item[key] for item in decisions if int(item.get("keep", 0)) == 1}


def jaccard_similarity(left, right):
    if not left and not right:
        return 1.0
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def top_correlated_knobs(parameter_decisions, top_k):
    ranked = sorted(parameter_decisions, key=lambda item: abs(float(item.get("correlation", 0.0))), reverse=True)
    return {item["name"] for item in ranked[:max(1, top_k)]}


def stability_status(previous_round, sql_decisions, parameter_decisions, thresholds, top_k_knobs):
    current_sql = kept_ids(sql_decisions, "sql_id")
    current_knobs = kept_ids(parameter_decisions, "name")
    current_top_knobs = top_correlated_knobs(parameter_decisions, top_k_knobs)
    current = {"sql": current_sql, "knobs": current_knobs, "top_knobs": current_top_knobs}
    if previous_round is None:
        return current, {"stable": False, "sql_jaccard": None, "knob_jaccard": None, "rank_jaccard": None}

    sql_jaccard = jaccard_similarity(previous_round["sql"], current_sql)
    knob_jaccard = jaccard_similarity(previous_round["knobs"], current_knobs)
    rank_jaccard = jaccard_similarity(previous_round["top_knobs"], current_top_knobs)
    return current, {
        "stable": (
            sql_jaccard >= thresholds["sql"]
            and knob_jaccard >= thresholds["knob"]
            and rank_jaccard >= thresholds["rank"]
        ),
        "sql_jaccard": sql_jaccard,
        "knob_jaccard": knob_jaccard,
        "rank_jaccard": rank_jaccard,
    }
