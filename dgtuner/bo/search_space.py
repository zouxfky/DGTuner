def load_probing_artifacts(records):
    summary = next((record for record in records if record.get("record_type") == "summary"), None)
    if summary is None:
        raise ValueError("probing output does not contain a summary record")

    parameter_decisions = [
        record
        for record in records
        if record.get("record_type") == "parameter_decision" and int(record.get("keep", 0)) == 1
    ]
    if not parameter_decisions:
        raise ValueError("probing output has no kept parameters")

    return summary, parameter_decisions


def bounds_from_parameter_decisions(parameter_decisions):
    pbounds = {}
    for decision in parameter_decisions:
        value_range = decision.get("narrowed_range") or {}
        if "min" not in value_range or "max" not in value_range:
            continue
        low = float(value_range["min"])
        high = float(value_range["max"])
        if high < low:
            low, high = high, low
        if high == low:
            high = low + 1e-9
        key = decision.get("id") or decision["name"]
        pbounds[key] = (low, high)
    if not pbounds:
        raise ValueError("kept probing parameters do not contain numeric narrowed ranges")
    return pbounds
