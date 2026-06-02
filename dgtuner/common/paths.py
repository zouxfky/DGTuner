from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def database_dir(database):
    return PROJECT_ROOT / "databases" / database


def experiment_dir(database):
    return PROJECT_ROOT / "experiments" / database


def dingodb_run_paths():
    from dgtuner.run_config import resolve_run_config

    return resolve_run_config()


def database_knowledge_paths(database):
    knowledge_dir = database_dir(database) / "knowledge"
    return knowledge_dir / "parameters.jsonl"


def default_workload_path(database):
    if database == "dingodb":
        return dingodb_run_paths()["workload_file"]
    return database_dir(database) / "workload.sql"


def llm_pruning_path(database):
    if database == "dingodb":
        return dingodb_run_paths()["llm_pruning"]
    return experiment_dir(database) / "llm_pruning.jsonl"


def probing_path(database):
    if database == "dingodb":
        return dingodb_run_paths()["probing"]
    return experiment_dir(database) / "probing.jsonl"


def reduced_workload_path(database):
    if database == "dingodb":
        return dingodb_run_paths()["reduced_workload"]
    return experiment_dir(database) / "reduced_workload.sql"


def bo_path(database):
    if database == "dingodb":
        return dingodb_run_paths()["bo"]
    return experiment_dir(database) / "bo.jsonl"
