import json
import subprocess

from databases.dingodb.config_deployer import (
    update_docker_config_option_dict,
    update_docker_yaml_config_dict,
    update_config_option_dict,
    update_remote_config_option_dict,
    update_remote_yaml_config_dict,
    update_yaml_config_dict,
)
from dgtuner.common.paths import database_dir

PARAMETER_KNOWLEDGE_PATH = str(database_dir("dingodb") / "knowledge" / "parameters.jsonl")
ROLE_NAMES = ("store", "index", "coordinator")


def _load_parameter_records(parameter_knowledge_path):
    records = []
    with open(parameter_knowledge_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _default_params_by_role(parameter_knowledge_path):
    yaml_defaults = {role: {} for role in ROLE_NAMES}
    gflags_defaults = {role: {} for role in ROLE_NAMES}
    for record in _load_parameter_records(parameter_knowledge_path):
        defaults = record.get("default") or {}
        if not isinstance(defaults, dict):
            continue
        target = yaml_defaults if record.get("format") == "yaml" else gflags_defaults
        for role, value in defaults.items():
            if role in target:
                target[role][record["id"]] = value
    return yaml_defaults, gflags_defaults


def send_default_param(default_server_info, parameter_knowledge_path=PARAMETER_KNOWLEDGE_PATH):
    """Deploy the default DingoDB store/index/coordinator configuration."""
    if default_server_info is None:
        raise ValueError("default_server_info is required")

    yaml_defaults, gflags_defaults = _default_params_by_role(parameter_knowledge_path)

    send_param_new(
        yaml_defaults["store"],
        yaml_defaults["index"],
        yaml_defaults["coordinator"],
        gflags_defaults["store"],
        gflags_defaults["index"],
        gflags_defaults["coordinator"],
        default_server_info,
    )


def send_param_new(
    store_yaml_para,
    index_yaml_para,
    coordinator_yaml_para,
    store_config_para,
    index_config_para,
    coordinator_config_para,
    default_server_info,
):
    """Deploy DingoDB role-specific YAML and gflags parameters."""
    if default_server_info is None:
        raise ValueError("default_server_info is required")

    for server in default_server_info:
        print(f"IP: {server['ip']}")
        print(f"User: {server['user']}")
        print(f"Password: {server['password']}")

        if server["type"] == "localhost":
            update_yaml_config_dict(server["storeYamlPath"], store_yaml_para)
            update_yaml_config_dict(server["indexYamlPath"], index_yaml_para)
            update_yaml_config_dict(server["coordinatorYamlPath"], coordinator_yaml_para)
            update_config_option_dict(server["storeConfigPath"], store_config_para)
            update_config_option_dict(server["indexConfigPath"], index_config_para)
            update_config_option_dict(server["coordinatorConfigPath"], coordinator_config_para)
        elif server["type"] == "remote":
            update_remote_yaml_config_dict(
                server["ip"], server["storeYamlPath"], store_yaml_para, server["user"], server["password"], server.get("port", 22)
            )
            update_remote_yaml_config_dict(
                server["ip"], server["indexYamlPath"], index_yaml_para, server["user"], server["password"], server.get("port", 22)
            )
            update_remote_yaml_config_dict(
                server["ip"],
                server["coordinatorYamlPath"],
                coordinator_yaml_para,
                server["user"],
                server["password"],
                server.get("port", 22),
            )
            update_remote_config_option_dict(
                server["ip"], server["storeConfigPath"], store_config_para, server["user"], server["password"], server.get("port", 22)
            )
            update_remote_config_option_dict(
                server["ip"], server["indexConfigPath"], index_config_para, server["user"], server["password"], server.get("port", 22)
            )
            update_remote_config_option_dict(
                server["ip"],
                server["coordinatorConfigPath"],
                coordinator_config_para,
                server["user"],
                server["password"],
                server.get("port", 22),
            )
        else:
            raise ValueError(f"Unsupported server type: {server['type']}")


def runtime_server_info(runtime_config):
    ssh = runtime_config.get("ssh") or {}
    config_apply = runtime_config.get("config_apply") or {}
    yaml_paths = config_apply.get("yaml") or {}
    gflags_paths = config_apply.get("gflags") or {}

    return [{
        "type": "remote" if ssh.get("enabled", True) else "localhost",
        "ip": ssh.get("host", "localhost"),
        "port": int(ssh.get("port", 22)),
        "user": ssh.get("user", ""),
        "password": ssh.get("password", ""),
        "storeYamlPath": yaml_paths.get("store", ""),
        "indexYamlPath": yaml_paths.get("index", ""),
        "coordinatorYamlPath": yaml_paths.get("coordinator", ""),
        "storeConfigPath": gflags_paths.get("store", ""),
        "indexConfigPath": gflags_paths.get("index", ""),
        "coordinatorConfigPath": gflags_paths.get("coordinator", ""),
    }]


def docker_role_targets(config_apply):
    default_targets = {
        "coordinator": [{
            "container": "coordinator1",
            "yaml": "/opt/dingo-store/dist/coordinator1/conf/coordinator.yaml",
            "gflags": "/opt/dingo-store/dist/coordinator1/conf/gflags.conf",
        }, {
            "container": "coordinator2",
            "yaml": "/opt/dingo-store/dist/coordinator1/conf/coordinator.yaml",
            "gflags": "/opt/dingo-store/dist/coordinator1/conf/gflags.conf",
        }, {
            "container": "coordinator3",
            "yaml": "/opt/dingo-store/dist/coordinator1/conf/coordinator.yaml",
            "gflags": "/opt/dingo-store/dist/coordinator1/conf/gflags.conf",
        }],
        "store": [{
            "container": "store1",
            "yaml": "/opt/dingo-store/dist/store1/conf/store.yaml",
            "gflags": "/opt/dingo-store/dist/store1/conf/gflags.conf",
        }, {
            "container": "store2",
            "yaml": "/opt/dingo-store/dist/store1/conf/store.yaml",
            "gflags": "/opt/dingo-store/dist/store1/conf/gflags.conf",
        }, {
            "container": "store3",
            "yaml": "/opt/dingo-store/dist/store1/conf/store.yaml",
            "gflags": "/opt/dingo-store/dist/store1/conf/gflags.conf",
        }],
        "index": [{
            "container": "index1",
            "yaml": "/opt/dingo-store/dist/index1/conf/index.yaml",
            "gflags": "/opt/dingo-store/dist/index1/conf/gflags.conf",
        }, {
            "container": "index2",
            "yaml": "/opt/dingo-store/dist/index1/conf/index.yaml",
            "gflags": "/opt/dingo-store/dist/index1/conf/gflags.conf",
        }, {
            "container": "index3",
            "yaml": "/opt/dingo-store/dist/index1/conf/index.yaml",
            "gflags": "/opt/dingo-store/dist/index1/conf/gflags.conf",
        }],
    }
    return (config_apply.get("docker") or {}).get("roles") or default_targets


def apply_docker_runtime_config(config_apply, yaml_params, gflags_params):
    role_targets = docker_role_targets(config_apply)
    for role in ROLE_NAMES:
        for target in role_targets.get(role, []):
            container = target["container"]
            update_docker_yaml_config_dict(container, target["yaml"], yaml_params[role])
            update_docker_config_option_dict(container, target["gflags"], gflags_params[role])


def apply_runtime_config(runtime_config, yaml_params, gflags_params, flat_params):
    config_apply = runtime_config.get("config_apply") or {}
    method = config_apply.get("method", "direct")
    if method == "direct":
        send_param_new(
            yaml_params["store"],
            yaml_params["index"],
            yaml_params["coordinator"],
            gflags_params["store"],
            gflags_params["index"],
            gflags_params["coordinator"],
            runtime_server_info(runtime_config),
        )
        return

    if method == "docker":
        apply_docker_runtime_config(config_apply, yaml_params, gflags_params)
        return

    if method == "script":
        script = config_apply.get("script")
        if not script:
            raise ValueError("config_apply.method is script, but config_apply.script is empty")
        payload = json.dumps({
            "params": flat_params,
            "yaml": yaml_params,
            "gflags": gflags_params,
        }, ensure_ascii=False)
        subprocess.run([script], input=payload, text=True, check=True)
        return

    raise ValueError(f"Unsupported config_apply method: {method}")
