import os
import re
import signal
import subprocess
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

from databases.mysql.controller import mysql_client_args
from dgtuner.common.paths import PROJECT_ROOT


OUTPUT_LOG = str(PROJECT_ROOT / "logfile" / "output.log")
DEFAULT_TIMEOUT_SECONDS = 1800
QUERY_TIMEOUT_STATUS = 124
_MYSQL_QUERY_TIMEOUT_ERRNO = 3024  # ER_QUERY_TIMEOUT (max_execution_time exceeded)
_SQL_CLIENT = None
_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
_QUERY_TIMEOUTS = {}


def configure_workload_client(sql_client, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    global _SQL_CLIENT, _TIMEOUT_SECONDS
    _SQL_CLIENT = sql_client
    _TIMEOUT_SECONDS = int(timeout_seconds)


def configure_query_timeouts(caps_by_index):
    """Per-query caps in seconds, keyed by 1-based statement index. {} disables."""
    global _QUERY_TIMEOUTS
    _QUERY_TIMEOUTS = {int(k): float(v) for k, v in (caps_by_index or {}).items()}


def _is_query_timeout(error):
    code = error.args[0] if getattr(error, "args", None) else None
    if code == _MYSQL_QUERY_TIMEOUT_ERRNO:
        return True
    text = str(error).lower()
    return "max_execution_time" in text or "maximum statement execution time" in text


def _require_client():
    if _SQL_CLIENT is None:
        raise ValueError("MySQL workload client is not configured")
    return _SQL_CLIENT


def split_sql_file(path):
    content = Path(path).read_text(encoding="utf-8", errors="ignore")
    return [statement.strip() for statement in content.split(";") if statement.strip()]


def _source_args(filepath):
    client = _require_client()
    path = Path(filepath).resolve()
    if client.get("mode", "docker") == "docker":
        return mysql_client_args(
            client,
            sql_file=f"/workload/{path.name}",
            volume=f"{path.parent}:/workload:ro",
        )
    return mysql_client_args(client, sql_file=str(path))


def _source_args_verbose(filepath):
    command = _source_args(filepath)
    try:
        mysql_index = command.index("mysql")
    except ValueError:
        mysql_index = 0
    return command[:mysql_index + 1] + ["-vvv"] + command[mysql_index + 1:]


def _sql_args(sql):
    return mysql_client_args(_require_client(), sql=sql)


def _timeout_handler(_signum, _frame):
    raise TimeoutError("Execution timed out")


def _connect_client():
    try:
        import pymysql
    except ModuleNotFoundError:
        return None

    client = _require_client()
    return pymysql.connect(
        host=str(client.get("host", "127.0.0.1")),
        port=int(client.get("port", 3306)),
        user=str(client.get("user", "root")),
        password=str(client.get("password", "")),
        database=client.get("database"),
        autocommit=True,
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=_TIMEOUT_SECONDS,
        write_timeout=_TIMEOUT_SECONDS,
    )


def execute_sqlfile_with_info_python(filepath):
    sql_statements = split_sql_file(filepath)
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(_TIMEOUT_SECONDS)
    execution_info = []
    connection = None
    try:
        connection = _connect_client()
        if connection is None:
            return None
        with connection.cursor() as cursor:
            for index, sql in enumerate(sql_statements, 1):
                cap = _QUERY_TIMEOUTS.get(index)
                start = time.time()
                try:
                    if cap:
                        cursor.execute("SET SESSION MAX_EXECUTION_TIME=%d" % max(1, int(cap * 1000)))
                    cursor.execute(sql)
                    cursor.fetchall()
                    while cursor.nextset():
                        cursor.fetchall()
                    execution_info.append({
                        "status_code": 0,
                        "execution_time": float(time.time() - start),
                        "sql": index,
                    })
                except Exception as error:
                    if _is_query_timeout(error):
                        # censored at the cap: a real, informative "this config made
                        # this query at least cap-slow" signal, not a hard failure.
                        execution_info.append({
                            "status_code": QUERY_TIMEOUT_STATUS,
                            "execution_time": float(cap) if cap else float(time.time() - start),
                            "sql": index,
                        })
                    else:
                        execution_info.append({
                            "status_code": 1,
                            "execution_time": float(time.time() - start),
                            "sql": index,
                        })
        return execution_info
    except TimeoutError:
        return [{"status_code": 124, "execution_time": float(_TIMEOUT_SECONDS), "sql": 1}]
    finally:
        signal.alarm(0)
        if connection is not None:
            connection.close()


def execute_sqlfile(filepath):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(_TIMEOUT_SECONDS)
    start = time.time()
    try:
        result = subprocess.run(_source_args(filepath), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return {"status_code": int(result.returncode), "execution_time": time.time() - start}
    except TimeoutError:
        return {"status_code": 124, "execution_time": float(_TIMEOUT_SECONDS)}
    finally:
        signal.alarm(0)


def parse_mysql_verbose_timings(output, expected_count):
    pattern = re.compile(r"(?:\d+\s+rows?\s+in\s+set|Empty set|Query OK,.*) \((\d+(?:\.\d+)?) sec\)")
    timings = [float(match.group(1)) for match in pattern.finditer(output or "")]
    if expected_count and len(timings) > expected_count:
        timings = timings[-expected_count:]
    return timings


def execute_sqlfile_with_info(filepath):
    python_result = execute_sqlfile_with_info_python(filepath)
    if python_result is not None:
        return python_result

    sql_statements = split_sql_file(filepath)
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(_TIMEOUT_SECONDS)
    try:
        result = subprocess.run(
            _source_args_verbose(filepath),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        timings = parse_mysql_verbose_timings(result.stdout, len(sql_statements))
        execution_info = []
        for index, _sql in enumerate(sql_statements, 1):
            status = int(result.returncode) if index > len(timings) else 0
            execution_info.append({
                "status_code": status,
                "execution_time": float(timings[index - 1]) if index <= len(timings) else 0.0,
                "sql": index,
            })
        return execution_info
    except TimeoutError:
        return [{"status_code": 124, "execution_time": float(_TIMEOUT_SECONDS), "sql": 1}]
    finally:
        signal.alarm(0)


def execute_statements_with_info(sql_statements):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(_TIMEOUT_SECONDS)
    execution_info = []
    try:
        for index, sql in enumerate(sql_statements, 1):
            start = time.time()
            result = subprocess.run(_sql_args(sql), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            execution_info.append({
                "status_code": int(result.returncode),
                "execution_time": float(time.time() - start),
                "sql": index,
            })
        return execution_info
    except TimeoutError:
        return [{"status_code": 124, "execution_time": float(_TIMEOUT_SECONDS), "sql": index + 1}]
    finally:
        signal.alarm(0)


def summarize_sql_stats(result_list):
    sql_stats = defaultdict(lambda: {"times": [], "status": 0})
    for result_batch in result_list:
        for entry in result_batch:
            sql_id = entry["sql"]
            sql_stats[sql_id]["times"].append(float(entry["execution_time"]))
            if int(entry["status_code"]) != 0:
                sql_stats[sql_id]["status"] = 1

    summary = []
    for sql_id, data in sorted(sql_stats.items()):
        summary.append({
            "sql": sql_id,
            "avg_execution_time": sum(data["times"]) / len(data["times"]) if data["times"] else 0,
            "status": data["status"],
        })
    return summary


def parallel_execute_sqlfile(file_path, thread_count):
    file_paths = [str(file_path)] * int(thread_count)
    with Pool(int(thread_count)) as pool:
        result_batches = pool.map(execute_sqlfile_with_info, file_paths)
    return max(
        (sum(float(item["execution_time"]) for item in batch) for batch in result_batches),
        default=0.0,
    )


def parallel_execute_sqlfile_withinfo(file_path, thread_count):
    with Pool(int(thread_count)) as pool:
        results = pool.map(execute_sqlfile_with_info, [str(file_path)] * int(thread_count))
    total_time = max(
        (sum(float(item["execution_time"]) for item in batch) for batch in results),
        default=0.0,
    )
    return total_time, summarize_sql_stats(results)
