from __future__ import annotations

import os
import re
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, value)


def env_flag(name: str) -> bool:
    load_env_file()
    value = os.getenv(name, "").strip().lower()
    return value in ("1", "true", "yes", "on")


def env_path(name: str, default: str | Path) -> Path:
    load_env_file()
    custom = os.getenv(name, "").strip()
    return Path(custom) if custom else Path(default)


def norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def safe_json_int(val: object, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
