from __future__ import annotations

import json
from pathlib import Path
import zipfile

from epub_parser import extract_epub_document_from_bytes
from tools.pdf_to_epub_ocr import ChapterDraft, convert_pdf_to_epub, write_preview


def _simple_text_pdf(text: str) -> bytes:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1", errors="ignore")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode("ascii")
    output += f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    return bytes(output)


def test_pdf_to_epub_generates_parser_friendly_epub(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    out_path = tmp_path / "sample.epub"
    work_dir = tmp_path / "work"
    pdf_path.write_bytes(_simple_text_pdf("Chapter 1. Hello world. This is a parser friendly text PDF."))

    result = convert_pdf_to_epub(
        pdf_path,
        out_path=out_path,
        work_dir=work_dir,
        language="en",
        title="Sample Book",
        max_pages=1,
        ocr_lang="eng",
    )

    assert result.epub_path == out_path.resolve()
    assert out_path.exists()
    with zipfile.ZipFile(out_path) as zf:
        assert zf.namelist()[0] == "mimetype"
        assert "META-INF/container.xml" in zf.namelist()
        assert "OEBPS/content.opf" in zf.namelist()
        assert "OEBPS/nav.xhtml" in zf.namelist()
        assert "OEBPS/toc.ncx" in zf.namelist()
        assert "OEBPS/chapters/chapter_001.xhtml" in zf.namelist()

    paragraphs, chapters = extract_epub_document_from_bytes(out_path.read_bytes())
    assert chapters
    assert paragraphs
    assert "Hello world" in " ".join(paragraphs)
    assert result.report["validated_chapter_count"] == len(chapters)
    assert result.report["validated_paragraph_count"] == len(paragraphs)
    assert (work_dir / "preview.md").exists()
    assert (work_dir / "parse_report.json").exists()


def test_pdf_to_epub_resume_reuses_page_cache(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    out_path = tmp_path / "sample.epub"
    work_dir = tmp_path / "work"
    pdf_path.write_bytes(_simple_text_pdf("Chapter 1. Resume should reuse this text layer page."))

    convert_pdf_to_epub(
        pdf_path,
        out_path=out_path,
        work_dir=work_dir,
        language="en",
        title="Resume Book",
        max_pages=1,
        ocr_lang="eng",
    )
    cache_path = work_dir / "ocr_pages.jsonl"
    first_cache = cache_path.read_text(encoding="utf-8")

    convert_pdf_to_epub(
        pdf_path,
        out_path=out_path,
        work_dir=work_dir,
        language="en",
        title="Resume Book",
        max_pages=1,
        ocr_lang="eng",
    )
    second_cache = cache_path.read_text(encoding="utf-8")

    assert second_cache == first_cache
    assert len([line for line in second_cache.splitlines() if line.strip()]) == 1
    record = json.loads(second_cache)
    assert record["source"] == "text_layer"


def test_preview_drops_invalid_ocr_unicode(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.md"
    report = {
        "title": "OCR Surrogate",
        "page_count": 1,
        "chapter_count": 1,
        "paragraph_count": 1,
        "text_layer_pages": 0,
        "ocr_pages": 1,
        "failed_pages": 0,
        "warnings": ["bad\udc00warning"],
    }
    chapters = [ChapterDraft(title="Chapter\udc00", page_start=1, page_end=1, paragraphs=["Hello\udc00 world"])]

    write_preview(preview_path, report=report, chapters=chapters)

    text = preview_path.read_text(encoding="utf-8")
    assert "\udc00" not in text
    assert "Hello world" in text
