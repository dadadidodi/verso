#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from alignment_common import get_api_config
from hybrid_alignment import align_chapter_hybrid, suggest_chapter_mappings
from paragraph_alignment import AlignmentBlock, expand_en_ranges_from_blocks
from server_events import append_server_event
from storage_v2 import DuReadingStore


APP_ROOT = Path(__file__).resolve().parent
ENGINE_VERSION = "hybrid_v2"
PROMPT_VERSION = "v2"


class ProjectCreateRequest(BaseModel):
    zh_book_id: int
    en_book_id: int


class ChapterMappingItem(BaseModel):
    zh_chapter_index: int
    en_chapter_index: int
    source: str = "manual"
    confidence: Optional[float] = None
    reason: str = ""
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    confirmed: bool = False


class ChapterMappingUpdateRequest(BaseModel):
    mappings: List[ChapterMappingItem]


class AlignChapterRequest(BaseModel):
    force: bool = False
    use_anchors: bool = True
    allow_llm: bool = True
    llm_policy: str = "auto"


class AnchorCreateRequest(BaseModel):
    zh_chapter_index: Optional[int] = None
    zh_paragraph_index: Optional[int] = None
    en_paragraph_index: Optional[int] = None
    zh_start: Optional[int] = None
    zh_end: Optional[int] = None
    en_start: Optional[int] = None
    en_end: Optional[int] = None
    kind: str = "hard"
    confirmed: bool = True
    note: str = ""


class MismatchReportRequest(BaseModel):
    chapter_index: int
    zh_start: int
    zh_end: int
    en_start: int
    en_end: int
    note: str = ""
    cache_key: str = ""


class JobRequest(BaseModel):
    chapter_index: Optional[int] = None
    count: int = 2
    allow_llm: bool = True
    llm_policy: str = "auto"


def _http_404(msg: str) -> HTTPException:
    return HTTPException(status_code=404, detail=msg)


def _normalize_llm_policy(llm_policy: str, allow_llm: bool) -> str:
    policy = (llm_policy or "auto").strip().lower()
    if policy not in {"auto", "force", "off"}:
        policy = "auto"
    if not allow_llm:
        return "off"
    return policy


def _alignment_source_from_metrics(state: str, metrics: Dict[str, Any]) -> str:
    if state == "skipped":
        return "skipped"
    if metrics.get("alignment_source"):
        return str(metrics["alignment_source"])
    if metrics.get("llm_rate_limited"):
        return "fallback"
    llm_calls = int(metrics.get("llm_calls") or 0)
    heuristic_segments = int(metrics.get("heuristic_segments") or 0)
    if llm_calls > 0 and heuristic_segments > 0:
        return "mixed"
    if llm_calls > 0:
        return "lm"
    return "heuristic"


def _project_context(store: DuReadingStore, project_id: int) -> Dict[str, Any]:
    try:
        overview = store.build_project_overview(project_id)
    except KeyError as exc:
        raise _http_404(str(exc)) from exc
    project = overview["project"]
    zh_paragraphs, zh_chapters = store.load_book_document(int(project["zh_book_id"]))
    en_paragraphs, en_chapters = store.load_book_document(int(project["en_book_id"]))
    mappings = {item["zh_chapter_index"]: item for item in store.list_chapter_mappings(project_id)}
    return {
        "overview": overview,
        "project": project,
        "zh_paragraphs": zh_paragraphs,
        "zh_chapters": zh_chapters,
        "en_paragraphs": en_paragraphs,
        "en_chapters": en_chapters,
        "mappings": mappings,
    }


def _project_overview_or_404(store: DuReadingStore, project_id: int) -> Dict[str, Any]:
    try:
        return store.build_project_overview(project_id)
    except KeyError as exc:
        raise _http_404(str(exc)) from exc


def _book_or_404(store: DuReadingStore, book_id: int) -> Dict[str, Any]:
    try:
        return store.get_book(book_id)
    except KeyError as exc:
        raise _http_404(str(exc)) from exc


def _validate_project_books(store: DuReadingStore, zh_book_id: int, en_book_id: int) -> None:
    zh_book = _book_or_404(store, zh_book_id)
    en_book = _book_or_404(store, en_book_id)
    if zh_book.get("language") != "zh":
        raise HTTPException(status_code=400, detail="zh_book_id must reference a zh book")
    if en_book.get("language") != "en":
        raise HTTPException(status_code=400, detail="en_book_id must reference an en book")


def _validate_mapping_update(
    ctx: Dict[str, Any],
    mappings: List[ChapterMappingItem],
) -> List[Dict[str, Any]]:
    zh_count = len(ctx["zh_chapters"])
    en_count = len(ctx["en_chapters"])
    seen_zh: set[int] = set()
    out: List[Dict[str, Any]] = []
    for item in mappings:
        zh_index = int(item.zh_chapter_index)
        en_index = int(item.en_chapter_index)
        if zh_index in seen_zh:
            raise HTTPException(status_code=400, detail=f"duplicate zh_chapter_index {zh_index}")
        if not (0 <= zh_index < zh_count):
            raise HTTPException(status_code=400, detail=f"zh_chapter_index {zh_index} out of range")
        if not (0 <= en_index < en_count):
            raise HTTPException(status_code=400, detail=f"en_chapter_index {en_index} out of range")
        seen_zh.add(zh_index)
        out.append(item.model_dump())
    return out


def _chapter_scope(ctx: Dict[str, Any], chapter_index: int) -> Dict[str, Any]:
    zh_chapters = ctx["zh_chapters"]
    en_chapters = ctx["en_chapters"]
    mappings = ctx["mappings"]
    if chapter_index < 0 or chapter_index >= len(zh_chapters):
        raise HTTPException(status_code=400, detail="chapter_index out of range")
    if chapter_index not in mappings:
        raise HTTPException(status_code=400, detail="chapter mapping missing; suggest or confirm mappings first")
    mapping = mappings[chapter_index]
    en_index = int(mapping["en_chapter_index"])
    if en_index < 0 or en_index >= len(en_chapters):
        raise HTTPException(status_code=400, detail="mapped English chapter out of range")
    zh_chapter = zh_chapters[chapter_index]
    en_chapter = en_chapters[en_index]
    zh_start = int(zh_chapter.get("start", 0))
    zh_end = int(zh_chapter.get("end", 0))
    en_start = int(en_chapter.get("start", 0))
    en_end = int(en_chapter.get("end", 0))
    return {
        "chapter_index": chapter_index,
        "mapped_en_chapter_index": en_index,
        "zh_chapter": zh_chapter,
        "en_chapter": en_chapter,
        "zh_start": zh_start,
        "zh_end": zh_end,
        "en_start": en_start,
        "en_end": en_end,
        "local_zh": ctx["zh_paragraphs"][zh_start : zh_end + 1],
        "local_en": ctx["en_paragraphs"][en_start : en_end + 1],
    }


def _approximate_map(zh_len: int, en_len: int) -> List[int]:
    if zh_len <= 0:
        return []
    if en_len <= 0:
        return [0] * zh_len
    if zh_len == 1:
        return [0]
    return [round((i / (zh_len - 1)) * max(0, en_len - 1)) for i in range(zh_len)]


def _ranges_from_sync_map(sync_map: List[int], en_len: int) -> List[List[int]]:
    if not sync_map:
        return []
    ranges: List[List[int]] = []
    for idx, en_index in enumerate(sync_map):
        next_en = sync_map[idx + 1] if idx + 1 < len(sync_map) else en_len
        start = max(0, min(en_len - 1, int(en_index))) if en_len > 0 else 0
        end = start if next_en <= en_index else max(start, min(en_len - 1, int(next_en) - 1))
        if idx == len(sync_map) - 1 and en_len > 0:
            end = max(start, en_len - 1)
        ranges.append([start, end])
    return ranges


def _ranges_from_blocks(blocks: List[Dict[str, Any]], zh_len: int, en_len: int) -> List[List[int]]:
    if not blocks:
        return []
    typed_blocks = [
        AlignmentBlock(
            zh_start=int(block["zh_start"]),
            zh_end=int(block["zh_end"]),
            en_start=int(block["en_start"]),
            en_end=int(block["en_end"]),
            confidence=float(block.get("confidence", 0.0)),
            reason=str(block.get("reason", "")),
        )
        for block in blocks
    ]
    return [list(item) for item in expand_en_ranges_from_blocks(typed_blocks, zh_len, en_len)]


def _anchor_range_from_request(request: AnchorCreateRequest) -> Dict[str, int]:
    zh_start = request.zh_start
    zh_end = request.zh_end
    en_start = request.en_start
    en_end = request.en_end
    if zh_start is None:
        zh_start = request.zh_paragraph_index
    if zh_end is None:
        zh_end = zh_start
    if en_start is None:
        en_start = request.en_paragraph_index
    if en_end is None:
        en_end = en_start
    if zh_start is None or zh_end is None or en_start is None or en_end is None:
        raise HTTPException(status_code=400, detail="anchor range missing")
    zh_a, zh_b = sorted((int(zh_start), int(zh_end)))
    en_a, en_b = sorted((int(en_start), int(en_end)))
    return {"zh_start": zh_a, "zh_end": zh_b, "en_start": en_a, "en_end": en_b}


def _validate_anchor_range(
    store: DuReadingStore,
    project_id: int,
    chapter_index: int,
    anchor_range: Dict[str, int],
) -> None:
    payload = _reader_payload(store, project_id, chapter_index)
    zh_len = len(payload["zh_paragraphs"])
    en_len = len(payload["en_paragraphs"])
    if not (0 <= anchor_range["zh_start"] <= anchor_range["zh_end"] < zh_len):
        raise HTTPException(status_code=400, detail="anchor Chinese range out of bounds")
    if not (0 <= anchor_range["en_start"] <= anchor_range["en_end"] < en_len):
        raise HTTPException(status_code=400, detail="anchor English range out of bounds")
    if not anchor_range:
        return
    existing = [
        item for item in store.list_anchors(project_id, chapter_index)
        if item.get("kind") == "hard" and item.get("confirmed")
    ]
    for item in existing:
        zh_overlaps = not (
            anchor_range["zh_end"] < int(item["zh_start"]) or anchor_range["zh_start"] > int(item["zh_end"])
        )
        en_overlaps = not (
            anchor_range["en_end"] < int(item["en_start"]) or anchor_range["en_start"] > int(item["en_end"])
        )
        crosses = (
            anchor_range["zh_start"] > int(item["zh_end"]) and anchor_range["en_start"] <= int(item["en_end"])
        ) or (
            anchor_range["zh_end"] < int(item["zh_start"]) and anchor_range["en_end"] >= int(item["en_start"])
        )
        if zh_overlaps or en_overlaps or crosses:
            raise HTTPException(
                status_code=400,
                detail=(
                    "anchor conflicts with existing "
                    f"zh {int(item['zh_start']) + 1}-{int(item['zh_end']) + 1} "
                    f"en {int(item['en_start']) + 1}-{int(item['en_end']) + 1}"
                ),
            )


def _serialize_alignment_payload(
    alignment: Optional[Dict[str, Any]],
    *,
    zh_len: int,
    en_len: int,
) -> Optional[Dict[str, Any]]:
    if alignment is None:
        return None
    blocks = list(alignment.get("blocks", []))
    sync_map = list(alignment.get("local_sync_map", []))
    payload = dict(alignment)
    payload["blocks"] = blocks
    payload["local_sync_map"] = sync_map
    payload["en_ranges_by_zh"] = (
        _ranges_from_blocks(blocks, zh_len, en_len) if blocks else _ranges_from_sync_map(sync_map, en_len)
    )
    payload["metrics"] = dict(payload.get("metrics") or {})
    payload["metrics"]["alignment_source"] = _alignment_source_from_metrics(
        str(payload.get("state") or "draft"),
        payload["metrics"],
    )
    return payload


def _reader_payload(store: DuReadingStore, project_id: int, chapter_index: int) -> Dict[str, Any]:
    ctx = _project_context(store, project_id)
    scope = _chapter_scope(ctx, chapter_index)
    alignment = store.get_chapter_alignment(project_id, chapter_index)
    if alignment is not None:
        sync_map = alignment["local_sync_map"]
        en_ranges_by_zh = _serialize_alignment_payload(
            alignment,
            zh_len=len(scope["local_zh"]),
            en_len=len(scope["local_en"]),
        )["en_ranges_by_zh"]
        source = alignment["state"]
    else:
        sync_map = _approximate_map(len(scope["local_zh"]), len(scope["local_en"]))
        en_ranges_by_zh = _ranges_from_sync_map(sync_map, len(scope["local_en"]))
        source = "approximate"
    return {
        "chapter_index": chapter_index,
        "mapped_en_chapter_index": scope["mapped_en_chapter_index"],
        "zh_title": str(scope["zh_chapter"].get("title", "")),
        "en_title": str(scope["en_chapter"].get("title", "")),
        "zh_range": {"start": scope["zh_start"], "end": scope["zh_end"]},
        "en_range": {"start": scope["en_start"], "end": scope["en_end"]},
        "zh_paragraphs": scope["local_zh"],
        "en_paragraphs": scope["local_en"],
        "local_sync_map": sync_map,
        "en_ranges_by_zh": en_ranges_by_zh,
        "sync_source": source,
    }


def _is_llm_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    return "HTTP 429" in text or "rate_limit_exceeded" in text or "Too Many Requests" in text


def _run_align_one(
    store: DuReadingStore,
    project_id: int,
    chapter_index: int,
    *,
    allow_llm: bool,
    force: bool,
    use_anchors: bool,
    llm_policy: str = "auto",
) -> Dict[str, Any]:
    policy = _normalize_llm_policy(llm_policy, allow_llm)
    ctx = _project_context(store, project_id)
    scope = _chapter_scope(ctx, chapter_index)
    anchors = [
        item for item in store.list_anchors(project_id, chapter_index)
        if item.get("kind") == "hard" and item.get("confirmed")
    ] if use_anchors else []
    cache_hit = False
    existing = store.get_chapter_alignment(project_id, chapter_index)
    config = get_api_config()
    fallback_reason = ""
    debug_label = f"project_{project_id}_chapter_{chapter_index + 1}"
    append_server_event(
        "alignment_start",
        project_id=project_id,
        chapter_index=chapter_index,
        debug_label=debug_label,
        llm_policy=policy,
        force=force,
        use_anchors=use_anchors,
    )
    try:
        result = align_chapter_hybrid(
            scope["local_zh"],
            scope["local_en"],
            config,
            anchors=anchors,
            allow_llm=allow_llm,
            force=force,
            llm_policy=policy,
            engine_version=ENGINE_VERSION,
            prompt_version=PROMPT_VERSION,
            debug_label=debug_label,
        )
    except RuntimeError as exc:
        if not allow_llm or not _is_llm_rate_limit_error(exc):
            raise
        fallback_reason = str(exc)
        append_server_event(
            "llm_rate_limited_fallback",
            project_id=project_id,
            chapter_index=chapter_index,
            debug_label=debug_label,
            llm_policy=policy,
            error=fallback_reason,
        )
        result = align_chapter_hybrid(
            scope["local_zh"],
            scope["local_en"],
            config,
            anchors=anchors,
            allow_llm=False,
            force=False,
            llm_policy="off",
            engine_version=ENGINE_VERSION,
            prompt_version=PROMPT_VERSION,
            debug_label=f"project_{project_id}_chapter_{chapter_index + 1}_fallback",
        )
        result["metrics"] = {
            **result.get("metrics", {}),
            "llm_rate_limited": True,
            "fallback_reason": fallback_reason,
            "alignment_source": "fallback",
            "llm_policy": policy,
        }
        for decision in result["metrics"].get("decision_log", []):
            if decision.get("method") == "heuristic":
                decision["reason"] = "rate_limited_fallback"
    if existing is not None and existing.get("cache_key") == result["cache_key"] and not force:
        existing_payload = _serialize_alignment_payload(
            existing,
            zh_len=len(scope["local_zh"]),
            en_len=len(scope["local_en"]),
        )
        cache_hit = True
        append_server_event(
            "alignment_cache_hit",
            project_id=project_id,
            chapter_index=chapter_index,
            debug_label=debug_label,
            llm_policy=policy,
            alignment_source=existing_payload["metrics"].get("alignment_source"),
        )
        return {
            "chapter_index": chapter_index,
            "mapped_en_chapter_index": scope["mapped_en_chapter_index"],
            "zh_range": {"start": scope["zh_start"], "end": scope["zh_end"]},
            "en_range": {"start": scope["en_start"], "end": scope["en_end"]},
            "blocks": existing_payload["blocks"],
            "local_sync_map": existing_payload["local_sync_map"],
            "en_ranges_by_zh": existing_payload["en_ranges_by_zh"],
            "review_items": existing_payload["review_items"],
            "metrics": {**existing_payload["metrics"], "cache_hit": True},
            "state": existing_payload["state"],
        }
    state = "draft"
    store.save_chapter_alignment(
        project_id,
        chapter_index,
        state=state,
        blocks=result["blocks"],
        local_sync_map=result["local_sync_map"],
        review_items=result["review_items"],
        metrics=result["metrics"],
        cache_key=result["cache_key"],
    )
    for decision in result["metrics"].get("decision_log", []):
        append_server_event(
            "alignment_decision",
            project_id=project_id,
            chapter_index=chapter_index,
            debug_label=decision.get("debug_label", debug_label),
            llm_policy=policy,
            method=decision.get("method"),
            reason=decision.get("reason"),
            zh_len=decision.get("zh_len"),
            en_len=decision.get("en_len"),
            segment_index=decision.get("segment_index"),
        )
    append_server_event(
        "alignment_saved",
        project_id=project_id,
        chapter_index=chapter_index,
        debug_label=debug_label,
        llm_policy=policy,
        alignment_source=result["metrics"].get("alignment_source"),
        llm_calls=result["metrics"].get("llm_calls"),
        heuristic_segments=result["metrics"].get("heuristic_segments"),
    )
    return {
        "chapter_index": chapter_index,
        "mapped_en_chapter_index": scope["mapped_en_chapter_index"],
        "zh_range": {"start": scope["zh_start"], "end": scope["zh_end"]},
        "en_range": {"start": scope["en_start"], "end": scope["en_end"]},
        "blocks": result["blocks"],
        "local_sync_map": result["local_sync_map"],
        "en_ranges_by_zh": _ranges_from_blocks(result["blocks"], len(scope["local_zh"]), len(scope["local_en"])),
        "review_items": result["review_items"],
        "metrics": {**result["metrics"], "cache_hit": cache_hit},
        "state": state,
    }


def _background_prefetch(
    store: DuReadingStore,
    project_id: int,
    job_id: int,
    *,
    start_chapter: int,
    count: int,
    allow_llm: bool,
    llm_policy: str = "auto",
) -> None:
    policy = _normalize_llm_policy(llm_policy, allow_llm)
    try:
        ctx = _project_context(store, project_id)
        total = len(ctx["zh_chapters"])
        end_chapter = min(total, start_chapter + max(0, count))
        planned = [
            chapter_index
            for chapter_index in range(start_chapter, end_chapter)
            if chapter_index in ctx["mappings"]
        ]
        done: List[int] = []
        store.update_job(
            job_id,
            status="running",
            result={
                "aligned_chapters": done,
                "current_chapter": None,
                "done_count": 0,
                "total_count": len(planned),
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "llm_policy": policy,
            },
        )
        for chapter_index in planned:
            append_server_event(
                "job_progress",
                project_id=project_id,
                chapter_index=chapter_index,
                debug_label=f"project_{project_id}_job_{job_id}",
                job_id=job_id,
                llm_policy=policy,
                done_count=len(done),
                total_count=len(planned),
            )
            store.update_job(
                job_id,
                status="running",
                result={
                    "aligned_chapters": done,
                    "current_chapter": chapter_index,
                    "done_count": len(done),
                    "total_count": len(planned),
                    "start_chapter": start_chapter,
                    "end_chapter": end_chapter,
                    "llm_policy": policy,
                },
            )
            _run_align_one(
                store,
                project_id,
                chapter_index,
                allow_llm=allow_llm,
                force=False,
                use_anchors=True,
                llm_policy=policy,
            )
            done.append(chapter_index)
            store.update_job(
                job_id,
                status="running",
                result={
                    "aligned_chapters": done,
                    "current_chapter": chapter_index,
                    "done_count": len(done),
                    "total_count": len(planned),
                    "start_chapter": start_chapter,
                    "end_chapter": end_chapter,
                    "llm_policy": policy,
                },
            )
        append_server_event(
            "job_completed",
            project_id=project_id,
            chapter_index=None,
            debug_label=f"project_{project_id}_job_{job_id}",
            job_id=job_id,
            llm_policy=policy,
            done_count=len(done),
            total_count=len(planned),
        )
        store.update_job(
            job_id,
            status="completed",
            result={
                "aligned_chapters": done,
                "current_chapter": None,
                "done_count": len(done),
                "total_count": len(planned),
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "llm_policy": policy,
            },
        )
    except Exception as exc:
        append_server_event(
            "job_failed",
            project_id=project_id,
            chapter_index=None,
            debug_label=f"project_{project_id}_job_{job_id}",
            job_id=job_id,
            llm_policy=policy,
            error=str(exc),
        )
        store.update_job(job_id, status="failed", result={"error": str(exc)})


def create_app(storage_root: Optional[Path | str] = None) -> FastAPI:
    root = Path(storage_root or os.getenv("DUREADING_STORAGE_DIR", "storage"))
    store = DuReadingStore(root)
    app = FastAPI(title="DuReading V2", version="2.0")
    app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(APP_ROOT / "index.html")

    @app.get("/app.js")
    def app_js() -> FileResponse:
        return FileResponse(APP_ROOT / "app.js", media_type="application/javascript")

    @app.get("/styles.css")
    def styles_css() -> FileResponse:
        return FileResponse(APP_ROOT / "styles.css", media_type="text/css")

    @app.get("/frontend_logic.js")
    def frontend_logic_js() -> FileResponse:
        return FileResponse(APP_ROOT / "frontend_logic.js", media_type="application/javascript")

    @app.get("/api/books")
    def list_books() -> Dict[str, Any]:
        return {"books": store.list_books()}

    @app.post("/api/books")
    async def upload_book(language: str = Form(...), file: UploadFile = File(...)) -> Dict[str, Any]:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty upload")
        if language not in {"zh", "en"}:
            raise HTTPException(status_code=400, detail="language must be zh or en")
        try:
            book = store.create_or_get_book(language=language, filename=file.filename or "book.epub", data=data)
        except (zipfile.BadZipFile, ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid EPUB: {exc}") from exc
        return {"book": book}

    @app.get("/api/books/{book_id}")
    def get_book(book_id: int) -> Dict[str, Any]:
        try:
            return {"book": store.get_book(book_id)}
        except KeyError as exc:
            raise _http_404(str(exc)) from exc

    @app.delete("/api/books/{book_id}")
    def delete_book(book_id: int) -> Dict[str, Any]:
        try:
            result = store.delete_book(book_id)
        except KeyError as exc:
            raise _http_404(str(exc)) from exc
        return {"deleted": True, **result}

    @app.get("/api/books/{book_id}/chapters")
    def get_book_chapters(book_id: int) -> Dict[str, Any]:
        try:
            _, chapters = store.load_book_document(book_id)
        except KeyError as exc:
            raise _http_404(str(exc)) from exc
        return {"chapters": chapters}

    @app.get("/api/projects")
    def list_projects() -> Dict[str, Any]:
        return {"projects": store.list_projects()}

    @app.post("/api/projects")
    def create_project(request: ProjectCreateRequest) -> Dict[str, Any]:
        _validate_project_books(store, request.zh_book_id, request.en_book_id)
        project = store.create_project(
            zh_book_id=request.zh_book_id,
            en_book_id=request.en_book_id,
            alignment_engine_version=ENGINE_VERSION,
            prompt_version=PROMPT_VERSION,
        )
        return {"project": project}

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: int) -> Dict[str, Any]:
        try:
            project = store.delete_project(project_id)
        except KeyError as exc:
            raise _http_404(str(exc)) from exc
        return {"deleted": True, "project": project}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int) -> Dict[str, Any]:
        return _project_overview_or_404(store, project_id)

    @app.get("/api/projects/{project_id}/chapters")
    def project_chapters(project_id: int) -> Dict[str, Any]:
        overview = _project_overview_or_404(store, project_id)
        return {"chapters": overview["chapters"], "stats": overview["stats"]}

    @app.post("/api/projects/{project_id}/chapter-mapping/suggest")
    def suggest_mapping(project_id: int, allow_llm: bool = True) -> Dict[str, Any]:
        ctx = _project_context(store, project_id)
        suggestion = suggest_chapter_mappings(
            ctx["zh_paragraphs"],
            ctx["zh_chapters"],
            ctx["en_paragraphs"],
            ctx["en_chapters"],
            get_api_config(),
            allow_llm=allow_llm,
        )
        mappings = suggestion["mappings"]
        store.replace_chapter_mappings(project_id, mappings, confirmed=False)
        return {
            "mappings": store.list_chapter_mappings(project_id),
            "strategy": suggestion.get("strategy", "unknown"),
            "fallback_reason": suggestion.get("fallback_reason", ""),
        }

    @app.get("/api/projects/{project_id}/chapter-mapping")
    def get_mapping(project_id: int) -> Dict[str, Any]:
        return {"mappings": store.list_chapter_mappings(project_id)}

    @app.put("/api/projects/{project_id}/chapter-mapping")
    def put_mapping(project_id: int, request: ChapterMappingUpdateRequest) -> Dict[str, Any]:
        ctx = _project_context(store, project_id)
        mappings = _validate_mapping_update(ctx, request.mappings)
        store.replace_chapter_mappings(project_id, mappings, confirmed=False)
        return {"mappings": store.list_chapter_mappings(project_id)}

    @app.post("/api/projects/{project_id}/chapter-mapping/confirm")
    def confirm_mapping(project_id: int) -> Dict[str, Any]:
        store.confirm_chapter_mappings(project_id)
        return {"mappings": store.list_chapter_mappings(project_id)}

    @app.get("/api/projects/{project_id}/reader")
    def reader_summary(project_id: int) -> Dict[str, Any]:
        overview = _project_overview_or_404(store, project_id)
        return {
            "project": overview["project"],
            "stats": overview["stats"],
            "chapters": overview["chapters"],
        }

    @app.get("/api/projects/{project_id}/reader/chapters/{chapter_index}")
    def reader_chapter(project_id: int, chapter_index: int) -> Dict[str, Any]:
        return _reader_payload(store, project_id, chapter_index)

    @app.get("/api/projects/{project_id}/chapters/{chapter_index}/alignment")
    def chapter_alignment(project_id: int, chapter_index: int) -> Dict[str, Any]:
        payload = _reader_payload(store, project_id, chapter_index)
        alignment = store.get_chapter_alignment(project_id, chapter_index)
        serialized = _serialize_alignment_payload(
            alignment,
            zh_len=len(payload["zh_paragraphs"]),
            en_len=len(payload["en_paragraphs"]),
        )
        return {
            **payload,
            "alignment": serialized,
            "anchors": store.list_anchors(project_id, chapter_index),
        }

    @app.post("/api/projects/{project_id}/chapters/{chapter_index}/align")
    def align_chapter(project_id: int, chapter_index: int, request: AlignChapterRequest) -> Dict[str, Any]:
        return _run_align_one(
            store,
            project_id,
            chapter_index,
            allow_llm=request.allow_llm,
            force=request.force,
            use_anchors=request.use_anchors,
            llm_policy=request.llm_policy,
        )

    @app.post("/api/projects/{project_id}/chapters/{chapter_index}/confirm")
    def confirm_chapter(project_id: int, chapter_index: int) -> Dict[str, Any]:
        alignment = store.get_chapter_alignment(project_id, chapter_index)
        if alignment is None:
            raise HTTPException(status_code=400, detail="chapter alignment missing")
        payload = _reader_payload(store, project_id, chapter_index)
        store.save_chapter_alignment(
            project_id,
            chapter_index,
            state="confirmed",
            blocks=alignment["blocks"],
            local_sync_map=alignment["local_sync_map"],
            review_items=alignment["review_items"],
            metrics=alignment["metrics"],
            cache_key=str(alignment["cache_key"]),
        )
        updated = store.get_chapter_alignment(project_id, chapter_index)
        return {
            "alignment": _serialize_alignment_payload(
                updated,
                zh_len=len(payload["zh_paragraphs"]),
                en_len=len(payload["en_paragraphs"]),
            )
        }

    @app.post("/api/projects/{project_id}/chapters/{chapter_index}/skip")
    def skip_chapter(project_id: int, chapter_index: int) -> Dict[str, Any]:
        payload = _reader_payload(store, project_id, chapter_index)
        sync_map = _approximate_map(len(payload["zh_paragraphs"]), len(payload["en_paragraphs"]))
        store.save_chapter_alignment(
            project_id,
            chapter_index,
            state="skipped",
            blocks=[],
            local_sync_map=sync_map,
            review_items=[],
            metrics={"mode": "skipped", "alignment_source": "skipped"},
            cache_key=f"skipped:{chapter_index}",
        )
        updated = store.get_chapter_alignment(project_id, chapter_index)
        return {
            "alignment": _serialize_alignment_payload(
                updated,
                zh_len=len(payload["zh_paragraphs"]),
                en_len=len(payload["en_paragraphs"]),
            )
        }

    @app.post("/api/projects/{project_id}/chapters/{chapter_index}/regenerate")
    def regenerate_chapter(project_id: int, chapter_index: int, request: AlignChapterRequest) -> Dict[str, Any]:
        return _run_align_one(
            store,
            project_id,
            chapter_index,
            allow_llm=request.allow_llm,
            force=True,
            use_anchors=request.use_anchors,
            llm_policy="force",
        )

    @app.get("/api/projects/{project_id}/anchors")
    def get_anchors(project_id: int, zh_chapter_index: Optional[int] = None) -> Dict[str, Any]:
        return {"anchors": store.list_anchors(project_id, zh_chapter_index)}

    @app.post("/api/projects/{project_id}/anchors")
    def create_anchor(project_id: int, request: AnchorCreateRequest) -> Dict[str, Any]:
        anchor_range = _anchor_range_from_request(request)
        if request.zh_chapter_index is None:
            raise HTTPException(status_code=400, detail="zh_chapter_index is required")
        if request.kind == "hard" and request.confirmed:
            _validate_anchor_range(store, project_id, request.zh_chapter_index, anchor_range)
        item = store.add_anchor(
            project_id,
            zh_chapter_index=request.zh_chapter_index,
            zh_start=anchor_range["zh_start"],
            zh_end=anchor_range["zh_end"],
            en_start=anchor_range["en_start"],
            en_end=anchor_range["en_end"],
            kind=request.kind,
            confirmed=request.confirmed,
            note=request.note,
        )
        return {"anchor": item, "anchors": store.list_anchors(project_id, request.zh_chapter_index)}

    @app.delete("/api/projects/{project_id}/anchors/{anchor_id}")
    def delete_anchor(project_id: int, anchor_id: int, zh_chapter_index: Optional[int] = None) -> Dict[str, Any]:
        store.delete_anchor(project_id, anchor_id)
        return {"anchors": store.list_anchors(project_id, zh_chapter_index)}

    @app.post("/api/projects/{project_id}/mismatch-reports")
    def create_mismatch_report(project_id: int, request: MismatchReportRequest) -> Dict[str, Any]:
        payload = _reader_payload(store, project_id, request.chapter_index)
        zh_start, zh_end = sorted((int(request.zh_start), int(request.zh_end)))
        en_start, en_end = sorted((int(request.en_start), int(request.en_end)))
        if not (0 <= zh_start <= zh_end < len(payload["zh_paragraphs"])):
            raise HTTPException(status_code=400, detail="report Chinese range out of bounds")
        if not (0 <= en_start <= en_end < len(payload["en_paragraphs"])):
            raise HTTPException(status_code=400, detail="report English range out of bounds")
        item = store.add_anchor(
            project_id,
            zh_chapter_index=request.chapter_index,
            zh_start=zh_start,
            zh_end=zh_end,
            en_start=en_start,
            en_end=en_end,
            kind="mismatch_report",
            confirmed=False,
            note=request.note,
            payload={"cache_key": request.cache_key},
        )
        return {"report": item, "reports": store.list_anchors(project_id, request.chapter_index)}

    @app.post("/api/projects/{project_id}/jobs/prefetch")
    def prefetch_job(project_id: int, request: JobRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        _project_overview_or_404(store, project_id)
        active_job = store.get_active_job(project_id, "prefetch")
        if active_job is not None:
            return {"job": active_job, "reused": True}
        job = store.create_job(project_id, "prefetch", request.model_dump())
        background_tasks.add_task(
            _background_prefetch,
            store,
            project_id,
            int(job["id"]),
            start_chapter=request.chapter_index or 0,
            count=request.count,
            allow_llm=request.allow_llm,
            llm_policy=request.llm_policy,
        )
        return {"job": job, "reused": False}

    @app.post("/api/projects/{project_id}/jobs/align-remaining")
    def align_remaining(project_id: int, request: JobRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        ctx = _project_context(store, project_id)
        active_job = store.get_active_job(project_id, "align_remaining")
        if active_job is not None:
            return {"job": active_job, "reused": True}
        job = store.create_job(project_id, "align_remaining", request.model_dump())
        background_tasks.add_task(
            _background_prefetch,
            store,
            project_id,
            int(job["id"]),
            start_chapter=request.chapter_index or 0,
            count=len(ctx["zh_chapters"]),
            allow_llm=request.allow_llm,
            llm_policy=request.llm_policy,
        )
        return {"job": job, "reused": False}

    @app.get("/api/projects/{project_id}/jobs")
    def list_jobs(project_id: int) -> Dict[str, Any]:
        return {"jobs": store.list_jobs(project_id)}

    @app.get("/api/projects/{project_id}/export")
    def export_project(project_id: int) -> Dict[str, Any]:
        return store.export_project_snapshot(project_id)

    return app


app = create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="DuReading v2 FastAPI server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("web_server:app", host="0.0.0.0", port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
