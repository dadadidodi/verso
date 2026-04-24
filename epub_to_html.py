#!/usr/bin/env python3
"""将 EPUB spine 中的 XHTML 正文合并为单个 HTML 文件（UTF-8），复用 chapter_catalog 的解析逻辑。"""
from __future__ import annotations

import argparse
import html
import re
import sys
import zipfile
from pathlib import Path

from alignment_common import norm_space
from chapter_catalog import iter_spine_html_parts

_BODY = re.compile(r"<body[^>]*>([\s\S]*)</body>", re.I)


def _body_inner(xhtml: str) -> str:
    m = _BODY.search(xhtml)
    if m:
        return m.group(1).strip()
    return xhtml.strip()


def epub_to_html(
    epub_path: Path,
    *,
    chapter_headings: bool = True,
    document_title: str | None = None,
) -> str:
    sections: list[str] = []
    first_title: str | None = None
    with zipfile.ZipFile(epub_path, "r") as zf:
        for content_path, html_text, title in iter_spine_html_parts(zf):
            inner = _body_inner(html_text)
            if not inner:
                continue
            safe_title = html.escape(norm_space(title.replace("\n", " ")))
            if first_title is None:
                first_title = safe_title
            href_attr = html.escape(content_path, quote=True)
            if chapter_headings:
                sections.append(
                    f'<section class="epub-spine" data-epub-href="{href_attr}">\n'
                    f'<h2 class="epub-chapter-title">{safe_title}</h2>\n'
                    f'<div class="epub-chapter-body">\n{inner}\n</div>\n</section>'
                )
            else:
                sections.append(
                    f'<section class="epub-spine" data-epub-href="{href_attr}">\n'
                    f'<div class="epub-chapter-body">\n{inner}\n</div>\n</section>'
                )

    if not sections:
        return ""

    if document_title:
        title_tag = html.escape(document_title)
    elif first_title:
        title_tag = first_title
    else:
        title_tag = "EPUB"
    merged = '\n<hr class="epub-spine-sep" />\n'.join(sections)
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title_tag}</title>
<style>
body {{ font-family: system-ui, sans-serif; line-height: 1.5; max-width: 40rem; margin: 1rem auto; padding: 0 1rem; }}
.epub-chapter-title {{ font-size: 1.25rem; margin-top: 2rem; }}
.epub-spine-sep {{ border: none; border-top: 1px solid #ccc; margin: 2rem 0; }}
</style>
</head>
<body>
{merged}
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="EPUB → 单个 HTML 文件")
    parser.add_argument("epub", type=Path, help="输入 .epub 路径")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出 .html（默认与 epub 同主文件名）",
    )
    parser.add_argument(
        "--no-chapter-headings",
        action="store_true",
        help="不插入 spine 文件的目录标题（h2）",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="HTML 文档标题（默认用第一章目录名）",
    )
    args = parser.parse_args()
    epub = args.epub.resolve()
    if not epub.is_file():
        print(f"找不到文件: {epub}", file=sys.stderr)
        return 1
    out = (args.output or epub.with_suffix(".html")).resolve()
    try:
        text = epub_to_html(
            epub,
            chapter_headings=not args.no_chapter_headings,
            document_title=args.title,
        )
    except Exception as e:
        print(f"转换失败: {e}", file=sys.stderr)
        return 1
    if not text.strip():
        print("未提取到正文。", file=sys.stderr)
        return 1
    out.write_text(text, encoding="utf-8")
    print(f"已写入: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
