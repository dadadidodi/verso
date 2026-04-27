from __future__ import annotations

import io
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from alignment_common import norm_space
from chapter_catalog import ChapterSegment, PARSER_VERSION as EPUB_PARSER_VERSION, extract_epub_document_from_bytes


PDF_PARSER_VERSION = "pdf_text_ocr_v1"
SUPPORTED_SOURCE_FORMATS = {"epub"}


@dataclass
class DocumentParseResult:
    source_format: str
    parser_version: str
    paragraphs: List[str]
    chapters: List[ChapterSegment]
    parse_warnings: List[str] = field(default_factory=list)
    quality_stats: Dict[str, Any] = field(default_factory=dict)


def detect_source_format(filename: str, content_type: str = "") -> str:
    suffix = Path(filename or "").suffix.lower()
    mime = (content_type or "").split(";")[0].strip().lower()
    if suffix == ".epub" or mime in {"application/epub+zip", "application/x-epub+zip"}:
        return "epub"
    raise ValueError("unsupported book format; upload EPUB only")


def parser_version_for_format(source_format: str) -> str:
    if source_format == "epub":
        return f"epub:{EPUB_PARSER_VERSION}"
    if source_format == "pdf":
        return f"pdf:{PDF_PARSER_VERSION}"
    raise ValueError(f"unsupported source format: {source_format}")


def source_filename_for_format(source_format: str) -> str:
    if source_format == "epub":
        return "source.epub"
    if source_format == "pdf":
        return "source.pdf"
    raise ValueError(f"unsupported source format: {source_format}")


def chapter_to_dict(chapter: ChapterSegment) -> Dict[str, Any]:
    return {"title": chapter.title, "path": chapter.path, "start": chapter.start, "end": chapter.end}


def chapter_from_dict(payload: Dict[str, Any]) -> ChapterSegment:
    return ChapterSegment(
        title=str(payload.get("title") or ""),
        path=str(payload.get("path") or ""),
        start=int(payload.get("start", 0)),
        end=int(payload.get("end", 0)),
    )


def extract_document_from_bytes(
    data: bytes,
    *,
    filename: str,
    content_type: str = "",
    language: str = "",
) -> DocumentParseResult:
    source_format = detect_source_format(filename, content_type)
    if source_format == "epub":
        paragraphs, chapters = extract_epub_document_from_bytes(data)
        return DocumentParseResult(
            source_format="epub",
            parser_version=parser_version_for_format("epub"),
            paragraphs=paragraphs,
            chapters=chapters,
            parse_warnings=[],
            quality_stats={
                "source_format": "epub",
                "chapter_count": len(chapters),
                "paragraph_count": len(paragraphs),
            },
        )
    raise ValueError("unsupported book format; upload EPUB only")


def extract_pdf_document_from_bytes(data: bytes, *, language: str = "") -> DocumentParseResult:
    try:
        return _extract_pdf_with_fitz(data, language=language)
    except ModuleNotFoundError:
        return _extract_pdf_with_pypdf(data, language=language)


def _clean_pdf_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [norm_space(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _split_pdf_paragraphs(text: str) -> List[str]:
    cleaned = _clean_pdf_text(text)
    if not cleaned:
        return []
    parts = re.split(r"\n\s*\n+", cleaned)
    if len(parts) == 1:
        lines = [line for line in cleaned.splitlines() if line]
        paragraphs: List[str] = []
        current = ""
        for line in lines:
            if _looks_like_noise_line(line):
                continue
            if not current:
                current = line
            elif _looks_like_heading(line) or _ends_sentence(current):
                paragraphs.append(current)
                current = line
            else:
                current = norm_space(f"{current} {line}")
        if current:
            paragraphs.append(current)
        return [p for p in paragraphs if len(p) >= 2]
    return [norm_space(part.replace("\n", " ")) for part in parts if len(norm_space(part)) >= 2]


def _looks_like_noise_line(line: str) -> bool:
    if re.fullmatch(r"\d{1,4}", line):
        return True
    if re.fullmatch(r"[-–—·•\s]+", line):
        return True
    return False


def _ends_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?。！？;；:”’\"']$", text.strip()))


def _looks_like_heading(text: str) -> bool:
    clean = norm_space(text)
    if not clean or len(clean) > 80:
        return False
    return bool(
        re.match(
            r"^(chapter|book|part|section)\b|^第[一二三四五六七八九十百零〇\d]+[章节卷部篇]|^\d{1,3}[.)、]\s+",
            clean,
            flags=re.I,
        )
    )


def _chapters_from_title_candidates(paragraphs: List[str]) -> List[ChapterSegment]:
    candidates = [idx for idx, text in enumerate(paragraphs) if _looks_like_heading(text)]
    if not candidates or candidates[0] != 0:
        candidates.insert(0, 0)
    chapters: List[ChapterSegment] = []
    for pos, start in enumerate(candidates):
        end = (candidates[pos + 1] - 1) if pos + 1 < len(candidates) else len(paragraphs) - 1
        if start <= end:
            title = paragraphs[start] if _looks_like_heading(paragraphs[start]) else f"PDF Section {pos + 1}"
            chapters.append(ChapterSegment(title=title, path=f"pdf:paragraphs:{start}-{end}", start=start, end=end))
    return chapters


def _fallback_chapters(paragraphs: List[str], page_count: int) -> List[ChapterSegment]:
    if not paragraphs:
        return []
    chapters = _chapters_from_title_candidates(paragraphs)
    if chapters:
        return chapters
    return [ChapterSegment(title="全文", path=f"pdf:pages:1-{max(1, page_count)}", start=0, end=len(paragraphs) - 1)]


def _read_tesseract_languages(language: str) -> Tuple[str, List[str]]:
    warnings: List[str] = []
    if shutil.which("tesseract") is None:
        warnings.append("tesseract binary not found; scanned PDF pages cannot be OCRed")
        return "", warnings
    desired = "chi_sim+chi_tra+eng" if language == "zh" else "eng"
    try:
        import pytesseract

        available = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # pragma: no cover - depends on local tesseract install
        warnings.append(f"could not inspect tesseract languages: {exc}")
        return desired, warnings
    selected = [item for item in desired.split("+") if item in available]
    if not selected:
        warnings.append(f"missing requested tesseract language pack(s): {desired}")
        return "", warnings
    missing = [item for item in desired.split("+") if item not in available]
    if missing:
        warnings.append(f"missing tesseract language pack(s): {'+'.join(missing)}")
    return "+".join(selected), warnings


def _text_quality_ok(text: str) -> bool:
    clean = norm_space(text)
    if len(clean) < 20:
        return False
    readable = sum(1 for ch in clean if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return readable / max(1, len(clean)) >= 0.45


def _extract_pdf_with_fitz(data: bytes, *, language: str) -> DocumentParseResult:
    import fitz  # type: ignore

    warnings: List[str] = []
    page_texts: List[str] = []
    text_layer_pages = 0
    ocr_pages = 0
    ocr_lang, lang_warnings = _read_tesseract_languages(language)
    warnings.extend(lang_warnings)
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text("text") or ""
            if _text_quality_ok(text):
                text_layer_pages += 1
                page_texts.append(text)
                continue
            if ocr_lang:
                try:
                    import pytesseract
                    from PIL import Image

                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr_text = pytesseract.image_to_string(image, lang=ocr_lang)
                    if norm_space(ocr_text):
                        ocr_pages += 1
                        page_texts.append(ocr_text)
                        continue
                except Exception as exc:  # pragma: no cover - OCR stack is environment-sensitive
                    warnings.append(f"OCR failed on page {page.number + 1}: {exc}")
            warnings.append(f"page {page.number + 1} has little readable text")
            page_texts.append(text)
        outlines = doc.get_toc(simple=True)
        page_count = doc.page_count
    paragraphs = _split_pdf_paragraphs("\n\n".join(page_texts))
    chapters = _chapters_from_outlines(outlines, paragraphs, page_count) if outlines else []
    if not chapters:
        chapters = _fallback_chapters(paragraphs, page_count)
        if len(chapters) == 1 and chapters[0].title == "全文":
            warnings.append("PDF has no usable bookmarks/headings; imported as one chapter")
    return DocumentParseResult(
        source_format="pdf",
        parser_version=parser_version_for_format("pdf"),
        paragraphs=paragraphs,
        chapters=chapters,
        parse_warnings=warnings,
        quality_stats={
            "source_format": "pdf",
            "page_count": page_count,
            "text_layer_pages": text_layer_pages,
            "ocr_pages": ocr_pages,
            "chapter_count": len(chapters),
            "paragraph_count": len(paragraphs),
            "pdf_backend": "pymupdf",
        },
    )


def _chapters_from_outlines(
    outlines: List[List[Any]],
    paragraphs: List[str],
    page_count: int,
) -> List[ChapterSegment]:
    if not outlines or not paragraphs:
        return []
    top_level = [item for item in outlines if len(item) >= 3 and int(item[2]) >= 1]
    if not top_level:
        return []
    top_level = sorted(top_level, key=lambda item: int(item[2]))
    chapters: List[ChapterSegment] = []
    for idx, item in enumerate(top_level):
        page = int(item[2])
        next_page = int(top_level[idx + 1][2]) if idx + 1 < len(top_level) else page_count + 1
        start = round(((page - 1) / max(1, page_count)) * len(paragraphs))
        end = round(((next_page - 1) / max(1, page_count)) * len(paragraphs)) - 1
        start = max(0, min(len(paragraphs) - 1, start))
        end = max(start, min(len(paragraphs) - 1, end))
        title = norm_space(str(item[1])) or f"PDF Section {idx + 1}"
        chapters.append(ChapterSegment(title=title, path=f"pdf:outline:{idx}:pages:{page}-{next_page - 1}", start=start, end=end))
    return chapters


def _extract_pdf_with_pypdf(data: bytes, *, language: str) -> DocumentParseResult:
    from PyPDF2 import PdfReader

    warnings = ["PyMuPDF is not installed; using PyPDF2 text-layer fallback without page rendering OCR"]
    if language:
        warnings.append("OCR fallback requires PyMuPDF page rendering and local tesseract")
    reader = PdfReader(io.BytesIO(data))
    page_texts: List[str] = []
    text_layer_pages = 0
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            warnings.append(f"text extraction failed on page {index + 1}: {exc}")
            text = ""
        if _text_quality_ok(text):
            text_layer_pages += 1
        else:
            warnings.append(f"page {index + 1} has little readable text")
        page_texts.append(text)
    paragraphs = _split_pdf_paragraphs("\n\n".join(page_texts))
    chapters = _fallback_chapters(paragraphs, len(reader.pages))
    if not paragraphs:
        warnings.append("no readable PDF text extracted")
    return DocumentParseResult(
        source_format="pdf",
        parser_version=parser_version_for_format("pdf"),
        paragraphs=paragraphs,
        chapters=chapters,
        parse_warnings=warnings,
        quality_stats={
            "source_format": "pdf",
            "page_count": len(reader.pages),
            "text_layer_pages": text_layer_pages,
            "ocr_pages": 0,
            "chapter_count": len(chapters),
            "paragraph_count": len(paragraphs),
            "pdf_backend": "pypdf",
        },
    )
