import json
from pathlib import Path


def json_safe(value):
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def read_jsonl(path):
    records = []
    with open(path, "r") as file:
        for line in file:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def append_jsonl(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as file:
        file.write(json.dumps(json_safe(record), ensure_ascii=False, separators=(",", ":")) + "\n")


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as file:
        for record in records:
            file.write(json.dumps(json_safe(record), ensure_ascii=False, separators=(",", ":")) + "\n")
