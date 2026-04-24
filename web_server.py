#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import time
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

from alignment_common import get_api_config, norm_space, safe_json_int
from alignment_service import align_book_by_chapter_mapping, align_single_chapter, map_chapters_ai
from chapter_catalog import extract_epub_document_from_bytes


def _api_log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[api {ts}] {msg}", flush=True)


def _para_stats(paragraphs: List[Any]) -> Dict[str, Any]:
    texts = [str(v) for v in paragraphs]
    return {
        "paragraph_count": len(texts),
        "char_total": sum(len(t) for t in texts),
        "char_max": max((len(t) for t in texts), default=0),
    }


class AppHandler(SimpleHTTPRequestHandler):
    def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8") if raw else "{}")
            if self.path == "/api/chapter-match":
                t0 = time.perf_counter()
                zh_titles = payload.get("zh_titles", [])
                en_titles = payload.get("en_titles", [])
                if not isinstance(zh_titles, list) or not isinstance(en_titles, list):
                    raise ValueError("zh_titles/en_titles 必须是数组")
                zh_titles = [norm_space(str(t)) for t in zh_titles if norm_space(str(t))]
                en_titles = [norm_space(str(t)) for t in en_titles if norm_space(str(t))]
                _api_log(f"POST /api/chapter-match start zh={len(zh_titles)} en={len(en_titles)}")

                config = get_api_config()
                pairs = map_chapters_ai(zh_titles, en_titles, config)
                output: List[Dict[str, Any]] = [
                    {"zh_index": p.zh_index, "en_index": p.en_index, "confidence": p.confidence, "reason": p.reason}
                    for p in pairs
                ]
                ms = int((time.perf_counter() - t0) * 1000)
                _api_log(f"POST /api/chapter-match ok pairs={len(output)} duration_ms={ms}")
                self._send_json({"pairs": output})
                return

            if self.path == "/api/extract-epub":
                t0 = time.perf_counter()
                epub_base64 = payload.get("epub_base64", "")
                if not isinstance(epub_base64, str) or not epub_base64.strip():
                    raise ValueError("epub_base64 不能为空")
                epub_bytes = base64.b64decode(epub_base64)
                _api_log(f"POST /api/extract-epub start bytes={len(epub_bytes)}")
                paragraphs, chapters = extract_epub_document_from_bytes(epub_bytes)
                st = _para_stats(paragraphs)
                ms = int((time.perf_counter() - t0) * 1000)
                _api_log(
                    f"POST /api/extract-epub ok paragraphs={st['paragraph_count']} "
                    f"chapters={len(chapters)} chars≈{st['char_total']} duration_ms={ms}"
                )
                self._send_json(
                    {
                        "paragraphs": paragraphs,
                        "chapters": [
                            {"title": c.title, "path": c.path, "start": c.start, "end": c.end}
                            for c in chapters
                        ],
                    }
                )
                return

            if self.path == "/api/align-paragraphs":
                t0 = time.perf_counter()
                zh_paragraphs = payload.get("zh_paragraphs", [])
                en_paragraphs = payload.get("en_paragraphs", [])
                zh_chapters = payload.get("zh_chapters", [])
                en_chapters = payload.get("en_chapters", [])
                chapter_map = payload.get("chapter_map", [])
                if not isinstance(zh_paragraphs, list) or not isinstance(en_paragraphs, list):
                    raise ValueError("zh_paragraphs/en_paragraphs 必须是数组")
                if not isinstance(zh_chapters, list) or not isinstance(en_chapters, list) or not isinstance(chapter_map, list):
                    raise ValueError("zh_chapters/en_chapters/chapter_map 必须是数组")
                zs = _para_stats(zh_paragraphs)
                es = _para_stats(en_paragraphs)
                _api_log(
                    f"POST /api/align-paragraphs start zh_paras={zs['paragraph_count']} en_paras={es['paragraph_count']} "
                    f"zh_chapters={len(zh_chapters)} map_len={len(chapter_map)} "
                    f"zh_chars≈{zs['char_total']} en_chars≈{es['char_total']}"
                )
                config = get_api_config()
                result = align_book_by_chapter_mapping(
                    zh_paragraphs=[str(v) for v in zh_paragraphs],
                    en_paragraphs=[str(v) for v in en_paragraphs],
                    zh_chapters=zh_chapters,
                    en_chapters=en_chapters,
                    chapter_map=[safe_json_int(v, 0) for v in chapter_map],
                    config=config,
                )
                stats = result.get("stats") if isinstance(result, dict) else None
                review_n = len(result.get("review_items", [])) if isinstance(result, dict) else 0
                ms = int((time.perf_counter() - t0) * 1000)
                _api_log(
                    f"POST /api/align-paragraphs ok duration_ms={ms} "
                    f"review_items={review_n} stats={stats!r}"
                )
                self._send_json(result)
                return

            if self.path == "/api/align-chapter":
                t0 = time.perf_counter()
                zh_paragraphs = payload.get("zh_paragraphs", [])
                en_paragraphs = payload.get("en_paragraphs", [])
                zh_chapters = payload.get("zh_chapters", [])
                en_chapters = payload.get("en_chapters", [])
                chapter_map = payload.get("chapter_map", [])
                chapter_index = safe_json_int(payload.get("chapter_index"), -1)
                if not isinstance(zh_paragraphs, list) or not isinstance(en_paragraphs, list):
                    raise ValueError("zh_paragraphs/en_paragraphs 必须是数组")
                if not isinstance(zh_chapters, list) or not isinstance(en_chapters, list) or not isinstance(chapter_map, list):
                    raise ValueError("zh_chapters/en_chapters/chapter_map 必须是数组")
                zh_title = ""
                en_title = ""
                en_idx = -1
                if 0 <= chapter_index < len(zh_chapters):
                    zh_title = norm_space(str(zh_chapters[chapter_index].get("title", "")))
                if 0 <= chapter_index < len(chapter_map):
                    en_idx = safe_json_int(chapter_map[chapter_index], -1)
                if 0 <= en_idx < len(en_chapters):
                    en_title = norm_space(str(en_chapters[en_idx].get("title", "")))
                zs = _para_stats(zh_paragraphs)
                es = _para_stats(en_paragraphs)
                _api_log(
                    f"POST /api/align-chapter start chapter_zh={chapter_index + 1} "
                    f"zh_title={zh_title or 'N/A'} en_chapter={en_idx + 1 if en_idx >= 0 else 'N/A'} "
                    f"en_title={en_title or 'N/A'} "
                    f"book_zh_paras={zs['paragraph_count']} book_en_paras={es['paragraph_count']} "
                    f"zh_chars≈{zs['char_total']} en_chars≈{es['char_total']}"
                )
                config = get_api_config()
                result = align_single_chapter(
                    zh_paragraphs=[str(v) for v in zh_paragraphs],
                    en_paragraphs=[str(v) for v in en_paragraphs],
                    zh_chapters=zh_chapters,
                    en_chapters=en_chapters,
                    chapter_map=[safe_json_int(v, 0) for v in chapter_map],
                    chapter_index=chapter_index,
                    config=config,
                )
                review_n = len(result.get("review_items", [])) if isinstance(result, dict) else 0
                blocks_n = len(result.get("blocks", [])) if isinstance(result, dict) else 0
                lsm = result.get("local_sync_map") if isinstance(result, dict) else None
                local_len = len(lsm) if isinstance(lsm, list) else 0
                ms = int((time.perf_counter() - t0) * 1000)
                _api_log(
                    f"POST /api/align-chapter ok chapter={chapter_index + 1} duration_ms={ms} "
                    f"local_map_len={local_len} blocks={blocks_n} review_items={review_n}"
                )
                self._send_json(result)
                return

            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-except
            _api_log(f"POST {self.path!r} ERROR: {exc!r}")
            traceback.print_exc()
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> int:
    parser = argparse.ArgumentParser(description="DuReading local web server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), AppHandler)
    print(f"启动网页服务: http://localhost:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
