from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from chapter_catalog import ChapterSegment, PARSER_VERSION as EPUB_PARSER_VERSION, extract_epub_document_from_bytes


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
    raise ValueError(f"unsupported source format: {source_format}")


def source_filename_for_format(source_format: str) -> str:
    if source_format == "epub":
        return "source.epub"
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
    if source_format != "epub":
        raise ValueError("unsupported book format; upload EPUB only")

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
