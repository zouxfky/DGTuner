import json


def parameter_id(record):
    return record.get("id") or record["name"]


def format_default(default):
    if not default:
        return "not specified"
    return ", ".join(f"{key}={value}" for key, value in default.items())


def format_range(value_range):
    if not value_range:
        return "not specified"
    if "choices" in value_range:
        return "choices: " + ", ".join(str(value) for value in value_range["choices"])
    if "min" in value_range and "max" in value_range:
        text = f"{value_range['min']} to {value_range['max']}"
        if value_range.get("step") is not None:
            text += f", step {value_range['step']}"
        return text
    return json.dumps(value_range, ensure_ascii=False, separators=(",", ":"))


def parameter_text(record, index):
    param_id = parameter_id(record)
    description = record.get("description") or f"Configuration parameter {param_id}."
    return (
        f"{index}. Parameter ID: {param_id}\n"
        f"   Description: {description}\n"
        f"   Default: {format_default(record.get('default'))}\n"
        f"   Type: {record.get('type', 'unknown')}\n"
        f"   Range: {format_range(record.get('range'))}"
    )


RETURN_SHAPE = (
    "Return JSON in exactly this shape:\n"
    "{\n"
    '  "parameters": [\n'
    "    {\n"
    '      "id": "same as candidate id",\n'
    '      "keep": 0,\n'
    '      "reason": "short workload-specific reason"\n'
    "    }\n"
    "  ]\n"
    "}\n"
)


def build_prompt(context, parameters, refine=False):
    parameter_notes = "\n\n".join(
        parameter_text(record, index)
        for index, record in enumerate(parameters, 1)
    )
    if refine:
        system = (
            "You are a database configuration tuning assistant. This is a SECOND "
            "round of parameter pruning: every candidate already passed an initial "
            "screen, so none is obviously irrelevant. Re-examine each one and remove "
            "only those you are confident have merely indirect or marginal influence "
            "on this workload. Stay conservative: when unsure, keep. Do not recommend "
            "concrete parameter values. Do not invent parameters. Return valid JSON only."
        )
        user = (
            "Task: re-examine these already-screened parameters and decide whether each "
            "should still be kept for empirical tuning.\n\n"
            "Rules:\n"
            "- Output `keep = 1` if the parameter has a DIRECT effect on this workload's "
            "execution performance, or if you cannot be sure its influence is only "
            "indirect or marginal.\n"
            "- Output `keep = 0` ONLY when, after careful thought, you are confident the "
            "parameter has only indirect, marginal, or situational influence on this "
            "workload.\n"
            "- This is the second round, so the bar may be slightly stricter than the "
            "first, but the conservative principle is unchanged: removing a genuinely "
            "useful parameter is worse than keeping a marginal one. When truly unsure, keep.\n"
            "- Prefer keeping the core classes that directly affect read-path performance: "
            "buffer/cache, memory, parallelism/threads, scan, and optimizer-related knobs.\n\n"
            f"Context:\n{context}\n\n"
            "Candidate parameters:\n"
            f"{parameter_notes}\n\n"
            + RETURN_SHAPE
        )
        return {"system": system, "user": user}

    return {
        "system": (
            "You are a database configuration tuning assistant. "
            "Your task is conservative binary parameter pruning. "
            "Do not recommend concrete parameter values. "
            "Do not invent parameters. "
            "Return valid JSON only."
        ),
        "user": (
            "Task: decide whether each candidate parameter should be kept for empirical tuning.\n\n"
            "Rules:\n"
            "- Output `keep = 1` if the parameter may affect the workload or if the relationship is unclear.\n"
            "- Output `keep = 0` only if the parameter is clearly irrelevant to the workload and objective described in the context.\n"
            "- Do not choose `keep = 0` only because the parameter has no range.\n"
            "- Be conservative: keeping an irrelevant parameter is acceptable; removing a useful parameter is not.\n\n"
            f"Context:\n{context}\n\n"
            "Candidate parameters:\n"
            f"{parameter_notes}\n\n"
            + RETURN_SHAPE
        ),
    }
