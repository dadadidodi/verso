from __future__ import annotations

from llm_client import ApiConfig
import hybrid_alignment
from hybrid_alignment import align_chapter_hybrid
from paragraph_alignment import AlignmentBlock


def test_force_policy_uses_llm_for_free_segments(monkeypatch):
    calls: list[tuple[int, int, str]] = []

    def fake_refine(zh_segment, en_segment, config, *, debug_label):
        calls.append((len(zh_segment), len(en_segment), debug_label))
        return [
            AlignmentBlock(
                zh_start=1,
                zh_end=len(zh_segment),
                en_start=1,
                en_end=len(en_segment),
                confidence=0.9,
                reason="fake_llm",
            )
        ]

    monkeypatch.setattr(hybrid_alignment, "_refine_segment_with_llm", fake_refine)
    config = ApiConfig(api_base_url="http://example.test", api_key="test-key", model="test-model")
    result = align_chapter_hybrid(
        ["中一", "中二", "中三"],
        ["en one", "en two", "en three"],
        config,
        allow_llm=True,
        force=False,
        llm_policy="force",
    )

    assert calls
    assert result["metrics"]["alignment_source"] == "lm"
    assert result["metrics"]["decision_log"][0]["reason"] == "force_policy"


def test_force_policy_respects_hard_anchor(monkeypatch):
    calls: list[tuple[int, int, str]] = []

    def fake_refine(zh_segment, en_segment, config, *, debug_label):
        calls.append((len(zh_segment), len(en_segment), debug_label))
        return [
            AlignmentBlock(
                zh_start=1,
                zh_end=len(zh_segment),
                en_start=1,
                en_end=len(en_segment),
                confidence=0.9,
                reason="fake_llm",
            )
        ]

    monkeypatch.setattr(hybrid_alignment, "_refine_segment_with_llm", fake_refine)
    config = ApiConfig(api_base_url="http://example.test", api_key="test-key", model="test-model")
    result = align_chapter_hybrid(
        ["中一", "中二", "中三"],
        ["en one", "en two", "en three"],
        config,
        anchors=[
            {
                "zh_start": 1,
                "zh_end": 1,
                "en_start": 1,
                "en_end": 1,
                "kind": "hard",
                "confirmed": True,
            }
        ],
        allow_llm=True,
        force=True,
        llm_policy="force",
    )

    assert any(block["reason"] == "hard_anchor" for block in result["blocks"])
    assert all("anchor" not in call[2] for call in calls)
    assert any(item["method"] == "hard_anchor" for item in result["metrics"]["decision_log"])
    assert result["metrics"]["alignment_source"] == "lm"


def test_missing_api_key_records_heuristic_reason():
    config = ApiConfig(api_base_url="", api_key="", model="")
    result = align_chapter_hybrid(
        ["中一", "中二"],
        ["en one", "en two"],
        config,
        allow_llm=True,
        force=False,
        llm_policy="force",
    )

    assert result["metrics"]["alignment_source"] == "heuristic"
    assert result["metrics"]["decision_log"][0]["reason"] == "missing_api_key"
