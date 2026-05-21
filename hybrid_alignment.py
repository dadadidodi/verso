from __future__ import annotations

import re
from dataclasses import asdict
from hashlib import sha256
from typing import Any, Dict, List, Optional, Sequence, Tuple

from alignment_common import ApiConfig
from alignment_service import map_chapters_ai
from paragraph_alignment import (
    AlignmentBlock,
    align_paragraphs_in_chapter_llm,
    build_review_items,
    expand_en_ranges_from_blocks,
    flatten_map_from_blocks,
    refine_large_blocks_llm,
)
from utils import norm_space


CHINESE_NUMS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

ROMAN_NUMS = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
    "xvi": 16,
    "xvii": 17,
    "xviii": 18,
    "xix": 19,
    "xx": 20,
}


def _extract_number(text: str) -> Optional[int]:
    m = re.search(r"\d+", text)
    if m:
        return int(m.group(0))
    roman = re.findall(r"\b[ivxlcdm]+\b", text.lower())
    for item in roman:
        if item in ROMAN_NUMS:
            return ROMAN_NUMS[item]
    if "第" in text:
        for key, value in CHINESE_NUMS.items():
            if key in text:
                return value
    return None


def _chapter_mapping_fallback(
    zh_chapters: Sequence[Dict[str, Any]],
    en_chapters: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not zh_chapters or not en_chapters:
        return []
    en_numbers = {
        idx: _extract_number(str(chapter.get("title", "")))
        for idx, chapter in enumerate(en_chapters)
    }
    results: List[Dict[str, Any]] = []
    last_en = 0
    en_count = len(en_chapters)
    zh_count = len(zh_chapters)
    for zh_index, zh_chapter in enumerate(zh_chapters):
        zh_title = str(zh_chapter.get("title", ""))
        zh_num = _extract_number(zh_title)
        choice = None
        if zh_num is not None:
            for en_index in range(last_en, en_count):
                if en_numbers.get(en_index) == zh_num:
                    choice = en_index
                    break
        if choice is None:
            relative = zh_index / max(1, zh_count - 1)
            choice = max(last_en, min(en_count - 1, round(relative * max(0, en_count - 1))))
        confidence = 0.68 if zh_num is not None and en_numbers.get(choice) == zh_num else 0.32
        reason = "fallback_number_match" if confidence > 0.6 else "fallback_position_match"
        results.append(
            {
                "zh_chapter_index": zh_index,
                "en_chapter_index": choice,
                "confidence": confidence,
                "source": "fallback",
                "reason": reason,
                "alternatives": [],
            }
        )
        last_en = choice
    return results


def suggest_chapter_mappings(
    zh_paragraphs: Sequence[str],
    zh_chapters: Sequence[Dict[str, Any]],
    en_paragraphs: Sequence[str],
    en_chapters: Sequence[Dict[str, Any]],
    config: ApiConfig,
    *,
    allow_llm: bool = True,
) -> Dict[str, Any]:
    del zh_paragraphs
    del en_paragraphs
    if not zh_chapters or not en_chapters:
        return {
            "mappings": [],
            "strategy": "empty",
            "fallback_reason": "",
        }
    zh_titles = [str(chapter.get("title", "")) for chapter in zh_chapters]
    en_titles = [str(chapter.get("title", "")) for chapter in en_chapters]
    if allow_llm and config.api_key:
        try:
            pairs = map_chapters_ai(zh_titles, en_titles, config)
            return {
                "mappings": [
                    {
                        "zh_chapter_index": pair.zh_index,
                        "en_chapter_index": pair.en_index,
                        "confidence": pair.confidence,
                        "source": "llm",
                        "reason": pair.reason,
                        "alternatives": [],
                    }
                    for pair in pairs
                ],
                "strategy": "llm",
                "fallback_reason": "",
            }
        except Exception as exc:
            return {
                "mappings": _chapter_mapping_fallback(zh_chapters, en_chapters),
                "strategy": "fallback",
                "fallback_reason": str(exc),
            }
    return {
        "mappings": _chapter_mapping_fallback(zh_chapters, en_chapters),
        "strategy": "fallback",
        "fallback_reason": "llm_disabled_or_missing_api_key",
    }


def _cache_key(
    zh_paragraphs: Sequence[str],
    en_paragraphs: Sequence[str],
    anchor_constraints: Sequence[Dict[str, Any]],
    *,
    engine_version: str,
    prompt_version: str,
    llm_policy: str,
) -> str:
    payload = (
        "\n".join(zh_paragraphs)
        + "\n---\n"
        + "\n".join(en_paragraphs)
        + "\n---\n"
        + str(sorted((
            a.get("zh_start", a.get("zh_paragraph_index")),
            a.get("zh_end", a.get("zh_paragraph_index")),
            a.get("en_start", a.get("en_paragraph_index")),
            a.get("en_end", a.get("en_paragraph_index")),
            a.get("kind"),
        ) for a in anchor_constraints))
        + "\n---\n"
        + engine_version
        + "\n"
        + prompt_version
        + "\n"
        + llm_policy
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _normalize_llm_policy(llm_policy: str, allow_llm: bool) -> str:
    policy = (llm_policy or "auto").strip().lower()
    if policy not in {"auto", "force", "off"}:
        policy = "auto"
    if not allow_llm:
        return "off"
    return policy


def _alignment_source(metrics: Dict[str, Any]) -> str:
    if metrics.get("llm_rate_limited"):
        return "fallback"
    if metrics.get("mode") == "skipped":
        return "skipped"
    llm_calls = int(metrics.get("llm_calls") or 0)
    heuristic_segments = int(metrics.get("heuristic_segments") or 0)
    if llm_calls > 0 and heuristic_segments > 0:
        return "mixed"
    if llm_calls > 0:
        return "lm"
    return "heuristic"


def _repair_blocks(blocks: Sequence[AlignmentBlock], zh_len: int, en_len: int) -> List[AlignmentBlock]:
    if zh_len <= 0 or en_len <= 0:
        return []
    repaired: List[AlignmentBlock] = []
    cursor_zh = 1
    cursor_en = 1
    for block in sorted(blocks, key=lambda b: (b.zh_start, b.en_start, b.zh_end, b.en_end)):
        if cursor_zh > zh_len:
            break
        zh_start = max(cursor_zh, min(zh_len, block.zh_start))
        zh_end = max(zh_start, min(zh_len, block.zh_end))
        en_start = max(cursor_en, min(en_len, block.en_start))
        en_end = max(en_start, min(en_len, block.en_end))
        repaired.append(
            AlignmentBlock(
                zh_start=zh_start,
                zh_end=zh_end,
                en_start=en_start,
                en_end=en_end,
                confidence=float(block.confidence),
                reason=block.reason,
            )
        )
        cursor_zh = zh_end + 1
        cursor_en = en_end
    if cursor_zh <= zh_len:
        repaired.append(
            AlignmentBlock(
                zh_start=cursor_zh,
                zh_end=zh_len,
                en_start=min(cursor_en, en_len),
                en_end=en_len,
                confidence=0.25,
                reason="filled_tail",
            )
        )
    return repaired


def _approximate_local_map(zh_paragraphs: Sequence[str], en_paragraphs: Sequence[str]) -> List[int]:
    zh_len = len(zh_paragraphs)
    en_len = len(en_paragraphs)
    if zh_len <= 0:
        return []
    if en_len <= 0:
        return [0] * zh_len

    def zh_role(text: str) -> str:
        clean = norm_space(text)
        if not clean:
            return "empty"
        if "书分享" in clean:
            return "footer"
        if "第 一 章" in clean or re.match(r"^第\s*[一二三四五六七八九十百千0-9]+\s*章", clean):
            return "title"
        if clean.startswith("——"):
            return "epigraph"
        if re.match(r"^(应是指|指|大约在公元)", clean):
            return "note"
        if re.search(r"\d{3,4}[—-]\d{2,4}", clean):
            return "note"
        return "main"

    def en_role(text: str) -> str:
        clean = norm_space(text)
        if not clean:
            return "empty"
        if re.match(r"^Chapter\s+\d+\b", clean, flags=re.I):
            return "title"
        if "BEAUMONT AND FLETCHER" in clean.upper():
            return "epigraph"
        return "main"

    zh_roles = [zh_role(text) for text in zh_paragraphs]
    en_roles = [en_role(text) for text in en_paragraphs]

    zh_prefix: List[int] = []
    for idx, role in enumerate(zh_roles):
        if role == "main":
            break
        zh_prefix.append(idx)

    en_prefix: List[int] = []
    for idx, role in enumerate(en_roles):
        if role == "main":
            break
        en_prefix.append(idx)

    mapping = [0] * zh_len
    for zh_idx, en_idx in zip(zh_prefix, en_prefix):
        mapping[zh_idx] = en_idx

    zh_main = [idx for idx, role in enumerate(zh_roles) if role == "main" and idx >= len(zh_prefix)]
    en_main = [idx for idx, role in enumerate(en_roles) if role == "main" and idx >= len(en_prefix)]
    if not zh_main:
        last = en_prefix[-1] if en_prefix else 0
        for idx in range(zh_len):
            mapping[idx] = max(0, min(en_len - 1, mapping[idx] if idx < len(zh_prefix) else last))
        return mapping
    if not en_main:
        last = en_prefix[-1] if en_prefix else 0
        for idx in range(zh_len):
            mapping[idx] = max(0, min(en_len - 1, mapping[idx] if idx < len(zh_prefix) else last))
        return mapping

    zh_weights = [max(1, len(zh_paragraphs[idx])) for idx in zh_main]
    en_weights = [max(1, len(en_paragraphs[idx])) for idx in en_main]
    total_zh = float(sum(zh_weights))
    total_en = float(sum(en_weights))
    en_midpoints: List[float] = []
    cursor_en = 0.0
    for weight in en_weights:
        en_midpoints.append(cursor_en + weight / 2.0)
        cursor_en += weight

    cursor_zh = 0.0
    for zh_idx, weight in zip(zh_main, zh_weights):
        target = ((cursor_zh + weight / 2.0) / max(1.0, total_zh)) * total_en
        local_choice = min(
            range(len(en_midpoints)),
            key=lambda local_idx: abs(en_midpoints[local_idx] - target),
        )
        mapping[zh_idx] = en_main[local_choice]
        cursor_zh += weight

    next_main_map: Dict[int, int] = {}
    upcoming = en_main[-1] if en_main else (en_prefix[-1] if en_prefix else 0)
    for idx in range(zh_len - 1, -1, -1):
        if zh_roles[idx] == "main":
            upcoming = mapping[idx]
        next_main_map[idx] = upcoming

    last_en = en_prefix[-1] if en_prefix else 0
    for idx, role in enumerate(zh_roles):
        if idx < len(zh_prefix):
            last_en = mapping[idx]
            continue
        if role == "main":
            last_en = mapping[idx]
        elif role == "note":
            mapping[idx] = next_main_map.get(idx, last_en)
        else:
            mapping[idx] = last_en

    last = 0
    for idx, value in enumerate(mapping):
        clamped = max(0, min(en_len - 1, int(value)))
        if clamped < last:
            clamped = last
        mapping[idx] = clamped
        last = clamped
    return mapping


def _heuristic_blocks(zh_paragraphs: Sequence[str], en_paragraphs: Sequence[str]) -> List[AlignmentBlock]:
    local_map = _approximate_local_map(zh_paragraphs, en_paragraphs)
    if not local_map:
        return []
    en_len = len(en_paragraphs)
    blocks: List[AlignmentBlock] = []
    previous = None
    for idx, en_index in enumerate(local_map, start=1):
        next_en_index = local_map[idx] if idx < len(local_map) else en_len
        range_start = 0 if idx == 1 else en_index
        range_end = en_index if next_en_index <= en_index else next_en_index - 1
        if idx == len(local_map):
            range_end = en_len - 1
        range_end = max(range_start, min(en_len - 1, range_end))
        confidence = 0.78
        if previous is not None:
            jump = en_index - previous
            if jump == 0:
                confidence = 0.74
            elif jump > 1:
                confidence = 0.62
        blocks.append(
            AlignmentBlock(
                zh_start=idx,
                zh_end=idx,
                en_start=range_start + 1,
                en_end=range_end + 1,
                confidence=confidence,
                reason="heuristic_length_guided",
            )
        )
        previous = en_index
    return blocks


def _normal_anchor_range(anchor: Dict[str, Any]) -> Tuple[int, int, int, int]:
    zh_start = int(anchor.get("zh_start", anchor.get("zh_paragraph_index", 0)))
    zh_end = int(anchor.get("zh_end", anchor.get("zh_paragraph_index", zh_start)))
    en_start = int(anchor.get("en_start", anchor.get("en_paragraph_index", 0)))
    en_end = int(anchor.get("en_end", anchor.get("en_paragraph_index", en_start)))
    zh_start, zh_end = sorted((zh_start, zh_end))
    en_start, en_end = sorted((en_start, en_end))
    return zh_start, zh_end, en_start, en_end


def _hard_anchor_ranges(anchors: Sequence[Dict[str, Any]], zh_len: int, en_len: int) -> List[Tuple[int, int, int, int]]:
    hard = [
        _normal_anchor_range(a)
        for a in anchors
        if a.get("kind") == "hard" and a.get("confirmed", True)
    ]
    hard.sort(key=lambda item: (item[0], item[2], item[1], item[3]))
    last_zh_end = -1
    last_en_end = -1
    for zh_start, zh_end, en_start, en_end in hard:
        if not (0 <= zh_start <= zh_end < zh_len):
            raise ValueError("anchor Chinese range out of bounds")
        if not (0 <= en_start <= en_end < en_len):
            raise ValueError("anchor English range out of bounds")
        if zh_start <= last_zh_end or en_start <= last_en_end:
            raise ValueError("hard anchors overlap or cross")
        last_zh_end = zh_end
        last_en_end = en_end
    return hard


def _anchor_segments(
    zh_len: int,
    en_len: int,
    anchors: Sequence[Dict[str, Any]],
) -> List[Tuple[int, int, int, int, Optional[Tuple[int, int, int, int]]]]:
    hard = _hard_anchor_ranges(anchors, zh_len, en_len)
    segments: List[Tuple[int, int, int, int, Optional[Tuple[int, int, int, int]]]] = []
    cursor_zh = 0
    cursor_en = 0
    for zh_start, zh_end, en_start, en_end in hard:
        if zh_start > cursor_zh:
            segments.append((cursor_zh, zh_start, cursor_en, en_start, None))
        segments.append((zh_start, zh_end + 1, en_start, en_end + 1, (zh_start, zh_end, en_start, en_end)))
        cursor_zh = zh_end + 1
        cursor_en = en_end + 1
    if cursor_zh < zh_len:
        segments.append((cursor_zh, zh_len, cursor_en, en_len, None))
    if not segments:
        segments.append((0, zh_len, 0, en_len, None))
    return segments


def _shift_blocks(blocks: Sequence[AlignmentBlock], zh_offset: int, en_offset: int) -> List[AlignmentBlock]:
    out: List[AlignmentBlock] = []
    for block in blocks:
        out.append(
            AlignmentBlock(
                zh_start=block.zh_start + zh_offset,
                zh_end=block.zh_end + zh_offset,
                en_start=block.en_start + en_offset,
                en_end=block.en_end + en_offset,
                confidence=float(block.confidence),
                reason=block.reason,
            )
        )
    return out


def _refine_segment_with_llm(
    zh_segment: Sequence[str],
    en_segment: Sequence[str],
    config: ApiConfig,
    *,
    debug_label: str,
) -> List[AlignmentBlock]:
    coarse = align_paragraphs_in_chapter_llm(zh_segment, en_segment, config, debug_label=debug_label)
    return refine_large_blocks_llm(coarse, zh_segment, en_segment, config, debug_label_prefix=debug_label)


def align_segment_hybrid(
    zh_segment: Sequence[str],
    en_segment: Sequence[str],
    config: ApiConfig,
    *,
    allow_llm: bool,
    force: bool,
    llm_policy: str = "auto",
    debug_label: str,
) -> Tuple[List[AlignmentBlock], Dict[str, Any]]:
    decision_base = {
        "debug_label": debug_label,
        "zh_len": len(zh_segment),
        "en_len": len(en_segment),
    }
    if not zh_segment or not en_segment:
        decision = {**decision_base, "method": "empty_gap", "reason": "empty_gap"}
        return [], {"llm_calls": 0, "heuristic_segments": 0, "decision_log": [decision]}

    policy = _normalize_llm_policy(llm_policy, allow_llm)
    has_api_key = bool(config.api_key)
    reason = "segment_too_large_and_balanced"
    wants_llm = False
    if policy == "off":
        reason = "llm_disabled"
    elif not has_api_key:
        reason = "missing_api_key"
    elif force or policy == "force":
        wants_llm = True
        reason = "force_policy"
    elif max(len(zh_segment), len(en_segment)) <= 12:
        wants_llm = True
        reason = "small_segment"
    elif abs(len(zh_segment) - len(en_segment)) >= 4:
        wants_llm = True
        reason = "imbalanced_segment"

    use_llm = wants_llm and has_api_key and policy != "off"
    if use_llm:
        blocks = _refine_segment_with_llm(zh_segment, en_segment, config, debug_label=debug_label)
        decision = {**decision_base, "method": "llm", "reason": reason}
        return blocks, {"llm_calls": 1, "heuristic_segments": 0, "decision_log": [decision]}
    decision = {**decision_base, "method": "heuristic", "reason": reason}
    return _heuristic_blocks(zh_segment, en_segment), {"llm_calls": 0, "heuristic_segments": 1, "decision_log": [decision]}


def align_chapter_hybrid(
    zh_paragraphs: Sequence[str],
    en_paragraphs: Sequence[str],
    config: ApiConfig,
    *,
    anchors: Sequence[Dict[str, Any]] | None = None,
    allow_llm: bool = True,
    force: bool = False,
    llm_policy: str = "auto",
    engine_version: str = "hybrid_v2",
    prompt_version: str = "v2",
    debug_label: str = "hybrid_align",
) -> Dict[str, Any]:
    anchors = list(anchors or [])
    policy = _normalize_llm_policy(llm_policy, allow_llm)
    zh_len = len(zh_paragraphs)
    en_len = len(en_paragraphs)
    cache_key = _cache_key(
        zh_paragraphs,
        en_paragraphs,
        anchors,
        engine_version=engine_version,
        prompt_version=prompt_version,
        llm_policy=policy,
    )
    if zh_len == 0 or en_len == 0:
        decision = {
            "segment_index": 0,
            "debug_label": debug_label,
            "zh_len": zh_len,
            "en_len": en_len,
            "method": "empty_gap",
            "reason": "empty_gap",
        }
        metrics = {
            "llm_calls": 0,
            "heuristic_segments": 0,
            "anchor_count": len(anchors),
            "llm_policy": policy,
            "decision_log": [decision],
        }
        metrics["alignment_source"] = _alignment_source(metrics)
        return {
            "blocks": [],
            "local_sync_map": [],
            "en_ranges_by_zh": [],
            "review_items": [],
            "metrics": metrics,
            "cache_key": cache_key,
        }

    hard_anchor_count = len(_hard_anchor_ranges(anchors, zh_len, en_len))
    if force and policy != "off" and config.api_key and hard_anchor_count == 0:
        blocks = _refine_segment_with_llm(zh_paragraphs, en_paragraphs, config, debug_label=f"{debug_label}_full")
        final_blocks = _repair_blocks(blocks, zh_len, en_len)
        decision = {
            "segment_index": 0,
            "debug_label": f"{debug_label}_full",
            "zh_len": zh_len,
            "en_len": en_len,
            "method": "llm",
            "reason": "force_policy",
        }
        metrics = {
            "llm_calls": 1,
            "heuristic_segments": 0,
            "anchor_count": len(anchors),
            "mode": "full_llm",
            "llm_policy": policy,
            "decision_log": [decision],
        }
        metrics["alignment_source"] = _alignment_source(metrics)
        return {
            "blocks": [asdict(b) for b in final_blocks],
            "local_sync_map": flatten_map_from_blocks(final_blocks, zh_len, en_len),
            "en_ranges_by_zh": [list(item) for item in expand_en_ranges_from_blocks(final_blocks, zh_len, en_len)],
            "review_items": build_review_items(final_blocks, 0),
            "metrics": metrics,
            "cache_key": cache_key,
        }

    final_blocks: List[AlignmentBlock] = []
    llm_calls = 0
    heuristic_segments = 0
    decision_log: List[Dict[str, Any]] = []
    segments = _anchor_segments(zh_len, en_len, anchors)
    for seg_no, (zh_start, zh_end, en_start, en_end, fixed_anchor) in enumerate(segments):
        if fixed_anchor is not None:
            anchor_zh_start, anchor_zh_end, anchor_en_start, anchor_en_end = fixed_anchor
            decision_log.append(
                {
                    "segment_index": seg_no,
                    "debug_label": f"{debug_label}_anchor_{seg_no}",
                    "zh_len": anchor_zh_end - anchor_zh_start + 1,
                    "en_len": anchor_en_end - anchor_en_start + 1,
                    "method": "hard_anchor",
                    "reason": "hard_anchor",
                }
            )
            final_blocks.append(
                AlignmentBlock(
                    zh_start=anchor_zh_start + 1,
                    zh_end=anchor_zh_end + 1,
                    en_start=anchor_en_start + 1,
                    en_end=anchor_en_end + 1,
                    confidence=0.99,
                    reason="hard_anchor",
                )
            )
            continue
        local_zh = list(zh_paragraphs[zh_start:zh_end])
        local_en = list(en_paragraphs[en_start:en_end])
        if not local_zh:
            decision_log.append(
                {
                    "segment_index": seg_no,
                    "debug_label": f"{debug_label}_segment_{seg_no}",
                    "zh_len": 0,
                    "en_len": len(local_en),
                    "method": "empty_gap",
                    "reason": "empty_chinese_gap",
                }
            )
            continue
        if not local_en:
            en_idx = max(1, min(en_len, en_start if en_start > 0 else 1))
            decision_log.append(
                {
                    "segment_index": seg_no,
                    "debug_label": f"{debug_label}_segment_{seg_no}",
                    "zh_len": len(local_zh),
                    "en_len": 0,
                    "method": "empty_gap",
                    "reason": "empty_english_gap",
                }
            )
            final_blocks.append(
                AlignmentBlock(
                    zh_start=zh_start + 1,
                    zh_end=zh_end,
                    en_start=en_idx,
                    en_end=en_idx,
                    confidence=0.2,
                    reason="empty_english_anchor_gap",
                )
            )
            continue
        local_blocks, segment_metrics = align_segment_hybrid(
            local_zh,
            local_en,
            config,
            allow_llm=allow_llm,
            force=force,
            llm_policy=policy,
            debug_label=f"{debug_label}_segment_{seg_no}",
        )
        llm_calls += segment_metrics["llm_calls"]
        heuristic_segments += segment_metrics["heuristic_segments"]
        for decision in segment_metrics.get("decision_log", []):
            decision_log.append({"segment_index": seg_no, **decision})
        final_blocks.extend(_shift_blocks(local_blocks, zh_start, en_start))
    repaired = _repair_blocks(final_blocks, zh_len, en_len)
    local_sync_map = flatten_map_from_blocks(repaired, zh_len, en_len)
    review_items = build_review_items(repaired, 0)
    metrics = {
        "llm_calls": llm_calls,
        "heuristic_segments": heuristic_segments,
        "anchor_count": hard_anchor_count,
        "mode": "hybrid",
        "llm_policy": policy,
        "decision_log": decision_log,
    }
    metrics["alignment_source"] = _alignment_source(metrics)
    return {
        "blocks": [asdict(b) for b in repaired],
        "local_sync_map": local_sync_map,
        "en_ranges_by_zh": [list(item) for item in expand_en_ranges_from_blocks(repaired, zh_len, en_len)],
        "review_items": review_items,
        "metrics": metrics,
        "cache_key": cache_key,
    }
