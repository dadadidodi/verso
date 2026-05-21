from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from utils import env_flag, env_path, load_env_file

_llm_debug_lock = threading.Lock()


@dataclass
class ApiConfig:
    api_base_url: str
    api_key: str
    model: str


def get_api_config(
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> ApiConfig:
    load_env_file()
    return ApiConfig(
        api_base_url=api_base_url or os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key or os.getenv("OPENAI_API_KEY", ""),
        model=model or os.getenv("OPENAI_MODEL", "gpt-4.1"),
    )


def is_llm_debug_enabled() -> bool:
    return env_flag("VERSO_LLM_DEBUG")


def _llm_debug_file_path() -> Path:
    return env_path("VERSO_LLM_DEBUG_FILE", Path("log") / "llm_debug.log")


def append_llm_debug_record(
    label: str,
    config: ApiConfig,
    system_prompt: str,
    user_prompt: str,
    *,
    raw_api_payload: Optional[Dict[str, Any]] = None,
    assistant_content: Optional[str] = None,
    parsed_json: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    if not is_llm_debug_enabled():
        return
    path = _llm_debug_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        "",
        "=" * 88,
        f"[{ts}]  {label}",
        f"model={config.model}",
        "----- SYSTEM PROMPT -----",
        system_prompt,
        "----- USER PROMPT -----",
        user_prompt,
    ]
    if error:
        parts.extend(["----- ERROR -----", error])
    else:
        if raw_api_payload is not None:
            parts.append("----- RAW API RESPONSE (full JSON) -----")
            parts.append(json.dumps(raw_api_payload, ensure_ascii=False, indent=2))
        if assistant_content is not None:
            parts.append("----- ASSISTANT message.content (raw string) -----")
            parts.append(assistant_content)
        if parsed_json is not None:
            parts.append("----- PARSED JSON OBJECT (from message.content) -----")
            parts.append(json.dumps(parsed_json, ensure_ascii=False, indent=2))
    parts.append("")
    block = "\n".join(parts) + "\n"
    with _llm_debug_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(block)


def call_chat_json(
    config: ApiConfig,
    system_prompt: str,
    user_prompt: str,
    timeout: int = 120,
    *,
    debug_label: str = "",
) -> Dict[str, Any]:
    if not config.api_key:
        raise ValueError("缺少 API Key：请在 .env 或环境变量中设置 OPENAI_API_KEY")
    body = {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    url = f"{config.api_base_url.rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"},
        method="POST",
    )
    label = debug_label or "call_chat_json"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        append_llm_debug_record(
            label,
            config,
            system_prompt,
            user_prompt,
            error=f"HTTP {e.code}: {detail}",
        )
        raise RuntimeError(f"AI API HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        append_llm_debug_record(
            label,
            config,
            system_prompt,
            user_prompt,
            error=f"URLError: {e}",
        )
        raise RuntimeError(f"AI API 网络错误: {e}") from e

    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        append_llm_debug_record(
            label,
            config,
            system_prompt,
            user_prompt,
            raw_api_payload=payload,
            error="choices[0].message.content 为空",
        )
        raise RuntimeError("AI 返回为空")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        append_llm_debug_record(
            label,
            config,
            system_prompt,
            user_prompt,
            raw_api_payload=payload,
            assistant_content=content,
            error=f"message.content 不是合法 JSON: {e}",
        )
        raise RuntimeError("AI 返回格式错误") from e
    if not isinstance(parsed, dict):
        append_llm_debug_record(
            label,
            config,
            system_prompt,
            user_prompt,
            raw_api_payload=payload,
            assistant_content=content,
            error="解析结果不是 JSON object",
        )
        raise RuntimeError("AI 返回格式错误")
    append_llm_debug_record(
        label,
        config,
        system_prompt,
        user_prompt,
        raw_api_payload=payload,
        assistant_content=content,
        parsed_json=parsed,
    )
    return parsed
