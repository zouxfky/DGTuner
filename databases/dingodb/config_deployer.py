import os

def _new_ssh_client():
    import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return ssh


def _new_yaml_parser():
    from ruamel.yaml import YAML

    return YAML()


def send_yaml_file(hostname, port, username, password, file_path, content):
    ssh = _new_ssh_client()
    try:
        # 连接到Linux服务器
        ssh.connect(hostname=hostname, port=port, username=username, password=password)
        # 在服务器上创建文件并写入字符串内容
        command = f"echo '{content}' > {file_path}"
        stdin, stdout, stderr = ssh.exec_command(command)

        # 检查是否有错误输出
        if stderr.read():
            print("Error:", stderr.read().decode())
        else:
            print("String written to file successfully.")
    except Exception as e:
        print("An error occurred:", str(e))
    finally:
        # 关闭SSH连接
        ssh.close()
def update_yaml_config(file_path, config_key, new_value):
    """
    更新指定yaml文件的指定配置，保留原有格式和注释。

    :param file_path: str, yaml文件的路径。
    :param config_key: str, 要更新的配置键，支持点分键路径，例如 "cluster.name"。
    :param new_value: 要设置的新值。
    :return: None
    """
    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        return

    # 使用ruamel.yaml读取yaml文件内容
    yaml = _new_yaml_parser()
    with open(file_path, 'r') as file:
        config = yaml.load(file)

    # 分割配置键，以支持嵌套键
    keys = config_key.split('.')

    # 逐步深入字典，找到要更新的键
    current_dict = config
    for key in keys[:-1]:
        if key in current_dict:
            current_dict = current_dict[key]
        else:
            print(f"Error: Key '{key}' not found in config.")
            return

    # 更新最后的键值
    last_key = keys[-1]
    if last_key in current_dict:
        current_dict[last_key] = new_value
    else:
        print(f"Error: Key '{last_key}' not found in config.")
        return

    # 将更新后的配置写回yaml文件，保留原有格式和注释
    with open(file_path, 'w') as file:
        yaml.dump(config, file)

    print(f"Config '{config_key}' updated to '{new_value}' in '{file_path}'.")
def update_yaml_config_dict(file_path, config_updates):
    """
    批量更新指定yaml文件的指定配置，保留原有格式和注释。

    :param file_path: str, yaml文件的路径。
    :param config_updates: dict, 要更新的配置键和值。
    :return: None
    """
    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        return

    # 使用ruamel.yaml读取yaml文件内容
    yaml = _new_yaml_parser()
    with open(file_path, 'r') as file:
        config = yaml.load(file)

    # 遍历要更新的配置
    for config_key, new_value in config_updates.items():
        keys = config_key.split('.')

        # 逐步深入字典，找到要更新的键
        current_dict = config
        for key in keys[:-1]:
            if key in current_dict:
                current_dict = current_dict[key]
            else:
                print(f"Error: Key '{key}' not found in config.")
                continue

        # 更新最后的键值
        last_key = keys[-1]
        if last_key in current_dict:
            current_dict[last_key] = new_value
        else:
            print(f"Error: Key '{last_key}' not found in config.")
            continue

    # 将更新后的配置写回yaml文件，保留原有格式和注释
    with open(file_path, 'w') as file:
        yaml.dump(config, file)

    print(f"Config updated in '{file_path}'.")
def update_remote_yaml_config_dict(remote_host, remote_path, config_updates, user, password, port=22):
    """
    批量更新远程主机上指定yaml文件的指定配置，保留原有格式和注释。
    :param remote_host: str, 远程主机的IP地址或主机名。
    :param remote_path: str, 远程主机上yaml文件的路径。
    :param config_updates: dict, 要更新的配置键和值。
    :param user: str, 登录远程主机的用户名。
    :param password: str, 登录远程主机的密码。
    :return: None
    """
    ssh = _new_ssh_client()
    # 连接服务器
    ssh.connect(remote_host, username=user, password=password, port=port)

    # 检查远程文件是否存在
    stdin, stdout, stderr = ssh.exec_command(f"[ -f {remote_path} ] && echo 'File exists' || echo 'File does not exist'")
    if "File does not exist" in stdout.read().decode():
        print(f"Error: File '{remote_path}' does not exist on remote host.")
        ssh.close()
        return

    # 读取远程yaml文件内容
    stdin, stdout, stderr = ssh.exec_command(f"cat {remote_path}")
    remote_yaml_content = stdout.read().decode()
    yaml = _new_yaml_parser()
    config = yaml.load(remote_yaml_content)

    # 遍历要更新的配置
    for config_key, new_value in config_updates.items():
        keys = config_key.split('.')

        # 逐步深入字典，找到要更新的键
        current_dict = config
        for key in keys[:-1]:
            if key in current_dict:
                current_dict = current_dict[key]
            else:
                print(f"Error: Key '{key}' not found in config.")
                continue

        # 更新最后的键值
        last_key = keys[-1]
        if last_key in current_dict:
            current_dict[last_key] = new_value
        else:
            print(f"Error: Key '{last_key}' not found in config.")
            continue

    # 将更新后的配置写回yaml字符串
    from io import StringIO
    updated_yaml_buffer = StringIO()
    yaml.dump(config, updated_yaml_buffer)
    updated_yaml_content = updated_yaml_buffer.getvalue()
    updated_yaml_buffer.close()

    # 通过临时文件上传更新后的yaml内容
    tmp_file = "/tmp/updated_config.yaml"
    with open(tmp_file, 'w') as file:
        file.write(updated_yaml_content)

    # 上传更新后的yaml文件到远程主机
    sftp = ssh.open_sftp()
    sftp.put(tmp_file, remote_path)

    # 删除临时文件
    os.remove(tmp_file)

    # 关闭连接
    sftp.close()
    ssh.close()

    print(f"Config updated in '{remote_path}' on remote host '{remote_host}'.")
def modify_config_option(filename, option, new_value):
    with open(filename, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if line.strip().startswith(f"{option}="):
            lines[i] = f"{option}={new_value}\n"
            break  # 找到并修改选项后立即退出循环

    with open(filename, 'w') as f:
        f.writelines(lines)
def update_config_option_dict(filename, config_updates):
    with open(filename, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        for option, new_value in config_updates.items():
            if line.strip().startswith(f"{option}="):
                lines[i] = f"{option}={new_value}\n"
                break  # 找到并修改选项后立即退出循环

    with open(filename, 'w') as f:
        f.writelines(lines)

    print(f"Config updated in '{filename}'.")
def update_remote_config_option_dict(remote_host, remote_path, config_updates, user, password, port=22):
    """
    更新远程主机上指定路径的gflags.conf文件配置。

    :param remote_host: str, 远程主机的IP地址或主机名。
    :param remote_path: str, 远程主机上gflags.conf文件的路径。
    :param config_updates: dict, 要更新的配置键和值。
    :param user: str, 登录远程主机的用户名。
    :param password: str, 登录远程主机的密码。
    :return: None
    """
    ssh = _new_ssh_client()
    # 连接服务器
    ssh.connect(remote_host, username=user, password=password, port=port)

    # 检查远程文件是否存在
    stdin, stdout, stderr = ssh.exec_command(f"[ -f {remote_path} ] && echo 'File exists' || echo 'File does not exist'")
    if "File does not exist" in stdout.read().decode():
        print(f"Error: File '{remote_path}' does not exist on remote host.")
        ssh.close()
        return

    # 读取远程gflags.conf文件内容
    stdin, stdout, stderr = ssh.exec_command(f"cat {remote_path}")
    remote_config_content = stdout.read().decode()
    lines = remote_config_content.splitlines()

    # 准备新的配置内容
    new_lines = []
    for line in lines:
        for option, new_value in config_updates.items():
            if line.strip().startswith(f"{option}="):
                new_lines.append(f"{option}={new_value}\n")
                break
        else:
            new_lines.append(line + '\n')

    # 如果配置文件中没有找到某些选项，则将它们添加到文件末尾
    for option, new_value in config_updates.items():
        if not any(line.strip().startswith(f"{option}=") for line in lines):
            new_lines.append(f"{option}={new_value}\n")

    # 将更新后的配置内容写回gflags.conf文件
    updated_config_content = ''.join(new_lines)
    tmp_file = "/tmp/updated_config.conf"
    with open(tmp_file, 'w') as f:
        f.write(updated_config_content)

    # 上传更新后的gflags.conf文件到远程主机
    sftp = ssh.open_sftp()
    sftp.put(tmp_file, remote_path)

    # 删除临时文件
    os.remove(tmp_file)

    # 关闭连接
    sftp.close()
    ssh.close()

    print(f"Config updated in '{remote_path}' on remote host '{remote_host}'.")
def send_param(yaml_para, store_config_para, index_config_para, coordinator_config_para):
    raise ValueError("send_param requires a database-specific deployer")


def send_default_param(*args, **kwargs):
    # Compatibility entry point for legacy DingoDB baselines.
    from databases.dingodb.deployer import send_default_param as dingodb_send_default_param

    return dingodb_send_default_param(*args, **kwargs)


def send_param_new(*args, **kwargs):
    # Compatibility entry point for legacy DingoDB baselines.
    from databases.dingodb.deployer import send_param_new as dingodb_send_param_new

    return dingodb_send_param_new(*args, **kwargs)
