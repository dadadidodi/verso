from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_event_lock = threading.Lock()


def _event_log_path() -> Path:
    custom = os.getenv("VERSO_SERVER_EVENTS_FILE", "").strip()
    if custom:
        return Path(custom)
    return Path("log") / "server_events.log"


def append_server_event(event_type: str, **fields: Any) -> None:
    path = _event_log_path()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **fields,
    }
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with _event_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
