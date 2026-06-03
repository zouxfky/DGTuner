import math

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance

from dgtuner.probing.analysis import numeric_sample_value
from dgtuner.probing.sampling import (
    default_sample_value,
    normalize_range,
    parameter_id,
    parameter_key,
    tunable_parameters,
)


def normalized_feature(record, value):
    """Encode a knob value as a float in [0, 1] over its tunable range."""
    value_range = normalize_range(record)
    if value_range is None:
        return 0.0
    low = float(value_range["low"])
    high = float(value_range["high"])
    if high <= low:
        return 0.0
    numeric = numeric_sample_value(value, record)
    return max(0.0, min(1.0, (numeric - low) / (high - low)))


def encode_configs(parameters, sample_results):
    """Build the (configs x knobs) feature matrix and target vector."""
    keys = [parameter_key(record) for record in parameters]
    record_by_key = {parameter_key(record): record for record in parameters}
    rows = []
    targets = []
    for result in sample_results:
        params = result.get("params") or {}
        row = []
        for key in keys:
            record = record_by_key[key]
            value = params.get(key, default_sample_value(record))
            row.append(normalized_feature(record, value))
        rows.append(row)
        targets.append(float(result.get("target", 0.0)))
    return np.asarray(rows, dtype=float), np.asarray(targets, dtype=float), keys


def aggregate_importance(matrix, targets, keep_top_k, bagging_rounds, seed):
    """Average permutation importance over several random forests (stability selection)."""
    feature_count = matrix.shape[1]
    importance_rounds = []
    top_k = max(1, min(int(keep_top_k), feature_count))
    selection_counts = np.zeros(feature_count, dtype=float)

    rounds = max(1, int(bagging_rounds))
    for round_id in range(rounds):
        model = RandomForestRegressor(
            n_estimators=300,
            max_features="sqrt",
            min_samples_leaf=1,
            random_state=seed + round_id,
            n_jobs=-1,
        )
        model.fit(matrix, targets)
        result = permutation_importance(
            model,
            matrix,
            targets,
            n_repeats=10,
            random_state=seed + round_id,
            n_jobs=-1,
        )
        importance = np.clip(result.importances_mean, 0.0, None)
        importance_rounds.append(importance)
        top_indices = np.argsort(importance)[::-1][:top_k]
        selection_counts[top_indices] += 1.0

    mean_importance = np.mean(importance_rounds, axis=0)
    selection_frequency = selection_counts / rounds
    return mean_importance, selection_frequency


def rank_parameters_by_importance(
    parameters,
    sample_results,
    keep_top_k=12,
    importance_threshold=0.0,
    bagging_rounds=5,
    seed=2026,
):
    matrix, targets, keys = encode_configs(parameters, sample_results)
    feature_count = len(keys)
    usable = (
        feature_count > 0
        and matrix.shape[0] >= 4
        and float(np.ptp(targets)) > 0.0
    )

    if usable:
        mean_importance, selection_frequency = aggregate_importance(
            matrix, targets, keep_top_k, bagging_rounds, seed
        )
    else:
        mean_importance = np.zeros(feature_count)
        selection_frequency = np.zeros(feature_count)

    total_importance = float(np.sum(mean_importance))
    shares = (
        mean_importance / total_importance
        if total_importance > 0
        else np.zeros(feature_count)
    )

    order = np.argsort(mean_importance)[::-1]
    rank_by_index = {int(index): rank for rank, index in enumerate(order, 1)}
    top_k = max(1, min(int(keep_top_k), feature_count)) if feature_count else 0
    top_indices = set(int(index) for index in order[:top_k])

    decisions = []
    for index, record in enumerate(parameters):
        key = parameter_key(record)
        importance = float(mean_importance[index])
        share = float(shares[index])
        frequency = float(selection_frequency[index])
        rank = rank_by_index[index]
        relevance = str(record.get("relevance", "")).strip().lower()
        protected = relevance == "high"
        if not usable:
            keep = 1 if (rank <= top_k or protected) else 0
        else:
            passes = (share >= importance_threshold or index in top_indices) and frequency >= 0.5
            keep = 1 if (passes or protected) else 0

        decisions.append({
            "record_type": "parameter_decision",
            "id": parameter_id(record),
            "name": key,
            "display_name": record.get("name") or key,
            "format": record.get("format"),
            "type": record.get("type"),
            "default": record.get("default"),
            "range": record.get("range"),
            "narrowed_range": record.get("range"),
            "keep": keep,
            "rank": rank,
            "importance": importance,
            "importance_share": share,
            "selection_frequency": frequency,
            "keep_top_k": top_k,
            "importance_threshold": importance_threshold,
            "protected": protected,
        })

    for item in decisions:
        if item["keep"]:
            if item["protected"]:
                item["reason"] = "Kept because the LLM marked it as high relevance."
            else:
                item["reason"] = "Kept because random-forest permutation importance was stable across bagging rounds."
        elif not usable:
            item["reason"] = "Kept-by-rank only; probing produced too few or degenerate samples for importance estimation."
        elif item["importance"] <= 0:
            item["reason"] = "Removed because permutation importance showed no measurable workload effect."
        else:
            item["reason"] = "Removed because importance was below threshold or unstable across bagging rounds."

    return decisions
