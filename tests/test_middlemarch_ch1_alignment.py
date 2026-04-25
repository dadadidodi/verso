from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alignment_common import get_api_config, load_env_file  # noqa: E402
from chapter_catalog import extract_epub_document_from_bytes  # noqa: E402
from hybrid_alignment import align_chapter_hybrid  # noqa: E402
from paragraph_alignment import AlignmentBlock, expand_en_ranges_from_blocks  # noqa: E402
from tests.paragraph_loader import load_paragraphs_from_path  # noqa: E402


FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
ZH_FIXTURE = FIXTURES_DIR / "middlemarch_ch1_zh.txt"
EN_FIXTURE = FIXTURES_DIR / "middlemarch_ch1_en.txt"
GOLD_FIXTURE = FIXTURES_DIR / "middlemarch_ch1_gold.json"


def _load_gold() -> dict:
    return json.loads(GOLD_FIXTURE.read_text(encoding="utf-8"))


def _metrics(predicted: list[int], expected: list[int]) -> tuple[float, float, float]:
    assert len(predicted) == len(expected)
    exact = sum(1 for actual, gold in zip(predicted, expected) if actual == gold) / len(expected)
    within_1 = sum(1 for actual, gold in zip(predicted, expected) if abs(actual - gold) <= 1) / len(expected)
    mae = sum(abs(actual - gold) for actual, gold in zip(predicted, expected)) / len(expected)
    return exact, within_1, mae


def _assert_monotone(mapping: list[int], en_len: int) -> None:
    assert mapping
    last = 0
    for value in mapping:
        assert 0 <= value < en_len
        assert value >= last
        last = value


def test_middlemarch_ch1_fixtures_match_epub_source() -> None:
    zh_fixture = load_paragraphs_from_path(ZH_FIXTURE)
    en_fixture = load_paragraphs_from_path(EN_FIXTURE)
    gold = _load_gold()

    zh_paragraphs, zh_chapters = extract_epub_document_from_bytes((REPO_ROOT / gold["zh_source"]).read_bytes())
    en_paragraphs, en_chapters = extract_epub_document_from_bytes((REPO_ROOT / gold["en_source"]).read_bytes())

    zh_chapter = zh_chapters[gold["zh_chapter_index"]]
    en_chapter = en_chapters[gold["en_chapter_index"]]

    assert zh_chapter.title == gold["zh_title"]
    assert en_chapter.title == gold["en_title"]

    zh_expected = zh_paragraphs[zh_chapter.start : zh_chapter.end + 1]
    en_expected = en_paragraphs[en_chapter.start : en_chapter.end + 1]

    assert zh_fixture == zh_expected
    assert en_fixture == en_expected
    assert len(zh_fixture) == gold["zh_paragraph_count"] == 56
    assert len(en_fixture) == gold["en_paragraph_count"] == 51
    assert len(gold["flatten_en_index_by_zh"]) == len(zh_fixture)
    assert len(gold["en_ranges_by_zh"]) == len(zh_fixture)


def test_align_chapter_hybrid_middlemarch_ch1_offline_regression() -> None:
    zh = load_paragraphs_from_path(ZH_FIXTURE)
    en = load_paragraphs_from_path(EN_FIXTURE)
    expected = _load_gold()["flatten_en_index_by_zh"]

    result = align_chapter_hybrid(
        zh,
        en,
        get_api_config(),
        allow_llm=False,
        debug_label="pytest_middlemarch_ch1_offline",
    )

    mapping = result["local_sync_map"]
    assert len(result["en_ranges_by_zh"]) == len(zh)
    assert len(mapping) == len(zh) == _load_gold()["zh_paragraph_count"]
    _assert_monotone(mapping, len(en))

    exact, within_1, mae = _metrics(mapping, expected)
    assert exact >= 0.70, f"exact_match_rate too low: {exact:.3f}"
    assert within_1 >= 0.90, f"within_1_rate too low: {within_1:.3f}"
    assert mae <= 0.60, f"mean_abs_error too high: {mae:.3f}"


def test_align_chapter_hybrid_middlemarch_ch1_offline_preserves_english_ranges() -> None:
    zh = load_paragraphs_from_path(ZH_FIXTURE)
    en = load_paragraphs_from_path(EN_FIXTURE)
    gold = _load_gold()

    result = align_chapter_hybrid(
        zh,
        en,
        get_api_config(),
        allow_llm=False,
        debug_label="pytest_middlemarch_ch1_offline_ranges",
    )

    blocks = [
        AlignmentBlock(
            zh_start=int(block["zh_start"]),
            zh_end=int(block["zh_end"]),
            en_start=int(block["en_start"]),
            en_end=int(block["en_end"]),
            confidence=float(block.get("confidence", 0.0)),
            reason=str(block.get("reason", "")),
        )
        for block in result["blocks"]
    ]
    ranges = expand_en_ranges_from_blocks(blocks, len(zh), len(en))
    assert ranges == [tuple(item) for item in result["en_ranges_by_zh"]]
    covered = {en_idx for start, end in ranges for en_idx in range(start, end + 1)}
    assert covered == set(range(len(en)))
    assert ranges[16] == tuple(gold["en_ranges_by_zh"][16])
    assert ranges[23] == tuple(gold["en_ranges_by_zh"][23])


def test_align_chapter_hybrid_middlemarch_ch1_llm_regression() -> None:
    load_env_file(str(REPO_ROOT / ".env"))
    if not os.getenv("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY not set; skip live LLM alignment regression")

    zh = load_paragraphs_from_path(ZH_FIXTURE)
    en = load_paragraphs_from_path(EN_FIXTURE)
    expected = _load_gold()["flatten_en_index_by_zh"]

    try:
        result = align_chapter_hybrid(
            zh,
            en,
            get_api_config(),
            allow_llm=True,
            debug_label="pytest_middlemarch_ch1_llm",
        )
    except RuntimeError as exc:
        if "网络错误" in str(exc) or "HTTP 429" in str(exc) or "rate_limit_exceeded" in str(exc):
            pytest.skip(f"live LLM unavailable in current environment: {exc}")
        raise

    mapping = result["local_sync_map"]
    assert len(result["en_ranges_by_zh"]) == len(zh)
    assert len(mapping) == len(zh) == _load_gold()["zh_paragraph_count"]
    _assert_monotone(mapping, len(en))

    exact, within_1, mae = _metrics(mapping, expected)
    assert exact >= 0.82, f"exact_match_rate too low: {exact:.3f}"
    assert within_1 >= 0.95, f"within_1_rate too low: {within_1:.3f}"
    assert mae <= 0.35, f"mean_abs_error too high: {mae:.3f}"
