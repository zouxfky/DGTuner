import os
import json

from dgtuner.common.paths import PROJECT_ROOT, database_dir
from databases.dingodb.controller import DBController, load_simple_yaml
from databases.base import DatabaseAdapter
from databases.dingodb.deployer import apply_runtime_config
from databases.dingodb.workload_runner import (
    configure_workload_client,
    parallel_execute_sqlfile,
    parallel_execute_sqlfile_withinfo,
    startTest,
)

OUTPUT_LOG = str(PROJECT_ROOT / "logfile" / "output.log")
PARAMETER_KNOWLEDGE_PATH = str(database_dir("dingodb") / "knowledge" / "parameters.jsonl")
YAML_CONFIG_PATH = str(database_dir("dingodb") / "runtime.yaml")
ROLE_NAMES = ("store", "index", "coordinator")


class DingoDBAdapter(DatabaseAdapter):
    """DingoDB-specific implementation of configuration and workload hooks."""

    def __init__(self, parameter_knowledge_path=PARAMETER_KNOWLEDGE_PATH, runtime_config_path=YAML_CONFIG_PATH):
        self.parameter_knowledge_path = parameter_knowledge_path
        self.parameter_records = self._load_parameter_records(parameter_knowledge_path)
        self.parameter_by_id = {record["id"]: record for record in self.parameter_records}
        self.runtime_config_path = runtime_config_path
        self.runtime_config = self._load_runtime_config(runtime_config_path)
        self.db_controller = DBController(runtime_config_path)
        workload_client = self.runtime_config.get("workload_client") or self.runtime_config.get("sql_client")
        timeout_seconds = workload_client.get(
            "timeout_seconds",
            self.runtime_config.get("workload_timeout_seconds", 1800),
        )
        configure_workload_client(
            workload_client,
            timeout_seconds,
        )

    def _load_runtime_config(self, runtime_config_path):
        config = load_simple_yaml(runtime_config_path)
        if "workload_client" not in config and "sql_client" not in config:
            raise ValueError(f"Missing workload_client in DingoDB runtime config: {runtime_config_path}")
        return config

    def _load_parameter_records(self, parameter_knowledge_path):
        records = []
        with open(parameter_knowledge_path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def get_pbounds(self):
        pbounds = {}
        for record in self.parameter_records:
            value_range = record.get("range") or {}
            if "min" in value_range and "max" in value_range:
                pbounds[record["id"]] = (float(value_range["min"]), float(value_range["max"]))
        return pbounds

    def get_true_values(self, params):
        return {key: self._coerce_value(self._parameter_record(key), value) for key, value in params.items()}

    def get_knob_type(self, knob_name):
        return self._parameter_record(knob_name).get("type")

    def _parameter_record(self, parameter_id):
        if parameter_id in self.parameter_by_id:
            return self.parameter_by_id[parameter_id]
        raise ValueError(f"Parameter '{parameter_id}' not found in DingoDB parameter knowledge.")

    def _coerce_value(self, record, value):
        value_range = record.get("range") or {}
        param_type = str(record.get("type", "")).lower()

        if "choices" in value_range:
            choices = list(value_range["choices"])
            if isinstance(value, str) and value in choices:
                return value
            index = int(round(float(value)))
            index = max(0, min(len(choices) - 1, index))
            return choices[index]

        low = value_range.get("min")
        high = value_range.get("max")
        if low is not None and high is not None:
            value = max(float(low), min(float(high), float(value)))
            step = value_range.get("step")
            if step:
                step = float(step)
                if step > 0:
                    value = float(low) + round((value - float(low)) / step) * step
                    value = max(float(low), min(float(high), value))

        if param_type in {"bool", "boolean"}:
            if isinstance(value, str):
                return value.lower() in {"true", "on", "yes", "1"}
            return bool(round(float(value)))
        if param_type in {"int", "integer"}:
            return int(round(float(value)))
        if param_type == "string":
            return str(int(round(float(value)))) if isinstance(value, (int, float)) else str(value)
        if param_type == "float":
            return round(float(value), 6)
        return value

    def _roles_for_record(self, record):
        default = record.get("default") or {}
        if isinstance(default, dict):
            return [role for role in ROLE_NAMES if role in default]
        return list(ROLE_NAMES)

    def _group_config_params(self, params):
        yaml_params = {role: {} for role in ROLE_NAMES}
        gflags_params = {role: {} for role in ROLE_NAMES}

        for parameter_id, value in self.get_true_values(params).items():
            record = self._parameter_record(parameter_id)
            target = yaml_params if record.get("format") == "yaml" else gflags_params
            for role in self._roles_for_record(record):
                target[role][parameter_id] = value

        return yaml_params, gflags_params

    def normalize_logged_knob_name(self, knob_name):
        for prefix in ("smart.", "server.", "store."):
            if knob_name.startswith(prefix):
                return knob_name[len(prefix):]
        return knob_name

    def apply_config(self, params):
        yaml_params, gflags_params = self._group_config_params(params)
        apply_runtime_config(self.runtime_config, yaml_params, gflags_params, self.get_true_values(params))

    def clear_output_log(self):
        if os.path.exists(OUTPUT_LOG):
            os.remove(OUTPUT_LOG)

    def run_workload(self, workload_path, concurrency, mode=1):
        if mode == 1:
            return 0, parallel_execute_sqlfile(self.db_controller, workload_path, concurrency)
        if mode == 2:
            return startTest(self.db_controller, workload_path, True, concurrency)
        raise ValueError(f"Unsupported DingoDB workload mode: {mode}")

    def run_workload_with_query_info(self, workload_path, concurrency):
        return parallel_execute_sqlfile_withinfo(self.db_controller, workload_path, concurrency)
