from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def database_dir(database):
    return PROJECT_ROOT / "databases" / database


def experiment_dir(database):
    return PROJECT_ROOT / "experiments" / database


def database_knowledge_paths(database):
    knowledge_dir = database_dir(database) / "knowledge"
    return knowledge_dir / "parameters.jsonl", knowledge_dir / "context.md"


def default_workload_path(database):
    return database_dir(database) / "workloads" / "ann_normal.sql"


def llm_pruning_path(database):
    return experiment_dir(database) / "llm_pruning.jsonl"


def probing_path(database):
    return experiment_dir(database) / "probing.jsonl"


def reduced_workload_path(database):
    return experiment_dir(database) / "reduced_workload.sql"


def bo_path(database):
    return experiment_dir(database) / "bo.jsonl"
