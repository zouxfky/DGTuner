import os
import subprocess
import time
from pathlib import Path

from databases.dingodb.controller import load_simple_yaml
from dgtuner.common.paths import database_dir


DEFAULT_RUNTIME_PATH = str(database_dir("mysql") / "runtime.yaml")


def mysql_client_args(client, sql=None, sql_file=None, volume=None, local_infile=False):
    if client.get("mode", "docker") == "docker":
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            str(client.get("network", "host")),
        ]
        if volume:
            command.extend(["-v", str(volume)])
        command.extend([str(client.get("image", "mysql:8.0")), "mysql"])
    else:
        command = [str(client.get("binary", "mysql"))]

    if local_infile:
        command.append("--local-infile=1")
    command.extend([
        "-h",
        str(client.get("host", "127.0.0.1")),
        "-P",
        str(client.get("port", 3306)),
        "-u",
        str(client.get("user", "root")),
    ])
    password = client.get("password")
    if password is not None:
        command.append(f"-p{password}")
    database = client.get("database")
    if database:
        command.append(str(database))
    if sql is not None:
        command.extend(["-e", sql])
    if sql_file is not None:
        command.extend(["-e", f"source {sql_file}"])
    return command


class MySQLController:
    def __init__(self, runtime_config_path=DEFAULT_RUNTIME_PATH):
        self.runtime_config_path = str(runtime_config_path)
        self.runtime = load_simple_yaml(self.runtime_config_path)
        self.client = self.runtime.get("workload_client") or self.runtime.get("sql_client") or {}
        self.lifecycle = self.runtime.get("lifecycle") or {}
        self.container = (self.runtime.get("mysql_runtime") or {}).get("container")
        self.max_retries = int(self.lifecycle.get("max_retries", 120))
        self.max_start_minutes = int(self.lifecycle.get("max_minutes", 5))

    def run_client(self, sql=None, sql_file=None, volume=None, local_infile=False, **kwargs):
        return subprocess.run(
            mysql_client_args(self.client, sql=sql, sql_file=sql_file, volume=volume, local_infile=local_infile),
            text=True,
            **kwargs,
        )

    def _run_command(self, command):
        if not command:
            return "", ""
        result = subprocess.run(command, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout, result.stderr

    def start(self):
        command = self.lifecycle.get("start")
        if command:
            return self._run_command(command)
        if self.container:
            result = subprocess.run(["docker", "start", str(self.container)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return result.stdout, result.stderr
        return "", ""

    def stop(self):
        command = self.lifecycle.get("stop")
        if command:
            return self._run_command(command)
        if self.container and bool(self.lifecycle.get("stop_enabled", False)):
            result = subprocess.run(["docker", "stop", str(self.container)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return result.stdout, result.stderr
        return "", ""

    def restart(self):
        command = self.lifecycle.get("restart")
        if command:
            stdout, stderr = self._run_command(command)
        elif self.container:
            result = subprocess.run(["docker", "restart", str(self.container)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = result.stdout, result.stderr
        else:
            stdout, stderr = "", ""
        self.wait_until_ready()
        return stdout, stderr

    def isStart(self):
        if self.is_ready():
            return "ok\n", ""
        return "not ok\n", ""

    def isClosed(self):
        if self.container:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", str(self.container)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0 or result.stdout.strip() != "true":
                return "ok\n", ""
        return "not ok\n", ""

    def clear_node_log(self):
        command = self.lifecycle.get("clear_log")
        if command:
            return self._run_command(command)
        if self.container:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.LogPath}}", str(self.container)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            log_path = result.stdout.strip()
            if result.returncode == 0 and log_path:
                subprocess.run(["truncate", "-s", "0", log_path], check=False)
        return "", ""

    def is_ready(self):
        result = self.run_client(sql="SELECT 1;", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return result.returncode == 0

    def wait_until_ready(self):
        deadline = time.time() + self.max_start_minutes * 60
        while time.time() < deadline:
            if self.is_ready():
                return True
            time.sleep(1)
        return False

    def write_container_config(self, content):
        mysql_runtime = self.runtime.get("mysql_runtime") or {}
        container = mysql_runtime.get("container")
        config_path = mysql_runtime.get("config_path", "/etc/mysql/conf.d/dgtuner.cnf")
        if not container:
            raise ValueError("mysql_runtime.container is required to write restart-required MySQL config.")
        temp_path = Path("/tmp") / f"dgtuner-mysql-{os.getpid()}.cnf"
        temp_path.write_text(content, encoding="utf-8")
        try:
            subprocess.run(["docker", "cp", str(temp_path), f"{container}:{config_path}"], check=True)
        finally:
            temp_path.unlink(missing_ok=True)
