#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from alignment_common import get_api_config, norm_space
from alignment_service import align_book_by_chapter_mapping, map_chapters_ai
from chapter_catalog import extract_epub_document


def build_paragraph_result_text(sync_map: List[int], review_items: List[dict]) -> str:
    lines: List[str] = []
    lines.append("# Paragraph Align Result")
    lines.append(f"sync_count={len(sync_map)}")
    lines.append(f"review_count={len(review_items)}")
    lines.append("sync_map:")
    lines.extend(str(v) for v in sync_map)
    lines.append("review_items:")
    for item in review_items:
        lines.append(
            f"chapter={int(item['chapter_index']) + 1}|zh={int(item['zh_start']) + 1}-{int(item['zh_end']) + 1}|"
            f"en={int(item['en_start']) + 1}-{int(item['en_end']) + 1}|conf={float(item['confidence']):.3f}|"
            f"reason={norm_space(str(item.get('reason', '')))}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="段落对齐调试导出")
    parser.add_argument("--zh", required=True, help="中文 EPUB 路径")
    parser.add_argument("--en", required=True, help="英文 EPUB 路径")
    parser.add_argument("--result-out", default="paragraph_result.txt")
    args = parser.parse_args()

    zh_paragraphs, zh_chapters = extract_epub_document(args.zh)
    en_paragraphs, en_chapters = extract_epub_document(args.en)
    config = get_api_config()
    chapter_pairs = map_chapters_ai([c.title for c in zh_chapters], [c.title for c in en_chapters], config)
    chapter_map = [p.en_index for p in chapter_pairs]

    result = align_book_by_chapter_mapping(
        zh_paragraphs=zh_paragraphs,
        en_paragraphs=en_paragraphs,
        zh_chapters=[{"title": c.title, "start": c.start, "end": c.end} for c in zh_chapters],
        en_chapters=[{"title": c.title, "start": c.start, "end": c.end} for c in en_chapters],
        chapter_map=chapter_map,
        config=config,
    )
    text = build_paragraph_result_text(result["sync_map"], result["review_items"])
    Path(args.result_out).write_text(text, encoding="utf-8")
    print(f"已写入段落对齐结果：{args.result_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
