import warnings

from scipy.stats import qmc


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


def tunable_parameters(parameters):
    return [record for record in parameters if normalize_range(record) is not None]


def generate_sobol_samples(parameters, n_samples, seed=2026):
    """Sample ``n_samples`` configurations that perturb every tunable knob at once.

    A scrambled Sobol sequence covers the joint space far more evenly than the
    one-at-a-time screening it replaces, so each (expensive) workload run informs
    every knob's importance estimate instead of only a handful.
    """
    tunable = tunable_parameters(parameters)
    if not tunable:
        return []

    ranges = [normalize_range(record) for record in tunable]
    lower = [value_range["low"] for value_range in ranges]
    upper = [value_range["high"] for value_range in ranges]

    sampler = qmc.Sobol(d=len(tunable), scramble=True, seed=seed)
    # a non-power-of-2 sample count only weakens Sobol's balance guarantee slightly,
    # which is irrelevant for coarse screening; silence the benign scipy warning.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        unit_samples = sampler.random(max(1, int(n_samples)))
    scaled = qmc.scale(unit_samples, lower, upper)

    samples = []
    for row in scaled:
        params = {
            parameter_key(record): coerce_sample_value(record, float(value))
            for record, value in zip(tunable, row)
        }
        samples.append({"params": params})
    return samples
