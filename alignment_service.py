from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from llm_client import ApiConfig, call_chat_json
from paragraph_alignment import (
    build_review_items,
    flatten_map_from_blocks,
    refine_large_blocks_llm,
    align_paragraphs_in_chapter_llm,
)
from utils import norm_space, safe_json_int


@dataclass
class ChapterPair:
    zh_index: int
    en_index: int
    confidence: float
    reason: str


def format_chapter_list_for_prompt(label: str, titles: Sequence[str]) -> str:
    lines = [f"{label} chapters ({len(titles)}):"]
    for i, title in enumerate(titles, start=1):
        lines.append(f"{i:04d}. {norm_space(title)}")
    return "\n".join(lines)


def map_chapters_ai(zh_titles: Sequence[str], en_titles: Sequence[str], config: ApiConfig) -> List[ChapterPair]:
    if not zh_titles or not en_titles:
        return []
    system_prompt = (
        "You align chapter titles for a Chinese–English translated book: the two lists describe the same "
        "work in translation. Map each Chinese chapter to the English chapter that is its translation "
        "counterpart (semantic / structural correspondence in the target language), not merely similar "
        "position or wording."
    )
    user_prompt = (
        "Task: translation-aware chapter alignment — pair each Chinese chapter with the English chapter "
        "that corresponds to it in the translated edition (by meaning and order in the book).\n"
        "Requirements:\n"
        "1) Output JSON only, no markdown.\n"
        "2) JSON schema: {\"pairs\":[{\"zh_index\":1,\"en_index\":1,\"confidence\":0.0,\"reason\":\"...\"}]}\n"
        "3) zh_index must cover ALL Chinese chapters exactly once, from 1..N.\n"
        "4) en_index must be non-decreasing as zh_index increases; never map a later Chinese chapter "
        "to an earlier English chapter (no backtracking).\n"
        "5) If unsure, still pick the best candidate and lower confidence.\n\n"
        f"{format_chapter_list_for_prompt('Chinese', zh_titles)}\n\n"
        f"{format_chapter_list_for_prompt('English', en_titles)}"
    )
    parsed = call_chat_json(config, system_prompt, user_prompt, debug_label="chapter_title_match")
    raw_pairs = parsed.get("pairs")
    if not isinstance(raw_pairs, list):
        raise RuntimeError("AI 返回格式错误：缺少 pairs 数组")

    mapped: List[ChapterPair] = []
    for item in raw_pairs:
        if not isinstance(item, dict):
            continue
        zh_idx = safe_json_int(item.get("zh_index"), 0)
        en_idx = safe_json_int(item.get("en_index"), 0)
        conf = float(item.get("confidence", 0.0))
        reason = str(item.get("reason", ""))
        if zh_idx >= 1 and en_idx >= 1:
            mapped.append(ChapterPair(zh_idx - 1, en_idx - 1, conf, reason))
    if not mapped:
        raise RuntimeError("AI 返回 pairs 为空")
    mapped.sort(key=lambda x: x.zh_index)

    by_zh = {p.zh_index: p for p in mapped}
    result: List[ChapterPair] = []
    last_en = 0
    for zh_i in range(len(zh_titles)):
        if zh_i in by_zh:
            p = by_zh[zh_i]
            en_i = max(last_en, min(p.en_index, len(en_titles) - 1))
            result.append(ChapterPair(zh_i, en_i, p.confidence, p.reason))
            last_en = en_i
        else:
            result.append(ChapterPair(zh_i, last_en, 0.2, "missing_from_ai_output_filled"))
    return result


def align_book_by_chapter_mapping(
    zh_paragraphs: Sequence[str],
    en_paragraphs: Sequence[str],
    zh_chapters: Sequence[Dict[str, int]],
    en_chapters: Sequence[Dict[str, int]],
    chapter_map: Sequence[int],
    config: ApiConfig,
) -> Dict[str, object]:
    if not zh_paragraphs:
        return {"sync_map": [], "chapter_results": [], "review_items": []}
    if not en_paragraphs:
        return {"sync_map": [0 for _ in zh_paragraphs], "chapter_results": [], "review_items": []}

    sync_map = [0 for _ in zh_paragraphs]
    chapter_results: List[Dict[str, object]] = []
    review_items: List[Dict[str, object]] = []

    total_chapters = min(len(zh_chapters), len(chapter_map))
    for c_idx, zh_ch in enumerate(zh_chapters):
        if c_idx >= len(chapter_map):
            break
        en_idx = chapter_map[c_idx]
        if en_idx < 0 or en_idx >= len(en_chapters):
            continue

        en_ch = en_chapters[en_idx]
        zh_start = safe_json_int(zh_ch.get("start"), 0)
        zh_end = safe_json_int(zh_ch.get("end"), 0)
        en_start = safe_json_int(en_ch.get("start"), 0)
        en_end = safe_json_int(en_ch.get("end"), 0)
        zh_title = norm_space(str(zh_ch.get("title", "")))
        en_title = norm_space(str(en_ch.get("title", "")))
        local_zh = zh_paragraphs[zh_start : zh_end + 1]
        local_en = en_paragraphs[en_start : en_end + 1]
        if not local_zh or not local_en:
            continue

        coarse = align_paragraphs_in_chapter_llm(
            local_zh,
            local_en,
            config,
            debug_label=f"book_chapter_{c_idx + 1}_coarse",
        )
        refined = refine_large_blocks_llm(
            coarse,
            local_zh,
            local_en,
            config,
            debug_label_prefix=f"book_chapter_{c_idx + 1}",
        )
        print(
            f"[align] chapter {c_idx + 1}/{total_chapters}: zh_title={zh_title or 'N/A'} "
            f"en_chapter={en_idx + 1} en_title={en_title or 'N/A'} "
            f"zh={len(local_zh)} en={len(local_en)} blocks={len(refined)}",
            flush=True,
        )
        local_map = flatten_map_from_blocks(refined, len(local_zh), len(local_en))
        for i, mapped_en_local in enumerate(local_map):
            sync_map[zh_start + i] = en_start + mapped_en_local

        blocks: List[Dict[str, object]] = []
        for block in refined:
            blocks.append(
                {
                    "zh_start": zh_start + block.zh_start - 1,
                    "zh_end": zh_start + block.zh_end - 1,
                    "en_start": en_start + block.en_start - 1,
                    "en_end": en_start + block.en_end - 1,
                    "confidence": round(float(block.confidence), 3),
                    "reason": block.reason,
                }
            )

        local_reviews = build_review_items(refined, c_idx)
        for item in local_reviews:
            item["zh_start"] = zh_start + safe_json_int(item.get("zh_start"), 1) - 1
            item["zh_end"] = zh_start + safe_json_int(item.get("zh_end"), 1) - 1
            item["en_start"] = en_start + safe_json_int(item.get("en_start"), 1) - 1
            item["en_end"] = en_start + safe_json_int(item.get("en_end"), 1) - 1
            review_items.append(item)

        chapter_results.append(
            {
                "chapter_index": c_idx,
                "mapped_en_chapter_index": en_idx,
                "blocks": blocks,
                "review_count": len(local_reviews),
            }
        )

    last = 0
    for i, value in enumerate(sync_map):
        if value < last:
            sync_map[i] = last
        else:
            last = value

    return {
        "sync_map": sync_map,
        "chapter_results": chapter_results,
        "review_items": review_items,
        "stats": {
            "chapter_count": len(chapter_results),
            "review_count": len(review_items),
        },
    }


def align_single_chapter(
    zh_paragraphs: Sequence[str],
    en_paragraphs: Sequence[str],
    zh_chapters: Sequence[Dict[str, int]],
    en_chapters: Sequence[Dict[str, int]],
    chapter_map: Sequence[int],
    chapter_index: int,
    config: ApiConfig,
) -> Dict[str, object]:
    if chapter_index < 0 or chapter_index >= len(zh_chapters):
        raise ValueError("chapter_index 超出范围")
    if chapter_index >= len(chapter_map):
        raise ValueError("chapter_map 缺少当前章节映射")
    en_idx = safe_json_int(chapter_map[chapter_index], -1)
    if en_idx < 0 or en_idx >= len(en_chapters):
        raise ValueError("当前章节映射到英文章节索引无效")

    zh_ch = zh_chapters[chapter_index]
    en_ch = en_chapters[en_idx]
    zh_start = safe_json_int(zh_ch.get("start"), 0)
    zh_end = safe_json_int(zh_ch.get("end"), 0)
    en_start = safe_json_int(en_ch.get("start"), 0)
    en_end = safe_json_int(en_ch.get("end"), 0)
    zh_title = norm_space(str(zh_ch.get("title", "")))
    en_title = norm_space(str(en_ch.get("title", "")))
    local_zh = zh_paragraphs[zh_start : zh_end + 1]
    local_en = en_paragraphs[en_start : en_end + 1]
    if not local_zh or not local_en:
        return {
            "chapter_index": chapter_index,
            "mapped_en_chapter_index": en_idx,
            "blocks": [],
            "local_sync_map": [],
            "review_items": [],
        }

    coarse = align_paragraphs_in_chapter_llm(
        local_zh,
        local_en,
        config,
        debug_label=f"single_chapter_{chapter_index + 1}_coarse",
    )
    refined = refine_large_blocks_llm(
        coarse,
        local_zh,
        local_en,
        config,
        debug_label_prefix=f"single_chapter_{chapter_index + 1}",
    )
    local_map = flatten_map_from_blocks(refined, len(local_zh), len(local_en))
    blocks: List[Dict[str, object]] = []
    for block in refined:
        blocks.append(
            {
                "zh_start": zh_start + block.zh_start - 1,
                "zh_end": zh_start + block.zh_end - 1,
                "en_start": en_start + block.en_start - 1,
                "en_end": en_start + block.en_end - 1,
                "confidence": round(float(block.confidence), 3),
                "reason": block.reason,
            }
        )
    review_items = build_review_items(refined, chapter_index)
    for item in review_items:
        item["zh_start"] = zh_start + safe_json_int(item.get("zh_start"), 1) - 1
        item["zh_end"] = zh_start + safe_json_int(item.get("zh_end"), 1) - 1
        item["en_start"] = en_start + safe_json_int(item.get("en_start"), 1) - 1
        item["en_end"] = en_start + safe_json_int(item.get("en_end"), 1) - 1

    print(
        f"[align] single chapter {chapter_index + 1}: zh_title={zh_title or 'N/A'} "
        f"en_chapter={en_idx + 1} en_title={en_title or 'N/A'} "
        f"zh={len(local_zh)} en={len(local_en)} blocks={len(refined)}",
        flush=True,
    )
    return {
        "chapter_index": chapter_index,
        "mapped_en_chapter_index": en_idx,
        "blocks": blocks,
        "local_sync_map": [en_start + v for v in local_map],
        "review_items": review_items,
        "zh_range": {"start": zh_start, "end": zh_end},
        "en_range": {"start": en_start, "end": en_end},
    }
