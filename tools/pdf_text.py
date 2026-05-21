from __future__ import annotations

import re
import shutil
from typing import List, Tuple

from utils import norm_space


def clean_pdf_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [norm_space(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def split_pdf_paragraphs(text: str) -> List[str]:
    cleaned = clean_pdf_text(text)
    if not cleaned:
        return []
    parts = re.split(r"\n\s*\n+", cleaned)
    if len(parts) > 1:
        return [norm_space(part.replace("\n", " ")) for part in parts if len(norm_space(part)) >= 2]

    paragraphs: List[str] = []
    current = ""
    for line in (line for line in cleaned.splitlines() if line):
        if looks_like_noise_line(line):
            continue
        if not current:
            current = line
        elif looks_like_heading(line) or ends_sentence(current):
            paragraphs.append(current)
            current = line
        else:
            current = norm_space(f"{current} {line}")
    if current:
        paragraphs.append(current)
    return [item for item in paragraphs if len(item) >= 2]


def looks_like_noise_line(line: str) -> bool:
    return bool(re.fullmatch(r"\d{1,4}", line) or re.fullmatch(r"[-–—·•\s]+", line))


def ends_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?。！？;；:”’\"']$", text.strip()))


def looks_like_heading(text: str) -> bool:
    clean = norm_space(text)
    if not clean or len(clean) > 80:
        return False
    return bool(
        re.match(
            r"^(chapter|book|part|section)\b|^第[一二三四五六七八九十百零〇\d]+[章节卷部篇]|^\d{1,3}[.)、]\s+",
            clean,
            flags=re.I,
        )
    )


def read_tesseract_languages(language: str) -> Tuple[str, List[str]]:
    warnings: List[str] = []
    if shutil.which("tesseract") is None:
        warnings.append("tesseract binary not found; scanned PDF pages cannot be OCRed")
        return "", warnings
    desired = "chi_sim+chi_tra+eng" if language == "zh" else "eng"
    try:
        import pytesseract

        available = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # pragma: no cover - depends on local tesseract install
        warnings.append(f"could not inspect tesseract languages: {exc}")
        return desired, warnings
    selected = [item for item in desired.split("+") if item in available]
    if not selected:
        warnings.append(f"missing requested tesseract language pack(s): {desired}")
        return "", warnings
    missing = [item for item in desired.split("+") if item not in available]
    if missing:
        warnings.append(f"missing tesseract language pack(s): {'+'.join(missing)}")
    return "+".join(selected), warnings


def text_quality_ok(text: str) -> bool:
    clean = norm_space(text)
    if len(clean) < 20:
        return False
    readable = sum(1 for ch in clean if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return readable / max(1, len(clean)) >= 0.45
