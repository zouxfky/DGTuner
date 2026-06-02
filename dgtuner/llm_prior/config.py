import os
from pathlib import Path

from dgtuner.llm_prior.paths import DEFAULT_LLM_ENV_PATH


def load_env_file(path=DEFAULT_LLM_ENV_PATH):
    values = {}
    path = Path(path)
    if not path.exists():
        return values
    with open(path, "r") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def llm_config():
    env = load_env_file()
    return {
        "api_base_url": env.get("LLM_API_BASE_URL") or os.environ.get("LLM_API_BASE_URL"),
        "api_key": env.get("LLM_API_KEY") or os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY"),
        "model": env.get("LLM_MODEL") or os.environ.get("LLM_MODEL"),
        "temperature": float(env.get("LLM_TEMPERATURE") or os.environ.get("LLM_TEMPERATURE") or 0),
        "timeout": int(env.get("LLM_TIMEOUT") or os.environ.get("LLM_TIMEOUT") or 180),
    }
