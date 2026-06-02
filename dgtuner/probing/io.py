import json
from pathlib import Path


def read_jsonl(path):
    records = []
    with open(path, "r") as file:
        for line in file:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def split_sql_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as file:
        content = file.read()
    return [statement.strip() for statement in content.split(";") if statement.strip()]


def write_sql_file(path, statements):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        for statement in statements:
            file.write(statement.rstrip(";") + ";\n")
