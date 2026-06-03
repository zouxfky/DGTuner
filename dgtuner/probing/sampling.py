import random


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


def default_sample_value(record):
    value_range = normalize_range(record)
    default = record.get("default") or {}
    default_value = default.get("mysql") if isinstance(default, dict) else default
    if value_range is None:
        return default_value

    if value_range["kind"] == "choice":
        choices = value_range["choices"]
        for index, choice in enumerate(choices):
            if default_value == choice or str(default_value).strip().lower() == str(choice).strip().lower():
                return index
        if str(record.get("type", "")).lower() in {"bool", "boolean"}:
            return 1 if bool(default_value) else 0
        return int(value_range["low"])

    if default_value is None:
        default_value = (value_range["low"] + value_range["high"]) / 2.0
    return coerce_sample_value(record, default_value)


def sample_parameter_value(record, sample_index, sample_count, seed=2026, round_id=1):
    value_range = normalize_range(record)
    if value_range is None:
        return default_sample_value(record)

    default_value = default_sample_value(record)
    if value_range["kind"] == "choice":
        choices = list(range(int(value_range["low"]), int(value_range["high"]) + 1))
        candidates = [value for value in choices if value != default_value]
        if not candidates:
            return default_value
        return candidates[(sample_index + round_id + seed) % len(candidates)]

    low = value_range["low"]
    high = value_range["high"]
    if high <= low:
        return default_value
    rng = random.Random(seed + round_id * 1000003 + sample_index * 9176 + sum(ord(char) for char in parameter_key(record)))
    fraction = (sample_index + 0.5) / max(1, sample_count)
    jitter = rng.uniform(-0.15, 0.15) / max(1, sample_count)
    fraction = max(0.0, min(1.0, fraction + jitter))
    value = low + fraction * (high - low)
    coerced = coerce_sample_value(record, value)
    if coerced == default_value and sample_count > 1:
        fallback_fraction = 0.0 if sample_index % 2 == 0 else 1.0
        coerced = coerce_sample_value(record, low + fallback_fraction * (high - low))
    return coerced


def generate_sparse_screening_samples(parameters, sample_count, active_parameters_per_sample=8, seed=2026):
    tunable = [record for record in parameters if normalize_range(record) is not None]
    default_sample = {parameter_key(record): default_sample_value(record) for record in tunable}
    if not tunable:
        return []

    rng = random.Random(seed)
    active_count = max(1, min(int(active_parameters_per_sample), len(tunable)))
    samples = []
    coverage = {parameter_key(record): 0 for record in tunable}
    for sample_index in range(max(1, int(sample_count))):
        params = dict(default_sample)
        candidates = sorted(
            tunable,
            key=lambda record: (coverage[parameter_key(record)], rng.random()),
        )
        varied_records = candidates[:active_count]
        varied_parameters = []
        for record in varied_records:
            key = parameter_key(record)
            params[key] = sample_parameter_value(record, sample_index, sample_count, seed=seed)
            varied_parameters.append(key)
            coverage[key] += 1
        samples.append({
            "params": params,
            "varied_parameters": varied_parameters,
            "screening_sample_index": sample_index + 1,
        })
    for sample in samples:
        sample["parameter_coverage"] = {
            key: coverage[key]
            for key in sample["varied_parameters"]
        }
    return samples
