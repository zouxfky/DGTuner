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


def _extract_output_text(data):
    """Pull the assistant text out of a Responses API payload (skipping reasoning)."""
    texts = []
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                texts.append(part["text"])
    return "\n".join(texts).strip()


def call_llm(prompt, config):
    if not config["api_key"]:
        raise ValueError(f"LLM_API_KEY is required in {DEFAULT_LLM_ENV_PATH}")
    if not config["api_base_url"]:
        raise ValueError(f"LLM_API_BASE_URL is required in {DEFAULT_LLM_ENV_PATH}")
    if not config["model"]:
        raise ValueError(f"LLM_MODEL is required in {DEFAULT_LLM_ENV_PATH}")

    try:
        from openai import OpenAI
    except ImportError:
        return _call_via_urllib(prompt, config)

    client = OpenAI(
        api_key=config["api_key"],
        base_url=config["api_base_url"],
        timeout=config["timeout"],
        max_retries=0,
    )
    try:
        response = client.responses.create(
            model=config["model"],
            instructions=prompt["system"],
            input=prompt["user"],
        )
        content = getattr(response, "output_text", None)
        if not content:
            content = _extract_output_text(response.model_dump())
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    if not content:
        raise RuntimeError("LLM returned an empty response (no output_text).")
    return extract_json_object(content)


def _call_via_urllib(prompt, config):
    payload = {
        "model": config["model"],
        "instructions": prompt["system"],
        "input": prompt["user"],
    }
    request = urllib.request.Request(
        config["api_base_url"].rstrip("/") + "/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = _extract_output_text(data)
    if not content:
        raise RuntimeError("LLM returned an empty response (no output_text).")
    return extract_json_object(content)
