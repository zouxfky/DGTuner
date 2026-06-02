import json
import re
import urllib.request

from dgtuner.llm_prior.paths import DEFAULT_LLM_ENV_PATH


def extract_json_object(value):
    if isinstance(value, dict):
        return value
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def call_llm(prompt, config):
    if not config["api_key"]:
        raise ValueError(f"LLM_API_KEY is required in {DEFAULT_LLM_ENV_PATH}")
    if not config["api_base_url"]:
        raise ValueError(f"LLM_API_BASE_URL is required in {DEFAULT_LLM_ENV_PATH}")
    if not config["model"]:
        raise ValueError(f"LLM_MODEL is required in {DEFAULT_LLM_ENV_PATH}")

    payload = {
        "model": config["model"],
        "temperature": config["temperature"],
        "messages": [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]},
        ],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        config["api_base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
        data = json.loads(response.read().decode("utf-8"))
    return extract_json_object(data["choices"][0]["message"]["content"])
