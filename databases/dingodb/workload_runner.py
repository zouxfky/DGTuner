import os
import signal
import subprocess
import time
from collections import defaultdict
from multiprocessing import Pool

from dgtuner.common.paths import PROJECT_ROOT

OUTPUT_LOG = str(PROJECT_ROOT / "logfile" / "output.log")
PARALLEL_LOG = str(PROJECT_ROOT / "logfile" / "parallel_joblog.log")

DEFAULT_TIMEOUT_SECONDS = 1800
_SQL_CLIENT = None
_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS


def configure_workload_client(sql_client, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    global _SQL_CLIENT, _TIMEOUT_SECONDS
    _SQL_CLIENT = sql_client
    _TIMEOUT_SECONDS = timeout_seconds


def _require_sql_client():
    if _SQL_CLIENT is None:
        raise ValueError("DingoDB workload sql_client is not configured")
    protocol = _SQL_CLIENT.get("protocol", "mysql")
    if protocol != "mysql":
        raise ValueError(f"Unsupported DingoDB SQL client protocol: {protocol}")
    return _SQL_CLIENT


def _mysql_args(sql):
    client = _require_sql_client()
    if client.get("mode") == "docker":
        image = str(client.get("image", "mysql:5.7"))
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            str(client.get("network", "host")),
            image,
            "mysql",
            "-h",
            str(client["host"]),
            "-P",
            str(client["port"]),
            "-u",
            str(client["user"]),
            f"-p{client['password']}",
            "-e",
            sql,
        ]
    return [
        str(client.get("binary", "mysql")),
        "-h",
        str(client["host"]),
        "-P",
        str(client["port"]),
        "-u",
        str(client["user"]),
        f"-p{client['password']}",
        "-e",
        sql,
    ]


def _mysql_command(sql, quote='"'):
    args = _mysql_args(sql)
    if args[0] == "docker":
        return subprocess.list2cmdline(args)
    executable, host_flag, host, port_flag, port, user_flag, user, password_arg, execute_flag, statement = args
    return (
        f"{executable} {host_flag} {host} {port_flag} {port} {user_flag} {user} "
        f"{password_arg} {execute_flag} {quote}{statement}{quote}"
    )


def _mysql_source_args(filepath):
    client = _require_sql_client()
    if client.get("mode") == "docker":
        image = str(client.get("image", "mysql:5.7"))
        mount_dir = os.path.dirname(os.path.abspath(filepath))
        mount_file = os.path.basename(filepath)
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            str(client.get("network", "host")),
            "-v",
            f"{mount_dir}:/workload:ro",
            image,
            "mysql",
            "-h",
            str(client["host"]),
            "-P",
            str(client["port"]),
            "-u",
            str(client["user"]),
            f"-p{client['password']}",
            "-e",
            f"source /workload/{mount_file}",
        ]
    return _mysql_args(f"source {filepath}")


def startTest(
    db_controller,
    sqlFilePath,
    isParallel=False,
    parallel=4,
    start=True,
    close=True,
    jobLog=PARALLEL_LOG,
    isLog=False,
    logPath=OUTPUT_LOG,
):
    from databases.dingodb.controller import isClosed, isStarted

    db_controller.clear_node_log()
    if start:
        db_controller.start()
        print(isStarted(db_controller))
    start_time = time.time()
    print("开始执行命令，当前时间为 {}".format(start_time))
    if isParallel:
        client = _require_sql_client()
        binary = str(client.get("binary", "mysql"))
        sqlCommand = (
            'cat {sqlFilePath} | parallel -j {parallel} -d "\\n" --joblog {jobLog} '
            '"{binary} -h {host} -P {port} -u {user} -p{password} -e {{}}" >> {logPath} 2>&1'
        ).format(
            sqlFilePath=sqlFilePath,
            parallel=parallel,
            jobLog=jobLog,
            binary=binary,
            host=client["host"],
            port=client["port"],
            user=client["user"],
            password=client["password"],
            logPath=logPath,
        )
        print(sqlCommand)
        status_code = os.system(sqlCommand)
    else:
        result = subprocess.run(_mysql_source_args(sqlFilePath), check=False)
        status_code = result.returncode
    end_time = time.time()
    print("执行命令结束，当前时间为 {}".format(end_time))
    execution_time = end_time - start_time
    print("执行时间为: {} 秒,执行状态为: {} ".format(execution_time, status_code))
    if close:
        db_controller.stop()
        print(isClosed(db_controller))
    return status_code, execution_time


def detect_encoding(file_path):
    import chardet

    with open(file_path, "rb") as f:
        result = chardet.detect(f.read())
    return result["encoding"]


def read_and_print_sql(sql_file_path):
    encoding = detect_encoding(sql_file_path)
    print(f"Detected encoding: {encoding}")

    with open(sql_file_path, "r", encoding=encoding, errors="ignore") as f:
        sql_data = f.read().split(";")
    return [sql.strip() for sql in sql_data if sql.strip()]


def execute_sql(sql):
    try:
        start_time = time.time()
        command = _mysql_command(sql)
        subprocess.run(command, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Executed: {sql}, Time taken: {execution_time:.4f} seconds")
    except subprocess.CalledProcessError as e:
        print(f"Error executing {sql}: {e}")


def parallel_execute_sql(sql_statements, thread_count):
    start_time = time.time()
    with Pool(thread_count) as pool:
        pool.map(execute_sql, sql_statements)
    end_time = time.time()
    total_time = end_time - start_time
    print(f"Total execution time: {total_time:.4f} seconds")


def handler(signum, frame):
    raise TimeoutError("Execution timed out")


def execute_sqlfile(filepath):
    try:
        start_time = time.time()
        command = subprocess.list2cmdline(_mysql_source_args(filepath))

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(_TIMEOUT_SECONDS)
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        signal.alarm(0)

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Executed: {filepath}, Time taken: {execution_time:.4f} seconds")
        return execution_time
    except subprocess.CalledProcessError as e:
        print(f"Error executing {filepath}: {e}\nError output: {e.stderr.decode()}")
        return 999
    except TimeoutError:
        print(f"Execution of {filepath} timed out.")
        return _TIMEOUT_SECONDS


def parallel_execute_sqlfile(db_controller, file_path, thread_count):
    from databases.dingodb.controller import isClosed, isStarted

    db_controller.clear_node_log()
    db_controller.start()
    print(isStarted(db_controller))
    start_time = time.time()
    file_paths = [file_path] * thread_count
    with Pool(thread_count) as pool:
        results = pool.map(execute_sqlfile, file_paths)

    end_time = time.time()
    total_time = end_time - start_time
    print(f"Total execution time: {total_time:.4f} seconds")
    if 999 in results:
        print("One or more SQL executions failed.")
        return total_time
    return total_time


def execute_sqlfile_withinfo(sql_statements):
    try:
        execution_info = []
        totalstart_time = time.time()
        signal.signal(signal.SIGALRM, handler)
        signal.alarm(_TIMEOUT_SECONDS)
        for index, sql in enumerate(sql_statements):
            start_time = time.time()
            if "'" in sql:
                command = _mysql_command(sql)
            else:
                command = _mysql_command(sql, quote="'")
            result = subprocess.run(command, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            end_time = time.time()
            execution_time = end_time - start_time
            execution_info.append({"status_code": int(result.returncode), "execution_time": float(execution_time), "sql": index + 1})
        signal.alarm(0)
        total_end_time = time.time()
        total_execution_time = total_end_time - totalstart_time
        return execution_info
    except subprocess.CalledProcessError:
        return 999
    except TimeoutError:
        return _TIMEOUT_SECONDS


def parallel_execute_sqlfile_withinfo(db_controller, file_path, thread_count):
    from databases.dingodb.controller import isClosed, isStarted

    db_controller.clear_node_log()
    db_controller.start()
    print(isStarted(db_controller))
    start_time = time.time()
    with open(file_path, "r") as file:
        sql_content = file.read()

    sql_statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]
    with Pool(thread_count) as pool:
        results = pool.map(execute_sqlfile_withinfo, [sql_statements] * thread_count)
    end_time = time.time()
    total_time = end_time - start_time
    print(f"Total execution time: {total_time:.4f} seconds")
    if 999 in results:
        print("One or more SQL executions failed.")
        return total_time, summarize_sql_stats([item for item in results if isinstance(item, list)])
    return total_time, summarize_sql_stats(results)


def summarize_sql_stats(result_list):
    sql_stats = defaultdict(lambda: {"times": [], "status": 0})

    for result_batch in result_list:
        for entry in result_batch:
            sql_id = entry["sql"]
            time = entry["execution_time"]
            status = entry["status_code"]

            sql_stats[sql_id]["times"].append(time)
            if status != 0:
                sql_stats[sql_id]["status"] = 1

    summary = []
    for sql_id, data in sorted(sql_stats.items()):
        avg_time = sum(data["times"]) / len(data["times"]) if data["times"] else 0
        summary.append(
            {
                "sql": sql_id,
                "avg_execution_time": avg_time,
                "status": data["status"],
            }
        )

    return summary
