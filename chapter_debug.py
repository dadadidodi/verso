#!/usr/bin/env python3
"""EPUB chapter extraction and local comparison debug tool.

Usage:
  python3 chapter_debug.py --epub book.epub
  python3 chapter_debug.py --zh zh.epub --en en.epub
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

from alignment_common import get_api_config, norm_space
from alignment_service import map_chapters_ai
from chapter_catalog import Chapter, extract_chapters


def print_chapters(label: str, chapters: List[Chapter]) -> None:
    print(f"\n=== {label} 章节 ({len(chapters)}) ===")
    for i, ch in enumerate(chapters, start=1):
        print(f"{i:04d}. {ch.title}  [{ch.path}]")


def build_result_text(
    zh_chapters: List[Chapter],
    en_chapters: List[Chapter],
    pairs: List[Tuple[int, int, float, str]],
) -> str:
    lines: List[str] = []
    lines.append("# Chapter Match Result")
    lines.append(f"zh_count={len(zh_chapters)}")
    lines.append(f"en_count={len(en_chapters)}")
    lines.append("pairs:")
    for z, e, score, reason in pairs:
        zh_title = norm_space(zh_chapters[z].title) if 0 <= z < len(zh_chapters) else ""
        en_title = norm_space(en_chapters[e].title) if 0 <= e < len(en_chapters) else ""
        safe_reason = norm_space(reason)
        lines.append(
            f"zh={z + 1:04d}|en={e + 1:04d}|conf={score:.3f}|zh_title={zh_title}|en_title={en_title}|reason={safe_reason}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="EPUB 章节提取/比对本地调试工具")
    parser.add_argument("--epub", help="单文件测试：只提取这本书章节")
    parser.add_argument("--zh", help="中文 EPUB 路径")
    parser.add_argument("--en", help="英文 EPUB 路径")
    parser.add_argument(
        "--api-base-url",
        default="",
        help="AI API base URL (default from OPENAI_API_BASE_URL/.env)",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="AI API key (default from OPENAI_API_KEY/.env)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Chat model (default from OPENAI_MODEL/.env)",
    )
    parser.add_argument(
        "--result-out",
        default="result.txt",
        help="match 结果写入文件路径（默认 result.txt）",
    )
    args = parser.parse_args()

    if args.epub:
        chapters = extract_chapters(args.epub)
        print_chapters("单文件", chapters)
        return 0

    if args.zh and args.en:
        zh_chapters = extract_chapters(args.zh)
        en_chapters = extract_chapters(args.en)
        print_chapters("中文", zh_chapters)
        print_chapters("英文", en_chapters)

        config = get_api_config(
            api_base_url=args.api_base_url or None,
            api_key=args.api_key or None,
            model=args.model or None,
        )
        pairs = map_chapters_ai(
            [c.title for c in zh_chapters],
            [c.title for c in en_chapters],
            config,
        )
        print("\n=== AI 章节对应建议（可人工核对）===")
        tuple_pairs: List[Tuple[int, int, float, str]] = []
        for pair in pairs:
            z, e, score, reason = pair.zh_index, pair.en_index, pair.confidence, pair.reason
            tuple_pairs.append((z, e, score, reason))
            print(
                f"中{z + 1:04d} -> 英{e + 1:04d}  conf={score:.3f}  "
                f"| {zh_chapters[z].title} => {en_chapters[e].title}\n"
                f"  reason: {reason}"
            )
        result_text = build_result_text(zh_chapters, en_chapters, tuple_pairs)
        Path(args.result_out).write_text(result_text, encoding="utf-8")
        print(f"\n已写入匹配结果：{args.result_out}")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pylint: disable=broad-except
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
