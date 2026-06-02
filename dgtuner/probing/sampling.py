import random

import numpy as np


def parameter_key(record):
    return record.get("id") or record.get("name")


def parameter_id(record):
    return parameter_key(record)


def normalize_range(record):
    value_range = record.get("range") or {}
    param_type = str(record.get("type", "")).lower()
    if "choices" in value_range:
        return {
            "kind": "choice",
            "choices": list(value_range["choices"]),
            "low": 0,
            "high": max(0, len(value_range["choices"]) - 1),
        }
    if param_type in {"bool", "boolean"}:
        return {"kind": "choice", "choices": ["false", "true"], "low": 0, "high": 1}
    if "min" in value_range and "max" in value_range:
        return {
            "kind": "numeric",
            "low": float(value_range["min"]),
            "high": float(value_range["max"]),
            "step": value_range.get("step"),
        }
    return None


def coerce_sample_value(record, value):
    value_range = normalize_range(record)
    if value_range is None:
        return value

    if value_range["kind"] == "choice":
        return int(round(max(value_range["low"], min(value_range["high"], value))))

    low = value_range["low"]
    high = value_range["high"]
    value = max(low, min(high, value))
    step = value_range.get("step")
    param_type = str(record.get("type", "")).lower()
    if step:
        step = float(step)
        if step > 0:
            value = low + round((value - low) / step) * step
            value = max(low, min(high, value))
    if param_type in {"int", "integer", "string"}:
        return int(round(value))
    return round(float(value), 6)


def latin_hypercube(sample_count, dimension_count, seed):
    rng = np.random.default_rng(seed)
    matrix = np.zeros((sample_count, dimension_count))
    for dimension in range(dimension_count):
        points = (np.arange(sample_count) + rng.random(sample_count)) / sample_count
        rng.shuffle(points)
        matrix[:, dimension] = points
    return matrix


def generate_lhs_samples(parameters, sample_count, seed=2026):
    tunable = [(record, normalize_range(record)) for record in parameters]
    tunable = [(record, value_range) for record, value_range in tunable if value_range is not None]
    if not tunable:
        return []

    random.seed(seed)
    matrix = latin_hypercube(sample_count, len(tunable), seed)
    samples = []
    for row in matrix:
        sample = {}
        for index, (record, value_range) in enumerate(tunable):
            raw_value = value_range["low"] + row[index] * (value_range["high"] - value_range["low"])
            sample[parameter_key(record)] = coerce_sample_value(record, raw_value)
        samples.append(sample)
    return samples
