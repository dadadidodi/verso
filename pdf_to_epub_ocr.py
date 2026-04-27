#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from alignment_common import norm_space
from chapter_catalog import extract_epub_document_from_bytes
from document_parser import _looks_like_heading, _read_tesseract_languages, _split_pdf_paragraphs, _text_quality_ok


TOOL_VERSION = "pdf_to_epub_ocr_v1"


@dataclass
class PageRecord:
    page_number: int
    source: str
    text: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class ChapterDraft:
    title: str
    page_start: int
    page_end: int
    paragraphs: List[str]


@dataclass
class ConversionResult:
    epub_path: Path
    work_dir: Path
    report: Dict[str, Any]


def convert_pdf_to_epub(
    pdf_path: Path,
    *,
    out_path: Path,
    work_dir: Path,
    language: str,
    title: str = "",
    author: str = "",
    ocr_lang: str = "",
    scale: float = 1.0,
    max_pages: Optional[int] = None,
    resume: bool = True,
    force: bool = False,
) -> ConversionResult:
    """Convert a PDF into a parser-friendly EPUB using cached text/OCR page records."""

    pdf_path = pdf_path.expanduser().resolve()
    out_path = out_path.expanduser().resolve()
    work_dir = work_dir.expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError("input file must be a PDF")
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    page_records, toc, metadata, extraction_warnings = extract_pdf_page_records(
        pdf_path,
        work_dir=work_dir,
        language=language,
        ocr_lang=ocr_lang,
        scale=scale,
        max_pages=max_pages,
        resume=resume,
        force=force,
    )
    if not page_records:
        raise ValueError("no pages were extracted from the PDF")

    book_title = title or norm_space(str(metadata.get("title") or "")) or pdf_path.stem
    book_author = author or norm_space(str(metadata.get("author") or ""))
    chapters = build_chapters_from_pages(page_records, toc=toc, max_pages=max_pages)
    if not any(chapter.paragraphs for chapter in chapters):
        raise ValueError("no readable paragraphs were extracted from the PDF")

    write_epub(out_path, title=book_title, author=book_author, language=language, chapters=chapters)
    parsed_paragraphs, parsed_chapters = extract_epub_document_from_bytes(out_path.read_bytes())
    report = {
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_pdf": str(pdf_path),
        "output_epub": str(out_path),
        "work_dir": str(work_dir),
        "title": book_title,
        "author": book_author,
        "language": language,
        "page_count": len(page_records),
        "text_layer_pages": sum(1 for item in page_records if item.source == "text_layer"),
        "ocr_pages": sum(1 for item in page_records if item.source == "ocr"),
        "failed_pages": sum(1 for item in page_records if item.source == "failed"),
        "toc_entries": len(toc),
        "chapter_count": len(chapters),
        "paragraph_count": sum(len(chapter.paragraphs) for chapter in chapters),
        "validated_chapter_count": len(parsed_chapters),
        "validated_paragraph_count": len(parsed_paragraphs),
        "warnings": extraction_warnings + [warning for item in page_records for warning in item.warnings],
        "chapters": [
            {
                "title": chapter.title,
                "page_start": chapter.page_start,
                "page_end": chapter.page_end,
                "paragraph_count": len(chapter.paragraphs),
            }
            for chapter in chapters
        ],
    }
    report = clean_json_value(report)
    (work_dir / "parse_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_preview(work_dir / "preview.md", report=report, chapters=chapters)
    return ConversionResult(epub_path=out_path, work_dir=work_dir, report=report)


def extract_pdf_page_records(
    pdf_path: Path,
    *,
    work_dir: Path,
    language: str,
    ocr_lang: str,
    scale: float,
    max_pages: Optional[int],
    resume: bool,
    force: bool,
) -> Tuple[List[PageRecord], List[List[Any]], Dict[str, Any], List[str]]:
    try:
        import fitz  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyMuPDF is required for pdf_to_epub_ocr.py; install requirements-dev.txt") from exc

    cache_path = work_dir / "ocr_pages.jsonl"
    if force and cache_path.exists():
        cache_path.unlink()
    cached = read_page_cache(cache_path) if resume and not force else {}
    warnings: List[str] = []
    selected_ocr_lang = ocr_lang.strip()
    if not selected_ocr_lang:
        selected_ocr_lang, lang_warnings = _read_tesseract_languages(language)
        warnings.extend(lang_warnings)
    elif shutil.which("tesseract") is None:
        warnings.append("tesseract binary not found; OCR pages will be marked failed")
        selected_ocr_lang = ""

    records: List[PageRecord] = []
    with fitz.open(pdf_path) as doc:
        total_pages = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
        toc = [item for item in doc.get_toc(simple=True) if len(item) >= 3 and int(item[2]) <= total_pages]
        metadata = dict(doc.metadata or {})
        for zero_based in range(total_pages):
            page_number = zero_based + 1
            if page_number in cached:
                records.append(cached[page_number])
                continue
            page = doc.load_page(zero_based)
            record = extract_single_page(page, page_number=page_number, ocr_lang=selected_ocr_lang, scale=scale)
            append_page_cache(cache_path, record)
            records.append(record)
    return records, toc, metadata, warnings


def extract_single_page(page: Any, *, page_number: int, ocr_lang: str, scale: float) -> PageRecord:
    text = page.get_text("text") or ""
    text = clean_unicode(text)
    if _text_quality_ok(text):
        return PageRecord(page_number=page_number, source="text_layer", text=text)
    if not ocr_lang:
        return PageRecord(
            page_number=page_number,
            source="failed",
            text=text,
            warnings=[f"page {page_number} has little readable text and OCR is unavailable"],
        )
    try:
        import fitz  # type: ignore
        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.open(BytesIO(pix.tobytes("png")))
        ocr_text = clean_unicode(pytesseract.image_to_string(image, lang=ocr_lang))
        if norm_space(ocr_text):
            return PageRecord(page_number=page_number, source="ocr", text=ocr_text)
        return PageRecord(page_number=page_number, source="failed", text=text, warnings=[f"OCR returned empty text on page {page_number}"])
    except Exception as exc:  # pragma: no cover - OCR stack is local-environment-sensitive
        return PageRecord(page_number=page_number, source="failed", text=text, warnings=[f"OCR failed on page {page_number}: {exc}"])


def read_page_cache(cache_path: Path) -> Dict[int, PageRecord]:
    if not cache_path.exists():
        return {}
    records: Dict[int, PageRecord] = {}
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        page_number = int(payload["page_number"])
        records[page_number] = PageRecord(
            page_number=page_number,
            source=str(payload.get("source") or "failed"),
            text=clean_unicode(str(payload.get("text") or "")),
            warnings=[str(item) for item in payload.get("warnings", [])],
        )
    return records


def append_page_cache(cache_path: Path, record: PageRecord) -> None:
    payload = {
        "page_number": record.page_number,
        "source": record.source,
        "text": clean_unicode(record.text),
        "warnings": record.warnings,
    }
    with cache_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_chapters_from_pages(
    page_records: List[PageRecord],
    *,
    toc: List[List[Any]],
    max_pages: Optional[int],
) -> List[ChapterDraft]:
    page_paragraphs = {record.page_number: _split_pdf_paragraphs(record.text) for record in page_records}
    max_page = page_records[-1].page_number
    if toc:
        chapters: List[ChapterDraft] = []
        entries = normalize_toc_entries(toc, max_page=max_page)
        for index, entry in enumerate(entries):
            page_start = entry["page"]
            next_page = entries[index + 1]["page"] if index + 1 < len(entries) else max_page + 1
            page_end = max(page_start, min(max_page, next_page - 1))
            paragraphs = paragraphs_for_page_range(page_paragraphs, page_start, page_end)
            if paragraphs:
                chapters.append(ChapterDraft(title=entry["title"], page_start=page_start, page_end=page_end, paragraphs=paragraphs))
        if chapters:
            return chapters
    return build_fallback_chapters(page_records, page_paragraphs=page_paragraphs, max_pages=max_pages)


def normalize_toc_entries(toc: List[List[Any]], *, max_page: int) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    seen: set[Tuple[int, str]] = set()
    for item in toc:
        page = int(item[2])
        title = norm_space(str(item[1])) or f"Chapter {len(entries) + 1}"
        if page < 1 or page > max_page:
            continue
        key = (page, title)
        if key in seen:
            continue
        seen.add(key)
        entries.append({"level": int(item[0]), "title": title, "page": page})
    entries.sort(key=lambda item: (item["page"], item["level"], item["title"]))
    return entries


def paragraphs_for_page_range(page_paragraphs: Dict[int, List[str]], page_start: int, page_end: int) -> List[str]:
    paragraphs: List[str] = []
    for page_number in range(page_start, page_end + 1):
        paragraphs.extend(page_paragraphs.get(page_number, []))
    return paragraphs


def build_fallback_chapters(
    page_records: List[PageRecord],
    *,
    page_paragraphs: Dict[int, List[str]],
    max_pages: Optional[int],
) -> List[ChapterDraft]:
    flat: List[Tuple[int, str]] = []
    for record in page_records:
        for paragraph in page_paragraphs.get(record.page_number, []):
            flat.append((record.page_number, paragraph))
    if not flat:
        return []
    heading_positions = [idx for idx, (_, paragraph) in enumerate(flat) if _looks_like_heading(paragraph)]
    if heading_positions:
        if heading_positions[0] != 0:
            heading_positions.insert(0, 0)
        chapters: List[ChapterDraft] = []
        for pos, start in enumerate(heading_positions):
            end = heading_positions[pos + 1] - 1 if pos + 1 < len(heading_positions) else len(flat) - 1
            page_start = flat[start][0]
            page_end = flat[end][0]
            raw_title = flat[start][1] if _looks_like_heading(flat[start][1]) else f"PDF Section {pos + 1}"
            paragraphs = [paragraph for _, paragraph in flat[start : end + 1]]
            chapters.append(ChapterDraft(title=raw_title, page_start=page_start, page_end=page_end, paragraphs=paragraphs))
        return chapters
    page_start = page_records[0].page_number
    page_end = page_records[-1].page_number if max_pages is None else min(max_pages, page_records[-1].page_number)
    return [ChapterDraft(title="全文", page_start=page_start, page_end=page_end, paragraphs=[paragraph for _, paragraph in flat])]


def write_epub(out_path: Path, *, title: str, author: str, language: str, chapters: List[ChapterDraft]) -> None:
    identifier = f"urn:uuid:{uuid.uuid4()}"
    chapter_files = [f"chapters/chapter_{index:03d}.xhtml" for index in range(1, len(chapters) + 1)]
    with zipfile.ZipFile(out_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml(), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", content_opf(title, author, language, identifier, chapter_files), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml(title, chapters, chapter_files), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/toc.ncx", toc_ncx(title, identifier, chapters, chapter_files), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/styles/book.css", book_css(), compress_type=zipfile.ZIP_DEFLATED)
        for chapter, filename in zip(chapters, chapter_files):
            zf.writestr(f"OEBPS/{filename}", chapter_xhtml(chapter), compress_type=zipfile.ZIP_DEFLATED)


def container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def content_opf(title: str, author: str, language: str, identifier: str, chapter_files: List[str]) -> str:
    author_node = f"\n    <dc:creator>{xml_escape(author)}</dc:creator>" if author else ""
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="styles/book.css" media-type="text/css"/>',
    ]
    spine_items = []
    for index, filename in enumerate(chapter_files, start=1):
        manifest_items.append(f'<item id="chapter{index}" href="{filename}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="chapter{index}"/>')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{xml_escape(identifier)}</dc:identifier>
    <dc:title>{xml_escape(title)}</dc:title>{author_node}
    <dc:language>{xml_escape(language or "und")}</dc:language>
    <meta property="dcterms:modified">{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>
    <meta name="generator" content="{TOOL_VERSION}"/>
  </metadata>
  <manifest>
    {chr(10).join(manifest_items)}
  </manifest>
  <spine toc="ncx">
    {chr(10).join(spine_items)}
  </spine>
</package>
"""


def nav_xhtml(title: str, chapters: List[ChapterDraft], chapter_files: List[str]) -> str:
    items = "\n".join(
        f'      <li><a href="{xml_escape(filename)}">{xml_escape(chapter.title)}</a></li>'
        for chapter, filename in zip(chapters, chapter_files)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="und">
<head>
  <title>{xml_escape(title)}</title>
  <meta charset="utf-8"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>{xml_escape(title)}</h1>
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""


def toc_ncx(title: str, identifier: str, chapters: List[ChapterDraft], chapter_files: List[str]) -> str:
    points = "\n".join(
        f"""    <navPoint id="navPoint-{index}" playOrder="{index}">
      <navLabel><text>{xml_escape(chapter.title)}</text></navLabel>
      <content src="{xml_escape(filename)}"/>
    </navPoint>"""
        for index, (chapter, filename) in enumerate(zip(chapters, chapter_files), start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{xml_escape(identifier)}"/>
  </head>
  <docTitle><text>{xml_escape(title)}</text></docTitle>
  <navMap>
{points}
  </navMap>
</ncx>
"""


def chapter_xhtml(chapter: ChapterDraft) -> str:
    paragraphs = "\n".join(f"    <p>{xml_escape(paragraph)}</p>" for paragraph in chapter.paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="und">
<head>
  <title>{xml_escape(chapter.title)}</title>
  <meta charset="utf-8"/>
  <link rel="stylesheet" type="text/css" href="../styles/book.css"/>
</head>
<body>
  <section>
    <h1>{xml_escape(chapter.title)}</h1>
{paragraphs}
  </section>
</body>
</html>
"""


def book_css() -> str:
    return """body {
  font-family: serif;
  line-height: 1.65;
  margin: 1.5em;
}
h1 {
  font-size: 1.5em;
  margin: 1em 0;
}
p {
  margin: 0 0 0.85em;
}
"""


def xml_escape(value: str) -> str:
    return html.escape(clean_unicode(str(value)), quote=True)


def clean_unicode(value: str) -> str:
    """Drop invalid Unicode code points that OCR engines occasionally emit."""

    return value.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def clean_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return clean_unicode(value)
    if isinstance(value, list):
        return [clean_json_value(item) for item in value]
    if isinstance(value, dict):
        return {clean_unicode(str(key)): clean_json_value(item) for key, item in value.items()}
    return value


def write_preview(path: Path, *, report: Dict[str, Any], chapters: List[ChapterDraft]) -> None:
    lines = [
        f"# {report['title']}",
        "",
        f"- pages: {report['page_count']}",
        f"- chapters: {report['chapter_count']}",
        f"- paragraphs: {report['paragraph_count']}",
        f"- text layer pages: {report['text_layer_pages']}",
        f"- OCR pages: {report['ocr_pages']}",
        f"- failed pages: {report['failed_pages']}",
        "",
        "## Chapters",
        "",
    ]
    for index, chapter in enumerate(chapters, start=1):
        title = clean_unicode(chapter.title)
        sample = clean_unicode(norm_space(" ".join(chapter.paragraphs[:2])))
        if len(sample) > 180:
            sample = sample[:180] + "..."
        lines.extend(
            [
                f"### {index}. {title}",
                "",
                f"- pages: {chapter.page_start}-{chapter.page_end}",
                f"- paragraphs: {len(chapter.paragraphs)}",
                "",
                sample,
                "",
            ]
        )
    warnings = report.get("warnings") or []
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {clean_unicode(str(item))}" for item in warnings[:80])
        if len(warnings) > 80:
            lines.append(f"- ... {len(warnings) - 80} more")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a text/scanned PDF into a DuReading-friendly EPUB.")
    parser.add_argument("pdf", type=Path, help="Input PDF path.")
    parser.add_argument("--out", type=Path, required=True, help="Output EPUB path.")
    parser.add_argument("--work-dir", type=Path, required=True, help="Directory for OCR cache and reports.")
    parser.add_argument("--language", default="zh", help="Book language metadata, e.g. zh or en.")
    parser.add_argument("--title", default="", help="Book title. Defaults to PDF metadata or filename.")
    parser.add_argument("--author", default="", help="Book author. Defaults to PDF metadata.")
    parser.add_argument("--ocr-lang", default="", help="Tesseract language string. Defaults by --language.")
    parser.add_argument("--scale", type=positive_float, default=1.0, help="PDF render scale for OCR pages.")
    parser.add_argument("--max-pages", type=positive_int, default=None, help="Only convert the first N pages.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing page cache without deleting it.")
    parser.add_argument("--force", action="store_true", help="Delete cache and re-extract all selected pages.")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = convert_pdf_to_epub(
            args.pdf,
            out_path=args.out,
            work_dir=args.work_dir,
            language=args.language,
            title=args.title,
            author=args.author,
            ocr_lang=args.ocr_lang,
            scale=args.scale,
            max_pages=args.max_pages,
            resume=not args.no_resume,
            force=args.force,
        )
    except Exception as exc:
        print(f"pdf_to_epub_ocr failed: {exc}", file=sys.stderr)
        return 1
    report = result.report
    print(
        "\n".join(
            [
                f"Wrote EPUB: {result.epub_path}",
                f"Work dir: {result.work_dir}",
                f"Chapters: {report['chapter_count']} · paragraphs: {report['paragraph_count']} · pages: {report['page_count']}",
                f"Text layer pages: {report['text_layer_pages']} · OCR pages: {report['ocr_pages']} · failed pages: {report['failed_pages']}",
                f"Preview: {result.work_dir / 'preview.md'}",
                f"Report: {result.work_dir / 'parse_report.json'}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
