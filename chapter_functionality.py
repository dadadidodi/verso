from __future__ import annotations

from typing import Sequence, Tuple

from alignment_common import ApiConfig, get_api_config, load_env_file, norm_space
from chapter_catalog import Chapter, ChapterSegment, extract_chapters, extract_epub_document, extract_epub_document_from_bytes
from alignment_service import format_chapter_list_for_prompt, map_chapters_ai


def call_ai_for_chapter_mapping_from_titles(
    zh_titles: Sequence[str],
    en_titles: Sequence[str],
    config: ApiConfig,
) -> list[tuple[int, int, float, str]]:
    pairs = map_chapters_ai(zh_titles, en_titles, config)
    return [(p.zh_index, p.en_index, p.confidence, p.reason) for p in pairs]


def call_ai_for_chapter_mapping(
    zh_chapters: Sequence[Chapter],
    en_chapters: Sequence[Chapter],
    config: ApiConfig,
) -> list[tuple[int, int, float, str]]:
    return call_ai_for_chapter_mapping_from_titles(
        [norm_space(ch.title) for ch in zh_chapters],
        [norm_space(ch.title) for ch in en_chapters],
        config,
    )


__all__ = [
    "ApiConfig",
    "Chapter",
    "ChapterSegment",
    "extract_chapters",
    "extract_epub_document",
    "extract_epub_document_from_bytes",
    "load_env_file",
    "get_api_config",
    "norm_space",
    "format_chapter_list_for_prompt",
    "call_ai_for_chapter_mapping_from_titles",
    "call_ai_for_chapter_mapping",
]
