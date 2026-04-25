"""
集成测试：从 fixtures 读入中英文段落，调用 align_paragraphs_in_chapter_llm。

运行（仓库根目录）::
    pip install -r requirements-dev.txt
    pytest tests/test_align_paragraphs_in_chapter_llm.py -q

需要根目录 `.env` 中配置 OPENAI_API_KEY（及可选 OPENAI_MODEL 等）。

结构校验通过后，会将 flatten_map_from_blocks 的结果与
tests/fixtures/sample_small_expected_mapping.json 中的 flatten_en_index_by_zh 逐项比对；
修改样例正文后若失败，请人工核对映射并更新该 JSON。
"""
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
from paragraph_alignment import (  # noqa: E402
    AlignmentBlock,
    align_paragraphs_in_chapter_llm,
    flatten_map_from_blocks,
)
from tests.paragraph_loader import load_paragraphs_from_path  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def _assert_block_indices_in_range(blocks: list[AlignmentBlock], zh_len: int, en_len: int) -> None:
    for b in blocks:
        assert 1 <= b.zh_start <= zh_len
        assert 1 <= b.zh_end <= zh_len
        assert b.zh_start <= b.zh_end
        assert 1 <= b.en_start <= en_len
        assert 1 <= b.en_end <= en_len
        assert b.en_start <= b.en_end


def _assert_zh_partition(blocks: list[AlignmentBlock], zh_len: int) -> None:
    assert zh_len >= 1
    sorted_b = sorted(blocks, key=lambda x: (x.zh_start, x.zh_end))
    cursor = 1
    for b in sorted_b:
        assert b.zh_start == cursor, f"gap or overlap at zh cursor {cursor}, block {b}"
        assert b.zh_end >= b.zh_start
        cursor = b.zh_end + 1
    assert cursor == zh_len + 1


def _assert_en_monotone_across_blocks(blocks: list[AlignmentBlock]) -> None:
    sorted_b = sorted(blocks, key=lambda x: (x.zh_start, x.zh_end))
    for i in range(1, len(sorted_b)):
        assert sorted_b[i].en_start >= sorted_b[i - 1].en_end, (
            f"en not monotone: block {sorted_b[i - 1]} then {sorted_b[i]}"
        )


def _assert_flatten_map_non_decreasing(mapping: list[int]) -> None:
    for i in range(1, len(mapping)):
        assert mapping[i] >= mapping[i - 1]


def test_align_paragraphs_in_chapter_llm_structure() -> None:
    load_env_file(str(REPO_ROOT / ".env"))
    if not os.getenv("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY not set; configure repo root .env or environment")

    zh = load_paragraphs_from_path(FIXTURES_DIR / "sample_ch_small.txt")
    en = load_paragraphs_from_path(FIXTURES_DIR / "sample_en_small.txt")
    assert len(zh) >= 1 and len(en) >= 1

    config = get_api_config()
    try:
        blocks = align_paragraphs_in_chapter_llm(
            zh,
            en,
            config,
            debug_label="pytest_align_chapter",
        )
    except RuntimeError as exc:
        if "网络错误" in str(exc):
            pytest.skip(f"network unavailable in current environment: {exc}")
        raise

    assert isinstance(blocks, list)
    assert len(blocks) >= 1
    zh_len, en_len = len(zh), len(en)

    _assert_block_indices_in_range(blocks, zh_len, en_len)
    _assert_zh_partition(blocks, zh_len)
    _assert_en_monotone_across_blocks(blocks)

    mapping = flatten_map_from_blocks(blocks, zh_len, en_len)
    assert len(mapping) == zh_len
    _assert_flatten_map_non_decreasing(mapping)
    for v in mapping:
        assert 0 <= v < en_len

    golden_path = FIXTURES_DIR / "sample_small_expected_mapping.json"
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    expected = payload["flatten_en_index_by_zh"]
    assert isinstance(expected, list) and len(expected) == zh_len, (
        f"golden 长度应为 {zh_len}，实际 {expected!r}，请检查 {golden_path}"
    )
    assert mapping == expected, (
        f"flatten 映射与 golden 不一致: 得到 {mapping}，期望 {expected}。"
        f"若有意修改了样例 txt，请同步更新 {golden_path}。"
    )
