import math

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from dgtuner.probing.analysis import numeric_sample_value
from dgtuner.probing.sampling import (
    default_sample_value,
    normalize_range,
    parameter_id,
    parameter_key,
)


# A knob is kept via the per-SQL recall net only if it drives a query that is at
# least this share of the baseline total runtime (ignore effects on tiny queries).
SQL_WEIGHT_FLOOR = 0.05
MIN_GP_ROWS = 8


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
    """Build the (configs x knobs) feature matrix and total-time target vector."""
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


def per_sql_log_ratio_targets(sample_results, baseline_query_info):
    """Per-SQL response vectors (log speed-up vs baseline) aligned to config rows.

    Returns {sql_id: (y[configs], weight)} where weight is the SQL's share of the
    baseline total runtime. Failed/missing runs become NaN so the caller can drop
    those rows for that SQL.
    """
    baseline = {
        int(item["sql"]): max(float(item["execution_time"]), 1e-9)
        for item in baseline_query_info or []
        if int(item.get("status", 0)) == 0 and item.get("sql") is not None
    }
    total_baseline = sum(baseline.values())
    if not baseline or total_baseline <= 0:
        return {}

    result = {}
    for sql_id, base_latency in baseline.items():
        values = []
        for res in sample_results:
            latency = None
            for item in res.get("query_info", []):
                if int(item["sql"]) == sql_id:
                    if int(item.get("status", 0)) == 0:
                        latency = float(item["execution_time"])
                    break
            if latency is None or latency <= 0:
                values.append(np.nan)
            else:
                values.append(-math.log(max(latency, 1e-9) / base_latency))
        result[sql_id] = (np.asarray(values, dtype=float), base_latency / total_baseline)
    return result


def fit_ard_lengthscales(matrix, targets, seed):
    """Fit one ARD Gaussian process; return its per-dimension length-scales.

    Features are normalized to [0, 1], so a length-scale near the upper bound means
    the surrogate is essentially flat along that knob (irrelevant), while a short
    length-scale means the workload is sensitive to it.
    """
    feature_count = matrix.shape[1]
    kernel = (
        ConstantKernel(1.0, (1e-3, 1e3))
        * RBF(length_scale=np.ones(feature_count), length_scale_bounds=(1e-2, 1e2))
        + WhiteKernel(noise_level=1e-3, noise_level_bounds=(1e-6, 1e1))
    )
    model = GaussianProcessRegressor(
        kernel=kernel,
        normalize_y=True,
        n_restarts_optimizer=3,
        random_state=seed,
    )
    model.fit(matrix, targets)
    length_scale = np.atleast_1d(model.kernel_.k1.k2.length_scale).astype(float)
    if length_scale.size == 1:
        length_scale = np.full(feature_count, float(length_scale[0]))
    return np.clip(length_scale, 1e-6, None)


def aggregate_relevance(matrix, targets, selection_threshold, bagging_rounds, seed):
    """Average ARD relevance (1/length-scale) over subsampled GP fits.

    Per round a knob is "selected" when its relevance share crosses the threshold;
    selection_frequency is the fraction of rounds in which that happened (stability
    selection over the unstable per-dimension length-scale estimates).
    """
    n_rows, feature_count = matrix.shape
    rng = np.random.RandomState(seed)
    subsample = min(n_rows, max(MIN_GP_ROWS, int(round(0.8 * n_rows))))

    relevance_rounds = []
    lengthscale_rounds = []
    selection_counts = np.zeros(feature_count, dtype=float)

    rounds = max(1, int(bagging_rounds))
    for round_id in range(rounds):
        if subsample < n_rows:
            idx = rng.choice(n_rows, size=subsample, replace=False)
        else:
            idx = np.arange(n_rows)
        length_scale = fit_ard_lengthscales(matrix[idx], targets[idx], seed + round_id)
        relevance = 1.0 / length_scale
        relevance_rounds.append(relevance)
        lengthscale_rounds.append(length_scale)
        total = float(relevance.sum())
        share = relevance / total if total > 0 else np.zeros(feature_count)
        selection_counts += (share >= selection_threshold).astype(float)

    mean_relevance = np.mean(relevance_rounds, axis=0)
    mean_lengthscale = np.mean(lengthscale_rounds, axis=0)
    selection_frequency = selection_counts / rounds
    return mean_relevance, mean_lengthscale, selection_frequency


def per_sql_selection(matrix, sample_results, baseline_query_info, selection_threshold, bagging_rounds, seed):
    """Run ARD relevance per heavy SQL; return [(sql_id, weight, frequency[])]."""
    if baseline_query_info is None:
        return []
    sql_targets = per_sql_log_ratio_targets(sample_results, baseline_query_info)
    selections = []
    # heaviest queries first; deterministic per-SQL seed offset
    for offset, sql_id in enumerate(sorted(sql_targets, key=lambda s: sql_targets[s][1], reverse=True)):
        y, weight = sql_targets[sql_id]
        if weight < SQL_WEIGHT_FLOOR:
            continue
        mask = ~np.isnan(y)
        if int(mask.sum()) < MIN_GP_ROWS:
            continue
        sub_x, sub_y = matrix[mask], y[mask]
        if float(np.ptp(sub_y)) <= 0.0:
            continue
        _, _, frequency = aggregate_relevance(
            sub_x, sub_y, selection_threshold, bagging_rounds, seed + 1000 * (offset + 1)
        )
        selections.append((int(sql_id), float(weight), frequency))
    return selections


def rank_parameters_by_importance(
    parameters,
    sample_results,
    baseline_query_info=None,
    importance_threshold=0.01,
    bagging_rounds=5,
    seed=2026,
):
    matrix, targets, keys = encode_configs(parameters, sample_results)
    feature_count = len(keys)
    usable = (
        feature_count > 0
        and matrix.shape[0] >= MIN_GP_ROWS
        and float(np.ptp(targets)) > 0.0
    )

    if usable:
        mean_relevance, mean_lengthscale, freq_total = aggregate_relevance(
            matrix, targets, importance_threshold, bagging_rounds, seed
        )
        sql_selections = per_sql_selection(
            matrix, sample_results, baseline_query_info, importance_threshold, bagging_rounds, seed
        )
    else:
        mean_relevance = np.zeros(feature_count)
        mean_lengthscale = np.full(feature_count, float("inf"))
        freq_total = np.zeros(feature_count)
        sql_selections = []

    total_relevance = float(np.sum(mean_relevance))
    shares = (
        mean_relevance / total_relevance
        if total_relevance > 0
        else np.zeros(feature_count)
    )

    order = np.argsort(mean_relevance)[::-1]
    rank_by_index = {int(index): rank for rank, index in enumerate(order, 1)}

    decisions = []
    for index, record in enumerate(parameters):
        key = parameter_key(record)
        relevance = float(mean_relevance[index])
        share = float(shares[index])
        total_frequency = float(freq_total[index])
        lengthscale = float(mean_lengthscale[index])
        rank = rank_by_index[index]
        relevance_tag = str(record.get("relevance", "")).strip().lower()
        protected = relevance_tag == "high"

        # per-SQL recall net: kept if it stably drives any heavy enough query
        driving_sql = [sql_id for sql_id, _weight, freq in sql_selections if freq[index] >= 0.5]
        keep_total = usable and total_frequency >= 0.5
        keep_sql = bool(driving_sql)
        keep = 1 if (keep_total or keep_sql or protected) else 0

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
            "relevance": relevance,
            "relevance_share": share,
            "mean_lengthscale": lengthscale,
            "total_selection_frequency": total_frequency,
            "relevant_for_sql": driving_sql,
            "selection_threshold": importance_threshold,
            "protected": protected,
        })

    # safety floor: never hand BO an empty search space
    if usable and not any(item["keep"] for item in decisions):
        best = min(decisions, key=lambda item: item["rank"])
        best["keep"] = 1
        best["reason"] = "Kept as the single most relevant knob; none cleared the relevance threshold."

    for item in decisions:
        if item.get("reason"):
            continue
        if item["keep"]:
            if item["protected"]:
                item["reason"] = "Kept because the LLM marked it as high relevance."
            elif item["total_selection_frequency"] >= 0.5:
                item["reason"] = "Kept: ARD-GP relevance on total time cleared the threshold in a majority of rounds."
            else:
                item["reason"] = f"Kept: stably drives heavy query/queries {item['relevant_for_sql']}."
        elif not usable:
            item["reason"] = "Undecided: probing produced too few or degenerate samples for relevance estimation."
        elif item["relevance"] <= 0:
            item["reason"] = "Removed: flat ARD length-scale (no measurable effect on the workload)."
        else:
            item["reason"] = "Removed: relevance stayed below the threshold on total time and on every heavy query."

    return decisions
