from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from alignment_common import ApiConfig, call_chat_json, norm_space, safe_json_int


@dataclass
class AlignmentBlock:
    zh_start: int
    zh_end: int
    en_start: int
    en_end: int
    confidence: float
    reason: str


@dataclass
class ChapterAlignment:
    chapter_index: int
    blocks: List[AlignmentBlock]
    review_items: List[Dict[str, object]]


def _format_paragraphs_for_prompt(label: str, paragraphs: Sequence[str]) -> str:
    lines = [f"{label} paragraphs ({len(paragraphs)}):"]
    for idx, text in enumerate(paragraphs, start=1):
        lines.append(f"{idx:04d}. {norm_space(text)}")
    return "\n".join(lines)


def _coerce_blocks(
    raw_blocks: Sequence[dict],
    zh_len: int,
    en_len: int,
) -> List[AlignmentBlock]:
    blocks: List[AlignmentBlock] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        zh_start = max(1, safe_json_int(raw.get("zh_start"), 0))
        zh_end = max(zh_start, safe_json_int(raw.get("zh_end"), zh_start))
        en_start = max(1, safe_json_int(raw.get("en_start"), 0))
        en_end = max(en_start, safe_json_int(raw.get("en_end"), en_start))
        zh_start = min(zh_start, zh_len)
        zh_end = min(zh_end, zh_len)
        en_start = min(en_start, en_len)
        en_end = min(en_end, en_len)
        _conf = raw.get("confidence", 0.5)
        confidence = float(0.5 if _conf is None else _conf)
        reason = str(raw.get("reason", "")).strip()
        blocks.append(
            AlignmentBlock(
                zh_start=zh_start,
                zh_end=zh_end,
                en_start=en_start,
                en_end=en_end,
                confidence=confidence,
                reason=reason,
            )
        )
    if not blocks:
        blocks = [AlignmentBlock(1, zh_len, 1, en_len, 0.2, "fallback_whole_chapter")]
    blocks.sort(key=lambda b: (b.zh_start, b.zh_end))
    return _repair_monotonic_blocks(blocks, zh_len, en_len)


def _repair_monotonic_blocks(blocks: List[AlignmentBlock], zh_len: int, en_len: int) -> List[AlignmentBlock]:
    repaired: List[AlignmentBlock] = []
    cursor_zh = 1
    cursor_en = 1
    for block in blocks:
        zh_start = max(cursor_zh, block.zh_start)
        zh_end = max(zh_start, block.zh_end)
        if zh_start > zh_len:
            break
        zh_end = min(zh_end, zh_len)

        en_start = max(cursor_en, block.en_start)
        en_end = max(en_start, block.en_end)
        en_start = min(en_start, en_len)
        en_end = min(en_end, en_len)

        repaired.append(
            AlignmentBlock(
                zh_start=zh_start,
                zh_end=zh_end,
                en_start=en_start,
                en_end=en_end,
                confidence=block.confidence,
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
                confidence=0.2,
                reason="filled_tail",
            )
        )
    return repaired


def align_paragraphs_in_chapter_llm(
    zh_paragraphs: Sequence[str],
    en_paragraphs: Sequence[str],
    config: ApiConfig,
    *,
    debug_label: str = "align_paragraphs_in_chapter",
) -> List[AlignmentBlock]:
    if not zh_paragraphs or not en_paragraphs:
        return []

    system_prompt = (
        "You align Chinese–English parallel text for a translated book: the two sides are the same work "
        "in translation. Your job is translation-aware alignment — pair paragraph ranges by semantic "
        "correspondence (what means the same in the other language), not by length, position, or "
        "superficial similarity alone. Return JSON blocks: each block pairs one contiguous Chinese "
        "index range with one contiguous English index range. Indices are 1-based inclusive. "
        "Preserve reading order (monotone). Prefer the finest reasonable split: do not merge consecutive "
        "1:1 paragraph pairs into one wide block when two separate blocks would be correct."
    )
    user_prompt = (
        "Context: These numbered lists are Chinese and English passages from the same translated book. "
        "Treat this as a translation-alignment task: each block must reflect which English paragraph(s) "
        "actually translate or correspond in meaning to which Chinese paragraph(s), in order through the chapter.\n\n"
        "Output JSON only. Schema:\n"
        "{\"blocks\":[{\"zh_start\":1,\"zh_end\":3,\"en_start\":1,\"en_end\":2,\"confidence\":0.82,\"reason\":\"...\"}]}\n"
        "Rules (all zh_start/zh_end/en_start/en_end are 1-based inclusive):\n"
        "1) Chinese coverage: blocks sorted by zh_start; together they must partition zh indices "
        "1..len(zh) exactly once each — no gaps, no overlaps.\n"
        "2) English monotonicity across blocks: if block A is immediately before block B in the list, "
        "then B.en_start >= A.en_end (English may touch at the boundary, e.g. A ends at en 5 and B starts at en 5).\n"
        "3) Within each block, many-to-many is allowed: several zh paragraphs to one en, one zh to several en, or N:M.\n"
        "4) Examples: many-zh one-en: zh_start=1,zh_end=3,en_start=1,en_end=1. "
        "N:M: zh_start=2,zh_end=4,en_start=3,en_end=6 means Chinese paras 2–4 align to English paras 3–6.\n"
        "5) confidence in [0,1]; use reason to briefly note semantic link when helpful.\n"
        "6) Prefer semantic translation equivalence over mechanical heuristics (e.g. do not align "
        "only because two paragraphs are the same length).\n"
        "7) Block granularity — do NOT merge unnecessarily: if Chinese paragraph i corresponds one-to-one "
        "to English paragraph j, and Chinese i+1 corresponds one-to-one to English j+1, you must output "
        "TWO blocks ({zh i, en j} and {zh i+1, en j+1}), not a single merged block spanning zh i–i+1 and "
        "en j–j+1. Use one block covering multiple zh indices only when they truly form an N:M or many-to-one "
        "translation unit (e.g. several zh paragraphs render as one en paragraph, or one zh spans several en). "
        "Never merge adjacent 1:1 pairs for convenience.\n"
        "8) The Chinese side may contain translator/editor notes or EPUB footnotes accidentally inserted "
        "as normal paragraphs. These often explain names, books, places, or allusions, and may contain dates "
        "like （1778—1829）. Do not treat note-only paragraphs as main narrative/dialogue that consumes new "
        "English paragraphs. If they must be covered, attach them to the nearest relevant English range with "
        "lower confidence and explain that they are translator notes.\n\n"
        f"{_format_paragraphs_for_prompt('Chinese', zh_paragraphs)}\n\n"
        f"{_format_paragraphs_for_prompt('English', en_paragraphs)}"
    )
    parsed = call_chat_json(
        config,
        system_prompt,
        user_prompt,
        timeout=600,
        debug_label=debug_label,
    )
    raw_blocks = parsed.get("blocks")
    if not isinstance(raw_blocks, list):
        raw_blocks = []
    return _coerce_blocks(raw_blocks, len(zh_paragraphs), len(en_paragraphs))


def refine_large_blocks_llm(
    blocks: Sequence[AlignmentBlock],
    zh_paragraphs: Sequence[str],
    en_paragraphs: Sequence[str],
    config: ApiConfig,
    threshold: int = 8,
    max_refine_calls: int = 2,
    *,
    debug_label_prefix: str = "",
) -> List[AlignmentBlock]:
    refined: List[AlignmentBlock] = []
    candidates = list(blocks)
    large_indexes = [
        idx
        for idx, block in enumerate(candidates)
        if (block.zh_end - block.zh_start + 1) > threshold or (block.en_end - block.en_start + 1) > threshold
    ]
    large_indexes.sort(
        key=lambda idx: max(
            candidates[idx].zh_end - candidates[idx].zh_start + 1,
            candidates[idx].en_end - candidates[idx].en_start + 1,
        ),
        reverse=True,
    )
    refine_set = set(large_indexes[: max(0, max_refine_calls)])

    for idx, block in enumerate(candidates):
        zh_span = block.zh_end - block.zh_start + 1
        en_span = block.en_end - block.en_start + 1
        need_refine = zh_span > threshold or en_span > threshold
        if not need_refine or idx not in refine_set:
            refined.append(block)
            continue

        local_zh = zh_paragraphs[block.zh_start - 1 : block.zh_end]
        local_en = en_paragraphs[block.en_start - 1 : block.en_end]
        if not local_zh or not local_en:
            refined.append(block)
            continue
        sub_label = (
            f"{debug_label_prefix}_refine_{idx}"
            if debug_label_prefix
            else f"refine_block_{idx}"
        )
        local_blocks = align_paragraphs_in_chapter_llm(
            local_zh,
            local_en,
            config,
            debug_label=sub_label,
        )
        if not local_blocks:
            refined.append(block)
            continue
        for lb in local_blocks:
            refined.append(
                AlignmentBlock(
                    zh_start=block.zh_start + lb.zh_start - 1,
                    zh_end=block.zh_start + lb.zh_end - 1,
                    en_start=block.en_start + lb.en_start - 1,
                    en_end=block.en_start + lb.en_end - 1,
                    confidence=lb.confidence,
                    reason=f"refined:{lb.reason}",
                )
            )
    return _repair_monotonic_blocks(refined, len(zh_paragraphs), len(en_paragraphs))


def score_alignment_confidence(block: AlignmentBlock) -> float:
    zh_span = block.zh_end - block.zh_start + 1
    en_span = block.en_end - block.en_start + 1
    imbalance = abs(zh_span - en_span) / max(1, max(zh_span, en_span))
    if en_span == 1 and zh_span > 1 and float(block.confidence) >= 0.55:
        imbalance *= 0.35
    score = float(block.confidence) * 0.85 + (1.0 - imbalance) * 0.15
    return max(0.0, min(1.0, score))


def _even_zh_to_en_indices(zh_span: int, en_span: int) -> List[int]:
    """Within one block, assign each zh row a 0..en_span-1 index (then add block base).
    When zh_span >= en_span, split zh rows across en columns as evenly as possible
    (avoids round() bunching many zh onto the same en). When zh_span < en_span,
    keep endpoint interpolation so short zh still spans the en range."""
    if zh_span <= 0:
        return []
    if en_span <= 1:
        return [0] * zh_span
    if zh_span < en_span:
        return [
            int(round((i / max(1, zh_span - 1)) * (en_span - 1))) for i in range(zh_span)
        ]
    q, r = divmod(zh_span, en_span)
    out: List[int] = []
    for e in range(en_span):
        cnt = q + (1 if e < r else 0)
        out.extend([e] * cnt)
    return out


def flatten_map_from_blocks(blocks: Sequence[AlignmentBlock], zh_len: int, en_len: int) -> List[int]:
    if zh_len <= 0:
        return []
    mapping = [0] * zh_len
    for block in blocks:
        zh_span = max(1, block.zh_end - block.zh_start + 1)
        en_span = max(1, block.en_end - block.en_start + 1)
        base = block.en_start - 1
        local_en = _even_zh_to_en_indices(zh_span, en_span)
        for i in range(zh_span):
            en_idx = base + local_en[i]
            en_idx = max(0, min(en_len - 1, en_idx))
            zi = block.zh_start - 1 + i
            if 0 <= zi < zh_len:
                mapping[zi] = en_idx
    last = 0
    for i, val in enumerate(mapping):
        if val < last:
            mapping[i] = last
        else:
            last = val
    return mapping


def expand_en_ranges_from_blocks(
    blocks: Sequence[AlignmentBlock],
    zh_len: int,
    en_len: int,
) -> List[Tuple[int, int]]:
    if zh_len <= 0:
        return []
    ranges: List[Tuple[int, int]] = [(0, 0) for _ in range(zh_len)]
    for block in blocks:
        zh_span = max(1, block.zh_end - block.zh_start + 1)
        en_span = max(1, block.en_end - block.en_start + 1)
        base = max(0, min(en_len - 1, block.en_start - 1))
        if zh_span == 1:
            local_ranges = [(0, max(0, en_span - 1))]
        else:
            local_ranges = []
            for i in range(zh_span):
                start = int((i * en_span) // zh_span)
                end = int((((i + 1) * en_span) // zh_span) - 1)
                if end < start:
                    end = start
                local_ranges.append((start, end))
        for i, (start, end) in enumerate(local_ranges):
            zi = block.zh_start - 1 + i
            if not 0 <= zi < zh_len:
                continue
            en_start = max(0, min(en_len - 1, base + start))
            en_end = max(en_start, min(en_len - 1, base + end))
            ranges[zi] = (en_start, en_end)
    last_start = 0
    last_end = 0
    repaired: List[Tuple[int, int]] = []
    for start, end in ranges:
        if start < last_start:
            start = last_start
        if end < start:
            end = start
        if end < last_end and start == last_start:
            end = last_end
        repaired.append((start, end))
        last_start = start
        last_end = end
    return repaired


def build_review_items(blocks: Sequence[AlignmentBlock], chapter_index: int, threshold: float = 0.55) -> List[Dict[str, object]]:
    review_items: List[Dict[str, object]] = []
    for idx, block in enumerate(blocks):
        score = score_alignment_confidence(block)
        if score >= threshold:
            continue
        review_items.append(
            {
                "chapter_index": chapter_index,
                "block_index": idx,
                "zh_start": block.zh_start,
                "zh_end": block.zh_end,
                "en_start": block.en_start,
                "en_end": block.en_end,
                "confidence": round(score, 3),
                "reason": block.reason or "low_confidence",
            }
        )
    return review_items
