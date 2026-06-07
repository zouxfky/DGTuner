import json
import os
from pathlib import Path

from databases.base import DatabaseAdapter
from databases.mysql.controller import DEFAULT_RUNTIME_PATH, MySQLController
from databases.mysql.workload_runner import (
    configure_query_timeouts,
    configure_workload_client,
    parallel_execute_sqlfile,
    parallel_execute_sqlfile_withinfo,
)
from dgtuner.common.paths import PROJECT_ROOT, database_dir


OUTPUT_LOG = str(PROJECT_ROOT / "logfile" / "output.log")
PARAMETER_KNOWLEDGE_PATH = str(database_dir("mysql") / "knowledge" / "parameters.jsonl")


class MySQLAdapter(DatabaseAdapter):
    """MySQL implementation for DGTuner Stage 2 and Stage 3."""

    def __init__(self, parameter_knowledge_path=PARAMETER_KNOWLEDGE_PATH, runtime_config_path=DEFAULT_RUNTIME_PATH):
        self.parameter_knowledge_path = str(parameter_knowledge_path)
        self.parameter_records = self._load_parameter_records(self.parameter_knowledge_path)
        self.parameter_by_id = {record["id"]: record for record in self.parameter_records}
        self.runtime_config_path = str(runtime_config_path)
        self.db_controller = MySQLController(self.runtime_config_path)
        self.runtime_config = self.db_controller.runtime
        workload_client = self.runtime_config.get("workload_client") or self.runtime_config.get("sql_client")
        if not workload_client:
            raise ValueError(f"Missing workload_client in MySQL runtime config: {self.runtime_config_path}")
        configure_workload_client(
            workload_client,
            int(workload_client.get("timeout_seconds", self.runtime_config.get("workload_timeout_seconds", 1800))),
        )
        self._restart_required = False

    def _load_parameter_records(self, path):
        records = []
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def _parameter_record(self, parameter_id):
        if parameter_id in self.parameter_by_id:
            return self.parameter_by_id[parameter_id]
        raise ValueError(f"Parameter '{parameter_id}' not found in MySQL parameter knowledge.")

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

    def _coerce_value(self, record, value):
        value_range = record.get("range") or {}
        param_type = str(record.get("type", "")).lower()

        if "choices" in value_range:
            choices = list(value_range["choices"])
            if isinstance(value, str) and value in choices:
                return value
            if param_type in {"bool", "boolean"}:
                if isinstance(value, str):
                    return value.lower() in {"true", "on", "yes", "1"}
                if isinstance(value, bool):
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
        if param_type == "float":
            return round(float(value), 6)
        if param_type == "string":
            return str(value)
        return value

    def _mysql_literal(self, value):
        if isinstance(value, bool):
            return "ON" if value else "OFF"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    def _cnf_value(self, value):
        if isinstance(value, bool):
            return "ON" if value else "OFF"
        return str(value)

    def _default_value(self, record):
        default = record.get("default") or {}
        if isinstance(default, dict) and "mysql" in default:
            return default["mysql"]
        return None

    def _build_restart_config(self, restart_params):
        lines = [
            "# Generated by DGTuner. Do not edit manually while a tuning run is active.",
            "[mysqld]",
        ]
        for name, value in sorted(restart_params.items()):
            lines.append(f"{name}={self._cnf_value(value)}")
        return "\n".join(lines) + "\n"

    def _connect_admin(self):
        try:
            import pymysql
        except ModuleNotFoundError:
            return None

        client = self.db_controller.client
        return pymysql.connect(
            host=str(client.get("host", "127.0.0.1")),
            port=int(client.get("port", 3306)),
            user=str(client.get("user", "root")),
            password=str(client.get("password", "")),
            autocommit=True,
            charset="utf8mb4",
            connect_timeout=10,
            read_timeout=int(client.get("timeout_seconds", self.runtime_config.get("workload_timeout_seconds", 1800))),
            write_timeout=int(client.get("timeout_seconds", self.runtime_config.get("workload_timeout_seconds", 1800))),
        )

    def _apply_dynamic_params(self, dynamic_params):
        failed = {}
        if not dynamic_params:
            return failed

        connection = self._connect_admin()
        if connection is None:
            for name, value in dynamic_params.items():
                sql = f"SET GLOBAL `{name}` = {self._mysql_literal(value)};"
                result = self.db_controller.run_client(sql=sql, stdout=None, stderr=None, check=False)
                if result.returncode != 0:
                    failed[name] = value
            return failed

        try:
            with connection.cursor() as cursor:
                for name, value in dynamic_params.items():
                    sql = f"SET GLOBAL `{name}` = {self._mysql_literal(value)};"
                    try:
                        cursor.execute(sql)
                    except Exception:
                        failed[name] = value
        finally:
            connection.close()
        return failed

    def apply_config(self, params):
        true_values = self.get_true_values(params)
        dynamic_params = {}
        restart_params = {}

        for parameter_id, value in true_values.items():
            record = self._parameter_record(parameter_id)
            if bool(record.get("dynamic")):
                dynamic_params[parameter_id] = value
            else:
                restart_params[parameter_id] = value

        restart_params.update(self._apply_dynamic_params(dynamic_params))

        self._restart_required = bool(restart_params)
        if restart_params:
            self.db_controller.write_container_config(self._build_restart_config(restart_params))

    def restart(self):
        if self._restart_required:
            self._restart_required = False
            return self.db_controller.restart()
        return "", ""

    def set_query_timeouts(self, caps_by_index):
        configure_query_timeouts(caps_by_index)

    def clear_output_log(self):
        if os.path.exists(OUTPUT_LOG):
            os.remove(OUTPUT_LOG)
        self.db_controller.clear_node_log()

    def run_workload(self, workload_path, concurrency, mode=1):
        if mode != 1:
            raise ValueError(f"Unsupported MySQL workload mode: {mode}")
        self.db_controller.start()
        self.db_controller.wait_until_ready()
        return 0, parallel_execute_sqlfile(workload_path, concurrency)

    def run_workload_with_query_info(self, workload_path, concurrency):
        self.db_controller.start()
        self.db_controller.wait_until_ready()
        return parallel_execute_sqlfile_withinfo(workload_path, concurrency)
