import random
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


# A numeric knob with at most this many legal values is treated as discrete (its
# few values are spread by balanced shuffling, not by Sobol thresholding which
# would produce identical/collinear low-cardinality columns).
DISCRETE_MAX_VALUES = 16


def discrete_values(record):
    """Legal sample values for a discrete knob, or None if the knob is continuous.

    Choice/bool -> the choice indices [0..k-1]. Small-range int -> the grid values
    low, low+step, ... <= high. Returns None for continuous numerics.
    """
    value_range = normalize_range(record)
    if value_range is None:
        return None
    if value_range["kind"] == "choice":
        return list(range(int(value_range["low"]), int(value_range["high"]) + 1))
    step = value_range.get("step")
    if not step or float(step) <= 0:
        return None
    low, high, step = float(value_range["low"]), float(value_range["high"]), float(step)
    count = int(round((high - low) / step)) + 1
    if count > DISCRETE_MAX_VALUES:
        return None
    return [low + i * step for i in range(count)]


def balanced_shuffled_column(values, n_samples, rng):
    """A length-n column over ``values`` that is balanced (each value ~n/k times)
    and independently ordered (its own RNG), so discrete columns never coincide."""
    column = []
    while len(column) < n_samples:
        block = list(values)
        rng.shuffle(block)
        column.extend(block)
    return column[:n_samples]


def generate_sobol_samples(parameters, n_samples, seed=2026):
    """Sample ``n_samples`` configurations that perturb every tunable knob at once.

    Continuous knobs are covered with a scrambled Sobol sequence; discrete knobs
    (bool/enum/small-range int) are spread by balanced independent shuffling so
    low-cardinality dimensions don't collapse into identical, collinear columns.
    """
    tunable = tunable_parameters(parameters)
    if not tunable:
        return []
    n_samples = max(1, int(n_samples))

    continuous, discrete = [], []
    for record in tunable:
        (discrete if discrete_values(record) is not None else continuous).append(record)

    # continuous -> Sobol
    continuous_columns = {}
    if continuous:
        ranges = [normalize_range(record) for record in continuous]
        lower = [r["low"] for r in ranges]
        upper = [r["high"] for r in ranges]
        sampler = qmc.Sobol(d=len(continuous), scramble=True, seed=seed)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            unit = sampler.random(n_samples)
        scaled = qmc.scale(unit, lower, upper)
        for col, record in enumerate(continuous):
            continuous_columns[parameter_key(record)] = [scaled[i][col] for i in range(n_samples)]

    # discrete -> balanced independent shuffle (own RNG per knob)
    discrete_columns = {}
    for record in discrete:
        key = parameter_key(record)
        rng = random.Random(f"{seed}:{key}")
        discrete_columns[key] = balanced_shuffled_column(discrete_values(record), n_samples, rng)

    samples = []
    for i in range(n_samples):
        params = {}
        for record in tunable:
            key = parameter_key(record)
            raw = discrete_columns[key][i] if key in discrete_columns else continuous_columns[key][i]
            params[key] = coerce_sample_value(record, float(raw))
        samples.append({"params": params})
    return samples

