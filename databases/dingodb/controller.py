import os
import time
import sys
import subprocess
from dgtuner.common.paths import database_dir

YAML_CONFIG_PATH = str(database_dir("dingodb") / "runtime.yaml")


def load_simple_yaml(config_path):
    try:
        import yaml

        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except ModuleNotFoundError:
        config = {}
        current_section = None
        with open(config_path, 'r') as file:
            for raw_line in file:
                line = raw_line.split('#', 1)[0].rstrip()
                if not line.strip():
                    continue
                if not line.startswith(' ') and ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    if value == '':
                        config[key] = {}
                        current_section = key
                    else:
                        config[key] = parse_yaml_scalar(value)
                        current_section = None
                elif current_section and ':' in line:
                    key, value = line.split(':', 1)
                    config[current_section][key.strip()] = parse_yaml_scalar(value.strip())
        return config


def parse_yaml_scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


class DBController:
    def __init__(self, config_path=YAML_CONFIG_PATH):
        config = load_simple_yaml(config_path)
        ssh = config.get("ssh", {})
        lifecycle = config.get("lifecycle", {})

        self.enabled = bool(lifecycle.get("enabled", True))
        self.remote = bool(ssh.get("enabled", False))
        self.ssh_host = ssh.get("host")
        self.ssh_port = int(ssh.get("port", 22))
        self.ssh_user = ssh.get("user")
        self.ssh_password = ssh.get("password")
        self.start_command = self._resolve_command(lifecycle.get("start"), config_path)
        self.start_check_command = self._resolve_command(lifecycle.get("start_check"), config_path)
        self.stop_command = self._resolve_command(lifecycle.get("stop"), config_path)
        self.stop_check_command = self._resolve_command(lifecycle.get("stop_check"), config_path)
        self.clear_log_command = self._resolve_command(lifecycle.get("clear_log"), config_path)
        self.max_retries = int(lifecycle.get("max_retries", 120))
        self.max_start_minutes = int(lifecycle.get("max_minutes", 7))

    def _execute_script(self, command):
        if not self.enabled or not command:
            return "", ""
        if self.remote:
            return self._execute_remote(command)
        try:
            result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return result.stdout.decode('utf-8'), result.stderr.decode('utf-8')
        except subprocess.CalledProcessError as e:
            return e.stdout.decode("utf-8", errors="ignore"), e.stderr.decode("utf-8", errors="ignore") or str(e)

    def _execute_remote(self, command):
        import paramiko

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_user,
                password=self.ssh_password,
            )
            stdin, stdout, stderr = ssh.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode("utf-8", errors="ignore")
            stderr_text = stderr.read().decode("utf-8", errors="ignore")
            if exit_status != 0 and not stderr_text:
                stderr_text = f"remote command failed with exit status {exit_status}"
            return stdout_text, stderr_text
        finally:
            ssh.close()

    def _resolve_command(self, command, config_path):
        if not command or self.remote:
            return command
        if os.path.isabs(str(command)):
            return command
        config_dir = os.path.dirname(os.path.abspath(config_path))
        return os.path.abspath(os.path.join(config_dir, str(command)))

    def start(self):
        """执行启动脚本"""
        return self._execute_script(self.start_command)

    def stop(self):
        """执行关闭脚本"""
        return self._execute_script(self.stop_command)

    def isStart(self):
        """执行是否启动成功脚本"""
        return self._execute_script(self.start_check_command)

    def isClosed(self):
        """执行启动脚本"""
        return self._execute_script(self.stop_check_command)

    def clear_node_log(self):
        return self._execute_script(self.clear_log_command)

    def print_attributes(self):
        for key, value in vars(self).items():
            print(f"{key}: {value}")

def isStarted(db_controller):
    attempts = 0
    start_time = time.time()  # 记录开始时间
    time_limit = db_controller.max_start_minutes * 60  # 将X分钟转换为秒
    loading_symbols = ['.', '..', '...']  # 循环使用的符号
    symbol_index = 0  # 当前符号的索引

    sys.stdout.write("启动中")  # 打印启动提示
    sys.stdout.flush()  # 刷新缓冲区，立即打印

    while True:
        stdout, stderr = db_controller.isStart()
        # 打印动态符号，不换行
        sys.stdout.write('\r启动中' + loading_symbols[symbol_index % len(loading_symbols)])
        sys.stdout.flush()  # 刷新缓冲区

        symbol_index += 1  # 更新符号索引
        time.sleep(1)  # 延迟 1 秒，模拟等待

        if "not" not in stdout:  # 假设 stdout 包含 "ok" 表示启动成功
            print("\r启动成功!" + " " * 10)  # 清除动态符号行并打印启动成功
            return True
        else:
            attempts += 1

        # 检查是否达到最大重试次数
        if attempts >= db_controller.max_retries:
            attempts = 0
            print(f"\n已达到最大重试次数 {db_controller.max_retries} 次，启动失败。")
            db_controller.stop()
            isClosed(db_controller)
            db_controller.start()

        # 检查是否达到时间限制
        elapsed_time = time.time() - start_time
        if elapsed_time >= time_limit:
            print(f"\n已达到时间限制 {db_controller.max_start_minutes} 分钟，退出。")
            return False

def isClosed(db_controller):
    attempts = 0
    start_time = time.time()  # 记录开始时间
    time_limit = db_controller.max_start_minutes * 60  # 将 X 分钟转换为秒
    loading_symbols = ['.', '..', '...']  # 循环使用的符号
    symbol_index = 0  # 当前符号的索引

    sys.stdout.write("关闭中")  # 打印关闭提示
    sys.stdout.flush()  # 刷新缓冲区，立即打印

    while True:
        stdout, stderr = db_controller.isClosed()
        # 打印动态符号，不换行
        sys.stdout.write('\r关闭中' + loading_symbols[symbol_index % len(loading_symbols)])
        sys.stdout.flush()  # 刷新缓冲区

        symbol_index += 1  # 更新符号索引
        time.sleep(1)  # 延迟 1 秒，模拟等待

        if "not" not in stdout:  # 假设 stdout 包含 "ok" 表示关闭成功
            print("\r关闭成功!" + " " * 10)  # 清除动态符号行并打印关闭成功
            return True
        else:
            attempts += 1

        # 检查是否达到最大重试次数
        if attempts >= db_controller.max_retries:
            attempts = 0
            print(f"\n已达到最大重试次数 {db_controller.max_retries} 次，关闭失败。")
            db_controller.stop()

        # 检查是否达到时间限制
        elapsed_time = time.time() - start_time
        if elapsed_time >= time_limit:
            print(f"\n已达到时间限制 {db_controller.max_start_minutes} 分钟，退出。")
            return False

def isFinished(db_controller):
    attempts = 0
    start_time = time.time()  # 记录开始时间
    time_limit = db_controller.max_start_minutes * 60  # 将X分钟转换为秒
    while True:
        stdout, stderr = db_controller.isFinished()
        print("是否执行完毕:", stdout)
        if "not" not in stdout:  # 假设 stdout 包含 "ok " 表示启动成功
            return True
        else:
            attempts += 1
            time.sleep(1)

        # 检查是否达到最大重试次数
        if attempts >= db_controller.max_retries:
            attempts = 0
            print(f"已达到最大重试次数 {db_controller.max_retries} 次，执行测试失败。")
            db_controller.stop()

        # 检查是否达到时间限制
        elapsed_time = time.time() - start_time
        if elapsed_time >= time_limit:
            print(f"已达到时间限制 {db_controller.max_minutes} 分钟，退出。")
            return False
