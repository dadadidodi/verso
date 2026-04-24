"""与 app.js 中 parseParagraphs 等价的段落切分（空行分段）。"""
from __future__ import annotations

import re
from pathlib import Path


def parse_paragraphs_text(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text.strip())
    out: list[str] = []
    for p in parts:
        normalized = re.sub(r"\s+", " ", p).strip()
        if normalized:
            out.append(normalized)
    return out


def load_paragraphs_from_path(path: Path) -> list[str]:
    return parse_paragraphs_text(path.read_text(encoding="utf-8"))
