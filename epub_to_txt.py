#!/usr/bin/env python3
"""将 EPUB 正文导出为 UTF-8 纯文本。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chapter_catalog import extract_epub_document


def main() -> int:
    parser = argparse.ArgumentParser(description="EPUB → UTF-8 TXT")
    parser.add_argument("epub", type=Path, help="输入 .epub 路径")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出 .txt（默认与 epub 同目录、同主文件名）",
    )
    parser.add_argument(
        "--chapter-headings",
        action="store_true",
        help="在每一章前插入目录标题行",
    )
    args = parser.parse_args()
    epub = args.epub.resolve()
    if not epub.is_file():
        print(f"找不到文件: {epub}", file=sys.stderr)
        return 1
    out = (args.output or epub.with_suffix(".txt")).resolve()
    try:
        paragraphs, chapters = extract_epub_document(str(epub))
    except Exception as e:
        print(f"解析失败: {e}", file=sys.stderr)
        return 1
    if not paragraphs:
        print("未提取到正文。", file=sys.stderr)
        return 1

    if args.chapter_headings and chapters:
        blocks: list[str] = []
        for ch in chapters:
            body = "\n\n".join(paragraphs[ch.start : ch.end + 1])
            blocks.append(f"{ch.title}\n\n{body}")
        text = "\n\n\n".join(blocks)
    else:
        text = "\n\n".join(paragraphs)

    out.write_text(text, encoding="utf-8")
    print(f"已写入: {out}（约 {len(paragraphs)} 段）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
