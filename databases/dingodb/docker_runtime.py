#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path

from databases.dingodb.controller import load_simple_yaml


DEFAULT_CONTAINERS = [
    "coordinator1",
    "coordinator2",
    "coordinator3",
    "store1",
    "store2",
    "store3",
    "index1",
    "index2",
    "index3",
    "executor",
    "proxy",
]


def run(args, **kwargs):
    return subprocess.run(args, text=True, **kwargs)


def project_root():
    return Path(__file__).resolve().parents[2]


def load_runtime(path):
    return load_simple_yaml(path)


def docker_runtime_config(runtime):
    return (runtime.get("docker_runtime") or {})


def compose_file(runtime, runtime_path):
    configured = docker_runtime_config(runtime).get("compose_file", "docker-compose.yml")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(runtime_path).resolve().parent / path
    return path


def detect_host_ip():
    commands = [
        ["hostname", "-I"],
        ["ip", "-4", "addr", "show"],
    ]
    for command in commands:
        result = run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        if result.returncode != 0:
            continue
        for token in result.stdout.replace("/", " ").split():
            if token.startswith(("127.", "172.17.", "172.18.")):
                continue
            parts = token.split(".")
            if len(parts) == 4 and all(part.isdigit() for part in parts):
                return token
    raise RuntimeError("Cannot detect host IP; set docker_runtime.host_ip in runtime.yaml.")


def host_ip(runtime):
    configured = docker_runtime_config(runtime).get("host_ip", "auto")
    return detect_host_ip() if configured == "auto" else str(configured)


def compose_command(runtime, runtime_path, action):
    return [
        "docker-compose",
        "-f",
        str(compose_file(runtime, runtime_path)),
        action,
    ]


def compose_env(runtime):
    env = os.environ.copy()
    env["DINGO_HOST_IP"] = host_ip(runtime)
    return env


def container_names(runtime):
    return list(docker_runtime_config(runtime).get("containers") or DEFAULT_CONTAINERS)


def workload_client(runtime):
    return runtime.get("workload_client") or {}


def mysql_check_args(runtime):
    client = workload_client(runtime)
    image = client.get("image", "mysql:5.7")
    network = client.get("network", "host")
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        str(network),
        str(image),
        "mysql",
        "-h",
        str(client.get("host", "127.0.0.1")),
        "-P",
        str(client.get("port", 3307)),
        "-u",
        str(client.get("user", "root")),
        f"-p{client.get('password', '123123')}",
        "-e",
        "show databases;",
    ]


def is_running(container):
    result = run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def start(runtime, runtime_path):
    command = compose_command(runtime, runtime_path, "up") + ["-d"]
    result = run(command, cwd=compose_file(runtime, runtime_path).parent, env=compose_env(runtime), check=False)
    return result.returncode


def stop(runtime, runtime_path):
    command = compose_command(runtime, runtime_path, "stop")
    result = run(command, cwd=compose_file(runtime, runtime_path).parent, env=compose_env(runtime), check=False)
    return result.returncode


def check(runtime):
    if not all(is_running(container) for container in container_names(runtime)):
        print("not ok")
        return 1
    result = run(mysql_check_args(runtime), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode == 0:
        print("ok")
        return 0
    print("not ok")
    return 1


def stop_check(runtime):
    if any(is_running(container) for container in container_names(runtime)):
        print("not ok")
        return 1
    print("ok")
    return 0


def clear_log(runtime):
    for container in container_names(runtime):
        result = run(
            ["docker", "inspect", "-f", "{{.LogPath}}", container],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        log_path = result.stdout.strip()
        if result.returncode == 0 and log_path:
            run(["truncate", "-s", "0", log_path], check=False)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Manage the local Docker DingoDB runtime.")
    parser.add_argument("action", choices=["start", "stop", "check", "stop-check", "clear-log", "host-ip"])
    parser.add_argument("--runtime", default=str(Path(__file__).resolve().parent / "runtime.yaml"))
    args = parser.parse_args()

    runtime_path = Path(args.runtime)
    runtime = load_runtime(runtime_path)
    if args.action == "start":
        return start(runtime, runtime_path)
    if args.action == "stop":
        return stop(runtime, runtime_path)
    if args.action == "check":
        return check(runtime)
    if args.action == "stop-check":
        return stop_check(runtime)
    if args.action == "clear-log":
        return clear_log(runtime)
    if args.action == "host-ip":
        print(host_ip(runtime))
        return 0
    raise ValueError(args.action)


if __name__ == "__main__":
    sys.exit(main())
