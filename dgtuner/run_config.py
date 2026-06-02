from pathlib import Path

from dgtuner.common.paths import PROJECT_ROOT


DEFAULT_RUN_CONFIG = PROJECT_ROOT / "configs" / "runs" / "dingodb_tpch.yaml"


def load_yaml(path):
    path = Path(path)
    try:
        import yaml

        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
    except ModuleNotFoundError:
        config = {}
        with path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                config[key.strip()] = value.strip().strip('"').strip("'")
        return config


def scale_to_dirname(scale):
    return f"sf{str(scale).replace('.', '_')}"


def project_path(value):
    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_run_config(config_path=DEFAULT_RUN_CONFIG):
    config_path = project_path(config_path or DEFAULT_RUN_CONFIG).resolve()
    config = load_yaml(config_path)
    database = str(config["database"])
    workload = str(config["workload"])
    scale = str(config.get("scale_factor", "0.01"))

    database_root = PROJECT_ROOT / "databases" / database
    workload_root = PROJECT_ROOT / "workload" / workload
    result_root = database_root / "results" / workload

    return {
        "config": config_path,
        "database": database,
        "workload": workload,
        "scale_factor": scale,
        "database_runtime": project_path(config.get("database_runtime", database_root / "runtime.yaml")),
        "database_root": database_root,
        "workload_root": workload_root,
        "parameters": database_root / "knowledge" / "parameters.jsonl",
        "context": workload_root / "context.md",
        "workload_file": workload_root / "all.sql",
        "queries_dir": workload_root / "queries",
        "schema": workload_root / "schema" / f"{database}.sql",
        "data_dir": workload_root / "data" / scale_to_dirname(scale),
        "prepare_script": workload_root / f"prepare_{database}.py",
        "result_root": result_root,
        "stage1_dir": result_root / "1",
        "stage2_dir": result_root / "2",
        "stage3_dir": result_root / "3",
        "llm_pruning": result_root / "1" / "llm_pruning.jsonl",
        "probing": result_root / "2" / "probing.jsonl",
        "reduced_workload": result_root / "2" / "reduced_workload.sql",
        "bo": result_root / "3" / "bo.jsonl",
    }
