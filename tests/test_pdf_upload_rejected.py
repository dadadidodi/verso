from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from document_parser import detect_source_format, extract_document_from_bytes
from web_server import create_app


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


def test_document_upload_parser_rejects_pdf() -> None:
    data = _simple_text_pdf("Chapter 1. This PDF should be converted to EPUB before upload.")

    with pytest.raises(ValueError, match="EPUB only"):
        detect_source_format("sample.pdf", "application/pdf")
    with pytest.raises(ValueError, match="EPUB only"):
        extract_document_from_bytes(data, filename="sample.pdf", content_type="application/pdf", language="en")


def test_pdf_upload_returns_400_and_import_preview_route_is_removed(tmp_path: Path) -> None:
    app = create_app(tmp_path / "storage")
    data = _simple_text_pdf("Chapter 1. Direct PDF upload is intentionally disabled.")

    async def run_flow() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            upload_resp = await client.post(
                "/api/books",
                data={"language": "en"},
                files={"file": ("sample.pdf", data, "application/pdf")},
            )
            assert upload_resp.status_code == 400
            assert "epub only" in str(upload_resp.json()["detail"]).lower()

            preview_resp = await client.post(
                "/api/book-imports",
                data={"language": "en"},
                files={"file": ("sample.pdf", data, "application/pdf")},
            )
            assert preview_resp.status_code == 404

    asyncio.run(run_flow())
