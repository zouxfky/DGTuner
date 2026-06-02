def normalize_keep(value):
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) else 0
    if isinstance(value, str):
        return 0 if value.strip().lower() in {"0", "false", "no", "remove"} else 1
    return 1


def normalize_response(data):
    items = data.get("parameters", [])
    if isinstance(items, dict):
        items = [{"id": key, **value} for key, value in items.items()]
    result = {}
    for item in items:
        param_id = item.get("id")
        if not param_id:
            continue
        result[param_id] = {
            "keep": normalize_keep(item.get("keep", 1)),
            "reason": item.get("reason", ""),
        }
    return result
