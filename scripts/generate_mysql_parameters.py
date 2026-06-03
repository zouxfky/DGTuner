#!/usr/bin/env python3
"""Generate MySQL parameter knowledge from official MySQL runtime metadata."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


BOOL_TRUE = {"ON", "TRUE", "1", "YES"}
BOOL_FALSE = {"OFF", "FALSE", "0", "NO"}

EXACT_EXCLUDE = {
    "admin_address",
    "admin_port",
    "auto_generate_certs",
    "basedir",
    "bind_address",
    "hostname",
    "license",
    "build_id",
    "character_set_system",
    "have_symlink",
    "innodb_buffer_pool_filename",
    "innodb_directories",
    "innodb_redo_log_archive_dirs",
    "innodb_tmpdir",
    "innodb_version",
    "named_pipe",
    "pid_file",
    "plugin_dir",
    "port",
    "protocol_version",
    "relay_log_basename",
    "relay_log_index",
    "relay_log",
    "report_host",
    "report_password",
    "report_port",
    "report_user",
    "secure_file_priv",
    "server_id",
    "server_id_bits",
    "server_uuid",
    "shared_memory",
    "shared_memory_base_name",
    "socket",
    "system_time_zone",
    "tmpdir",
    "version",
    "version_comment",
    "version_compile_machine",
    "version_compile_os",
    "version_compile_zlib",
}

PREFIX_EXCLUDE = (
    "keyring_",
    "ndb_",
    "rpl_semi_sync_",
)

SUBSTRING_EXCLUDE = (
    "address",
    "certificate",
    "component",
    "credential",
    "endpoint",
    "fips",
    "private_key",
    "public_key",
    "rsa",
    "source_ssl",
    "source_tls",
    "x509",
)

SUFFIX_EXCLUDE = (
    "_dir",
    "_dirs",
    "_directory",
    "_filename",
    "_path",
    "_port",
    "_socket",
    "_tmpdir",
)

PATH_LIKE_FILE_PARAMS = {
    "core_file",
    "general_log_file",
    "log_bin_basename",
    "log_bin_index",
    "log_error",
    "log_error_services",
    "log_error_suppression_list",
    "relay_log_info_file",
    "slow_query_log_file",
}

ENUM_CHOICES = {
    "binlog_checksum": ["CRC32", "NONE"],
    "binlog_error_action": ["ABORT_SERVER", "IGNORE_ERROR"],
    "binlog_format": ["ROW", "STATEMENT", "MIXED"],
    "binlog_row_image": ["FULL", "MINIMAL", "NOBLOB"],
    "binlog_row_metadata": ["MINIMAL", "FULL"],
    "binlog_transaction_dependency_tracking": ["COMMIT_ORDER", "WRITESET", "WRITESET_SESSION"],
    "completion_type": ["NO_CHAIN", "CHAIN", "RELEASE"],
    "concurrent_insert": ["NEVER", "AUTO", "ALWAYS"],
    "default_storage_engine": ["InnoDB", "MyISAM", "MEMORY", "CSV", "ARCHIVE"],
    "default_tmp_storage_engine": ["InnoDB", "MyISAM", "MEMORY"],
    "explain_format": ["TRADITIONAL", "JSON", "TREE"],
    "innodb_change_buffering": ["none", "inserts", "deletes", "changes", "purges", "all"],
    "innodb_checksum_algorithm": ["crc32", "strict_crc32", "innodb", "strict_innodb", "none", "strict_none"],
    "innodb_default_row_format": ["dynamic", "compact", "redundant"],
    "innodb_flush_method": ["fsync", "O_DSYNC", "littlesync", "nosync", "O_DIRECT", "O_DIRECT_NO_FSYNC"],
    "innodb_stats_method": ["nulls_equal", "nulls_unequal", "nulls_ignored"],
    "internal_tmp_mem_storage_engine": ["TempTable", "MEMORY"],
    "log_output": ["FILE", "TABLE", "NONE"],
    "log_timestamps": ["UTC", "SYSTEM"],
    "master_info_repository": ["TABLE", "FILE"],
    "myisam_stats_method": ["nulls_equal", "nulls_unequal", "nulls_ignored"],
    "relay_log_info_repository": ["TABLE", "FILE"],
    "replica_exec_mode": ["STRICT", "IDEMPOTENT"],
    "slave_exec_mode": ["STRICT", "IDEMPOTENT"],
    "terminology_use_previous": ["NONE", "BEFORE_8_0_26"],
    "thread_handling": ["one-thread-per-connection", "no-threads", "loaded-dynamically"],
    "transaction_isolation": ["READ-UNCOMMITTED", "READ-COMMITTED", "REPEATABLE-READ", "SERIALIZABLE"],
    "transaction_write_set_extraction": ["OFF", "MURMUR32", "XXHASH64"],
}

RANGE_OVERRIDES = {
    "mysqlx_zstd_default_compression_level": {"min": 1, "max": 22, "step": 1},
    "mysqlx_zstd_max_client_compression_level": {"min": 1, "max": 22, "step": 1},
}


def parse_tsv(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text().splitlines():
        rows.append(line.split("\t"))
    return rows


def should_exclude(name: str) -> bool:
    if name in EXACT_EXCLUDE or name in PATH_LIKE_FILE_PARAMS:
        return True
    if name.startswith(PREFIX_EXCLUDE):
        return True
    if name.endswith(SUFFIX_EXCLUDE):
        return True
    if any(part in name for part in SUBSTRING_EXCLUDE):
        return True
    if re.search(r"(^|_)ssl($|_)", name):
        return True
    if re.search(r"(^|_)tls($|_)", name):
        return True
    return False


def parse_value(value: str, min_value: str | None = None, max_value: str | None = None) -> tuple[str, Any]:
    upper = value.upper()
    if upper in BOOL_TRUE | BOOL_FALSE and min_value == "0" and max_value == "0":
        return "bool", upper in BOOL_TRUE
    if re.fullmatch(r"[-+]?\d+", value):
        return "int", int(value)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", value):
        return "float", float(value)
    return "string", value


def official_range(name: str, value_type: str, default: Any, min_value: str | None, max_value: str | None) -> tuple[dict[str, Any], str]:
    if value_type == "bool":
        return {"choices": [False, True]}, "official_boolean_domain"
    if name in RANGE_OVERRIDES:
        return RANGE_OVERRIDES[name], "mysql_documented_domain_override"
    if value_type in {"int", "float"}:
        if min_value not in {None, "", "0"} or max_value not in {None, "", "0"}:
            min_parsed = float(min_value) if value_type == "float" else int(min_value or 0)
            max_parsed = float(max_value) if value_type == "float" else int(max_value or 0)
            if min_parsed > max_parsed:
                return inferred_numeric_range(value_type, default), "inferred_numeric_from_invalid_official_bounds"
            if value_type == "int":
                return {"min": min_parsed, "max": max_parsed, "step": numeric_step(default, min_parsed, max_parsed)}, "official_mysql_variables_info"
            return {"min": min_parsed, "max": max_parsed}, "official_mysql_variables_info"
        return inferred_numeric_range(value_type, default), "inferred_numeric_from_official_default"
    if name in ENUM_CHOICES:
        choices = ENUM_CHOICES[name]
        if isinstance(default, str) and default not in choices and default != "":
            choices = [default, *choices]
        return {"choices": choices}, "official_mysql_enum_choices"
    if default == "":
        return {"choices": [""]}, "official_default_single_choice"
    return {"choices": [default]}, "official_default_single_choice"


def numeric_step(default: Any, min_value: int, max_value: int) -> int:
    width = max_value - min_value
    if width <= 1:
        return 1
    if isinstance(default, int) and default > 0:
        magnitude = 10 ** max(0, len(str(abs(default))) - 2)
        return max(1, magnitude)
    return max(1, int(math.ceil(width / 100)))


def inferred_numeric_range(value_type: str, default: Any) -> dict[str, Any]:
    if value_type == "float":
        base = abs(default) if default else 1.0
        return {"min": 0.0, "max": round(base * 10, 6)}
    default_int = int(default)
    if default_int <= 0:
        return {"min": 0, "max": 1024, "step": 32}
    return {"min": 0, "max": max(default_int * 4, default_int + 1), "step": numeric_step(default_int, 0, max(default_int * 4, default_int + 1))}


def detect_dynamic(name: str, container: str) -> bool | None:
    sql = f"SET GLOBAL `{name}` = @@GLOBAL.`{name}`"
    cmd = ["docker", "exec", container, "mysql", "-uroot", "-N", "-B", "-e", sql]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.returncode == 0:
        return True
    return False


def load_dynamic_cache(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    return {k: bool(v) for k, v in json.loads(path.read_text()).items()}


def save_dynamic_cache(path: Path, data: dict[str, bool]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--global-variables", default="/tmp/mysql_global_variables.tsv")
    parser.add_argument("--variables-info", default="/tmp/mysql_variables_info.tsv")
    parser.add_argument("--version-file", default="/tmp/mysql_mysqld_version.txt")
    parser.add_argument("--output", default="databases/mysql/knowledge/parameters.jsonl")
    parser.add_argument("--dynamic-cache", default="/tmp/mysql_dynamic_cache.json")
    parser.add_argument("--container", default="mysql-param-scan")
    parser.add_argument("--probe-dynamic", action="store_true")
    args = parser.parse_args()

    global_rows = parse_tsv(Path(args.global_variables))
    info_rows = parse_tsv(Path(args.variables_info))
    version = Path(args.version_file).read_text().strip()
    info = {row[0].lower(): (row[1] if len(row) > 1 else None, row[2] if len(row) > 2 else None) for row in info_rows}

    candidates: list[tuple[str, str, str | None, str | None]] = []
    for row in global_rows:
        if len(row) < 2:
            continue
        name = row[0].lower()
        value = row[1]
        if should_exclude(name):
            continue
        min_value, max_value = info.get(name, (None, None))
        candidates.append((name, value, min_value, max_value))

    dynamic_cache = load_dynamic_cache(Path(args.dynamic_cache))
    if args.probe_dynamic:
        for name, _value, _min_value, _max_value in candidates:
            if name not in dynamic_cache:
                dynamic = detect_dynamic(name, args.container)
                if dynamic is not None:
                    dynamic_cache[name] = dynamic
        save_dynamic_cache(Path(args.dynamic_cache), dynamic_cache)

    source = "official_mysql_8_0_46_docker_image"
    rows: list[dict[str, Any]] = []
    for name, value, min_value, max_value in candidates:
        value_type, default = parse_value(value, min_value, max_value)
        range_value, range_source = official_range(name, value_type, default, min_value, max_value)
        dynamic = dynamic_cache.get(name)
        rows.append(
            {
                "id": name,
                "name": name,
                "format": "variable",
                "scope": "global",
                "dynamic": dynamic,
                "requires_restart": None if dynamic is None else not dynamic,
                "default": {"mysql": default},
                "type": value_type,
                "range": range_value,
                "range_source": range_source,
                "default_source": source,
                "source_version": version,
                "description": (
                    f"MySQL server variable {name}. Default is from the official MySQL 8.0.46 Docker image. "
                    f"Range source: {range_source}. Deployment, path, port, socket, credential, certificate, "
                    "and topology endpoint variables are intentionally excluded."
                ),
            }
        )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for row in sorted(rows, key=lambda item: item["id"]):
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"generated {len(rows)} parameters -> {out}")


if __name__ == "__main__":
    main()
