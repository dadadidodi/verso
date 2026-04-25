from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from web_server import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]


def _range_contains(ranges: list[list[int]], zh_index: int, en_index: int) -> bool:
    start, end = ranges[zh_index]
    return start <= en_index <= end


async def _upload_middlemarch_pair(client: httpx.AsyncClient) -> tuple[int, int]:
    zh_data = (REPO_ROOT / "data" / "CnMiddlemarch.epub").read_bytes()
    en_data = (REPO_ROOT / "data" / "EnMiddlemarch.epub").read_bytes()
    zh_resp = await client.post(
        "/api/books",
        data={"language": "zh"},
        files={"file": ("CnMiddlemarch.epub", zh_data, "application/epub+zip")},
    )
    en_resp = await client.post(
        "/api/books",
        data={"language": "en"},
        files={"file": ("EnMiddlemarch.epub", en_data, "application/epub+zip")},
    )
    assert zh_resp.status_code == 200
    assert en_resp.status_code == 200
    return int(zh_resp.json()["book"]["id"]), int(en_resp.json()["book"]["id"])


def _empty_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    return buf.getvalue()


def test_upload_bad_epub_returns_400(tmp_path: Path) -> None:
    app = create_app(tmp_path / "storage")

    async def run_flow() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            not_zip_resp = await client.post(
                "/api/books",
                data={"language": "zh"},
                files={"file": ("bad.epub", b"not an epub", "application/epub+zip")},
            )
            assert not_zip_resp.status_code == 400
            assert "epub" in str(not_zip_resp.json()["detail"]).lower()

            broken_epub_resp = await client.post(
                "/api/books",
                data={"language": "en"},
                files={"file": ("empty.epub", _empty_zip_bytes(), "application/epub+zip")},
            )
            assert broken_epub_resp.status_code == 400
            assert "epub" in str(broken_epub_resp.json()["detail"]).lower()

    asyncio.run(run_flow())


def test_project_and_mapping_validation_errors_do_not_write_bad_state(tmp_path: Path) -> None:
    app = create_app(tmp_path / "storage")

    async def run_flow() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            missing_resp = await client.post("/api/projects", json={"zh_book_id": 9999, "en_book_id": 10000})
            assert missing_resp.status_code in {400, 404}
            assert (await client.get("/api/projects")).json()["projects"] == []

            zh_book_id, en_book_id = await _upload_middlemarch_pair(client)

            swapped_resp = await client.post(
                "/api/projects",
                json={"zh_book_id": en_book_id, "en_book_id": zh_book_id},
            )
            assert swapped_resp.status_code == 400
            assert (await client.get("/api/projects")).json()["projects"] == []

            project_resp = await client.post(
                "/api/projects",
                json={"zh_book_id": zh_book_id, "en_book_id": en_book_id},
            )
            assert project_resp.status_code == 200
            project_id = project_resp.json()["project"]["id"]

            suggest_resp = await client.post(f"/api/projects/{project_id}/chapter-mapping/suggest?allow_llm=false")
            assert suggest_resp.status_code == 200
            original_mappings = suggest_resp.json()["mappings"]
            assert original_mappings

            bad_zh_payload = {
                "mappings": [
                    {
                        **original_mappings[0],
                        "zh_chapter_index": 99999,
                    }
                ]
            }
            bad_zh_resp = await client.put(
                f"/api/projects/{project_id}/chapter-mapping",
                json=bad_zh_payload,
            )
            assert bad_zh_resp.status_code == 400
            after_bad_zh = await client.get(f"/api/projects/{project_id}/chapter-mapping")
            assert after_bad_zh.json()["mappings"] == original_mappings

            bad_en_payload = {
                "mappings": [
                    {
                        **original_mappings[0],
                        "en_chapter_index": 99999,
                    }
                ]
            }
            bad_en_resp = await client.put(
                f"/api/projects/{project_id}/chapter-mapping",
                json=bad_en_payload,
            )
            assert bad_en_resp.status_code == 400
            after_bad_en = await client.get(f"/api/projects/{project_id}/chapter-mapping")
            assert after_bad_en.json()["mappings"] == original_mappings

            duplicate_payload = {"mappings": [original_mappings[0], original_mappings[0]]}
            duplicate_resp = await client.put(
                f"/api/projects/{project_id}/chapter-mapping",
                json=duplicate_payload,
            )
            assert duplicate_resp.status_code == 400
            after_duplicate = await client.get(f"/api/projects/{project_id}/chapter-mapping")
            assert after_duplicate.json()["mappings"] == original_mappings

    asyncio.run(run_flow())


def test_active_background_jobs_are_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(tmp_path / "storage")

    import web_server as web_server_module

    monkeypatch.setattr(web_server_module, "_background_prefetch", lambda *args, **kwargs: None)

    async def run_flow() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            zh_book_id, en_book_id = await _upload_middlemarch_pair(client)
            project_resp = await client.post(
                "/api/projects",
                json={"zh_book_id": zh_book_id, "en_book_id": en_book_id},
            )
            project_id = project_resp.json()["project"]["id"]

            first_prefetch = await client.post(
                f"/api/projects/{project_id}/jobs/prefetch",
                json={"chapter_index": 0, "count": 2, "allow_llm": False, "llm_policy": "off"},
            )
            second_prefetch = await client.post(
                f"/api/projects/{project_id}/jobs/prefetch",
                json={"chapter_index": 0, "count": 2, "allow_llm": False, "llm_policy": "off"},
            )
            assert first_prefetch.status_code == 200
            assert second_prefetch.status_code == 200
            assert first_prefetch.json()["reused"] is False
            assert second_prefetch.json()["reused"] is True
            assert second_prefetch.json()["job"]["id"] == first_prefetch.json()["job"]["id"]

            first_remaining = await client.post(
                f"/api/projects/{project_id}/jobs/align-remaining",
                json={"chapter_index": 0, "count": 2, "allow_llm": False, "llm_policy": "off"},
            )
            second_remaining = await client.post(
                f"/api/projects/{project_id}/jobs/align-remaining",
                json={"chapter_index": 0, "count": 2, "allow_llm": False, "llm_policy": "off"},
            )
            assert first_remaining.status_code == 200
            assert second_remaining.status_code == 200
            assert first_remaining.json()["reused"] is False
            assert second_remaining.json()["reused"] is True
            assert second_remaining.json()["job"]["id"] == first_remaining.json()["job"]["id"]

            jobs = (await client.get(f"/api/projects/{project_id}/jobs")).json()["jobs"]
            active_jobs = [job for job in jobs if job["status"] in {"pending", "running"}]
            assert len(active_jobs) == 2
            assert {job["type"] for job in active_jobs} == {"prefetch", "align_remaining"}

    asyncio.run(run_flow())


def test_v2_project_flow(tmp_path: Path) -> None:
    app = create_app(tmp_path / "storage")
    zh_data = (REPO_ROOT / "data" / "CnMiddlemarch.epub").read_bytes()
    en_data = (REPO_ROOT / "data" / "EnMiddlemarch.epub").read_bytes()

    async def run_flow() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            root_resp = await client.get("/")
            app_js_resp = await client.get("/app.js")
            logic_js_resp = await client.get("/frontend_logic.js")
            styles_resp = await client.get("/styles.css")
            assert root_resp.status_code == 200
            assert app_js_resp.status_code == 200
            assert logic_js_resp.status_code == 200
            assert styles_resp.status_code == 200

            zh_resp = await client.post(
                "/api/books",
                data={"language": "zh"},
                files={"file": ("CnMiddlemarch.epub", zh_data, "application/epub+zip")},
            )
            en_resp = await client.post(
                "/api/books",
                data={"language": "en"},
                files={"file": ("EnMiddlemarch.epub", en_data, "application/epub+zip")},
            )
            assert zh_resp.status_code == 200
            assert en_resp.status_code == 200
            zh_book_id = zh_resp.json()["book"]["id"]
            en_book_id = en_resp.json()["book"]["id"]

            duplicate_resp = await client.post(
                "/api/books",
                data={"language": "zh"},
                files={"file": ("CnMiddlemarch.epub", zh_data, "application/epub+zip")},
            )
            assert duplicate_resp.status_code == 200
            assert duplicate_resp.json()["book"]["id"] == zh_book_id

            create_resp = await client.post("/api/projects", json={"zh_book_id": zh_book_id, "en_book_id": en_book_id})
            assert create_resp.status_code == 200
            project_id = create_resp.json()["project"]["id"]

            suggest_resp = await client.post(f"/api/projects/{project_id}/chapter-mapping/suggest?allow_llm=false")
            assert suggest_resp.status_code == 200
            suggest_payload = suggest_resp.json()
            mappings = suggest_payload["mappings"]
            assert mappings
            assert len(mappings) >= 2
            assert suggest_payload["strategy"] == "fallback"
            assert suggest_payload["fallback_reason"]

            chapters_resp = await client.get(f"/api/projects/{project_id}/chapters")
            assert chapters_resp.status_code == 200
            chapters_payload = chapters_resp.json()
            chapters = chapters_payload["chapters"]
            assert chapters
            assert chapters_payload["stats"]["en_chapter_count"] >= 1

            overview_resp = await client.get(f"/api/projects/{project_id}")
            assert overview_resp.status_code == 200
            overview = overview_resp.json()
            assert overview["en_chapters"]
            assert overview["en_chapters"][0]["title"]

            manual_target = 3 if len(chapters) > 3 else (1 if len(chapters) > 1 else 0)
            override_en_index = 11 if chapters_payload["stats"]["en_chapter_count"] > 11 else (
                1 if chapters[manual_target]["mapped_en_chapter_index"] != 1 else 0
            )
            override_payload = {
                "mappings": [
                    {
                        "zh_chapter_index": item["zh_chapter_index"],
                        "en_chapter_index": (
                            override_en_index
                            if item["zh_chapter_index"] == manual_target
                            else item["en_chapter_index"]
                        ),
                        "source": "manual" if item["zh_chapter_index"] == manual_target else item["source"],
                        "confidence": item["confidence"],
                        "reason": "manual_override" if item["zh_chapter_index"] == manual_target else item["reason"],
                        "alternatives": item.get("alternatives", []),
                        "confirmed": False,
                    }
                    for item in mappings
                ]
            }
            override_resp = await client.put(f"/api/projects/{project_id}/chapter-mapping", json=override_payload)
            assert override_resp.status_code == 200
            override_map = override_resp.json()["mappings"]
            changed = next(item for item in override_map if item["zh_chapter_index"] == manual_target)
            assert changed["en_chapter_index"] == override_en_index
            assert changed["source"] == "manual"

            confirm_mapping_resp = await client.post(f"/api/projects/{project_id}/chapter-mapping/confirm")
            assert confirm_mapping_resp.status_code == 200
            confirmed_mapping = next(
                item for item in confirm_mapping_resp.json()["mappings"] if item["zh_chapter_index"] == manual_target
            )
            assert confirmed_mapping["confirmed"] is True

            align_resp = await client.post(
                f"/api/projects/{project_id}/chapters/{manual_target}/align",
                json={"force": False, "use_anchors": True, "allow_llm": False, "llm_policy": "off"},
            )
            assert align_resp.status_code == 200
            align_payload = align_resp.json()
            assert align_payload["state"] == "draft"
            assert align_payload["local_sync_map"]
            assert align_payload["en_ranges_by_zh"]
            assert align_payload["mapped_en_chapter_index"] == override_en_index
            assert align_payload["metrics"]["alignment_source"] == "heuristic"
            assert align_payload["metrics"]["llm_policy"] == "off"
            assert any(item["reason"] == "llm_disabled" for item in align_payload["metrics"]["decision_log"])

            alignment_view_resp = await client.get(f"/api/projects/{project_id}/chapters/{manual_target}/alignment")
            assert alignment_view_resp.status_code == 200
            alignment_view = alignment_view_resp.json()
            assert alignment_view["alignment"]["en_ranges_by_zh"]
            assert alignment_view["alignment"]["metrics"]["alignment_source"] == "heuristic"

            reader_before_anchor = await client.get(f"/api/projects/{project_id}/reader/chapters/{manual_target}")
            assert reader_before_anchor.status_code == 200
            reader_before_payload = reader_before_anchor.json()
            assert len(reader_before_payload["en_ranges_by_zh"]) == len(reader_before_payload["zh_paragraphs"])
            zh_anchor = min(1, max(0, len(reader_before_payload["zh_paragraphs"]) - 1))
            en_anchor = min(1, max(0, len(reader_before_payload["en_paragraphs"]) - 1))

            anchor_resp = await client.post(
                f"/api/projects/{project_id}/anchors",
                json={
                    "zh_chapter_index": manual_target,
                    "zh_paragraph_index": zh_anchor,
                    "en_paragraph_index": en_anchor,
                    "kind": "hard",
                    "confirmed": True,
                },
            )
            assert anchor_resp.status_code == 200
            anchors = anchor_resp.json()["anchors"]
            assert any(
                item["zh_paragraph_index"] == zh_anchor and item["en_paragraph_index"] == en_anchor
                for item in anchors
            )
            anchor_id = next(
                item["id"]
                for item in anchors
                if item["zh_paragraph_index"] == zh_anchor and item["en_paragraph_index"] == en_anchor
            )

            list_anchor_resp = await client.get(
                f"/api/projects/{project_id}/anchors",
                params={"zh_chapter_index": manual_target},
            )
            assert list_anchor_resp.status_code == 200
            assert any(item["id"] == anchor_id for item in list_anchor_resp.json()["anchors"])
            single_anchor = next(item for item in list_anchor_resp.json()["anchors"] if item["id"] == anchor_id)
            assert single_anchor["zh_start"] == zh_anchor
            assert single_anchor["zh_end"] == zh_anchor
            assert single_anchor["en_start"] == en_anchor
            assert single_anchor["en_end"] == en_anchor

            zh_range_start = min(zh_anchor + 2, len(reader_before_payload["zh_paragraphs"]) - 2)
            en_range_start = min(en_anchor + 2, len(reader_before_payload["en_paragraphs"]) - 2)
            range_anchor_resp = await client.post(
                f"/api/projects/{project_id}/anchors",
                json={
                    "zh_chapter_index": manual_target,
                    "zh_start": zh_range_start,
                    "zh_end": zh_range_start + 1,
                    "en_start": en_range_start,
                    "en_end": en_range_start + 1,
                    "kind": "hard",
                    "confirmed": True,
                },
            )
            assert range_anchor_resp.status_code == 200
            range_anchor = next(
                item for item in range_anchor_resp.json()["anchors"]
                if item["zh_start"] == zh_range_start and item["zh_end"] == zh_range_start + 1
            )
            assert range_anchor["en_start"] == en_range_start
            assert range_anchor["en_end"] == en_range_start + 1

            conflict_resp = await client.post(
                f"/api/projects/{project_id}/anchors",
                json={
                    "zh_chapter_index": manual_target,
                    "zh_start": zh_range_start,
                    "zh_end": zh_range_start,
                    "en_start": en_range_start + 1,
                    "en_end": en_range_start + 1,
                    "kind": "hard",
                    "confirmed": True,
                },
            )
            assert conflict_resp.status_code == 400

            regenerate_resp = await client.post(
                f"/api/projects/{project_id}/chapters/{manual_target}/regenerate",
                json={"force": True, "use_anchors": True, "allow_llm": False},
            )
            assert regenerate_resp.status_code == 200
            regenerate_payload = regenerate_resp.json()
            assert regenerate_payload["local_sync_map"][zh_anchor] == en_anchor
            assert _range_contains(regenerate_payload["en_ranges_by_zh"], zh_anchor, en_anchor)
            assert any(
                block["reason"] == "hard_anchor"
                and block["zh_start"] == zh_range_start + 1
                and block["zh_end"] == zh_range_start + 2
                and block["en_start"] == en_range_start + 1
                and block["en_end"] == en_range_start + 2
                for block in regenerate_payload["blocks"]
            )
            assert _range_contains(regenerate_payload["en_ranges_by_zh"], zh_range_start, en_range_start)
            assert _range_contains(regenerate_payload["en_ranges_by_zh"], zh_range_start + 1, en_range_start + 1)

            confirm_resp = await client.post(f"/api/projects/{project_id}/chapters/{manual_target}/confirm")
            assert confirm_resp.status_code == 200
            assert confirm_resp.json()["alignment"]["state"] == "confirmed"
            assert _range_contains(confirm_resp.json()["alignment"]["en_ranges_by_zh"], zh_anchor, en_anchor)

            reader_resp = await client.get(f"/api/projects/{project_id}/reader/chapters/{manual_target}")
            assert reader_resp.status_code == 200
            reader_payload = reader_resp.json()
            assert reader_payload["zh_paragraphs"]
            assert reader_payload["en_paragraphs"]
            assert reader_payload["local_sync_map"]
            assert reader_payload["local_sync_map"][zh_anchor] == en_anchor
            assert len(reader_payload["en_ranges_by_zh"]) == len(reader_payload["zh_paragraphs"])
            assert _range_contains(reader_payload["en_ranges_by_zh"], zh_anchor, en_anchor)

            mismatch_resp = await client.post(
                f"/api/projects/{project_id}/mismatch-reports",
                json={
                    "chapter_index": manual_target,
                    "zh_start": zh_anchor,
                    "zh_end": zh_anchor,
                    "en_start": en_anchor,
                    "en_end": en_anchor,
                    "cache_key": regenerate_payload["metrics"].get("cache_key", ""),
                    "note": "pytest mismatch",
                },
            )
            assert mismatch_resp.status_code == 200
            assert mismatch_resp.json()["report"]["kind"] == "mismatch_report"

            prefetch_resp = await client.post(
                f"/api/projects/{project_id}/jobs/prefetch",
                json={"chapter_index": 0, "count": 2, "allow_llm": False, "llm_policy": "off"},
            )
            assert prefetch_resp.status_code == 200
            jobs_resp = await client.get(f"/api/projects/{project_id}/jobs")
            assert jobs_resp.status_code == 200
            jobs = jobs_resp.json()["jobs"]
            assert jobs
            assert jobs[0]["status"] in {"completed", "pending", "running"}
            assert jobs[0]["type"] == "prefetch"
            assert jobs[0]["payload"]["llm_policy"] == "off"
            assert "done_count" in jobs[0]["result"]
            assert "total_count" in jobs[0]["result"]

            remaining_resp = await client.post(
                f"/api/projects/{project_id}/jobs/align-remaining",
                json={"chapter_index": 0, "count": 2, "allow_llm": False, "llm_policy": "off"},
            )
            assert remaining_resp.status_code == 200
            jobs_resp = await client.get(f"/api/projects/{project_id}/jobs")
            assert jobs_resp.status_code == 200
            align_job = next(job for job in jobs_resp.json()["jobs"] if job["type"] == "align_remaining")
            assert align_job["status"] in {"completed", "pending", "running"}
            assert align_job["payload"]["llm_policy"] == "off"
            assert "done_count" in align_job["result"]
            assert "total_count" in align_job["result"]

            delete_anchor_resp = await client.delete(
                f"/api/projects/{project_id}/anchors/{anchor_id}",
                params={"zh_chapter_index": manual_target},
            )
            assert delete_anchor_resp.status_code == 200
            assert not any(item["id"] == anchor_id for item in delete_anchor_resp.json()["anchors"])

            skip_resp = await client.post(f"/api/projects/{project_id}/chapters/0/skip")
            assert skip_resp.status_code == 200
            assert skip_resp.json()["alignment"]["state"] == "skipped"
            assert skip_resp.json()["alignment"]["en_ranges_by_zh"]

            export_resp = await client.get(f"/api/projects/{project_id}/export")
            assert export_resp.status_code == 200
            export_payload = export_resp.json()
            assert export_payload["version"] == 2
            assert isinstance(export_payload["anchors"], list)
            assert export_payload["chapter_alignments"]

            delete_project_resp = await client.delete(f"/api/projects/{project_id}")
            assert delete_project_resp.status_code == 200
            assert delete_project_resp.json()["deleted"] is True

            deleted_project_resp = await client.get(f"/api/projects/{project_id}")
            assert deleted_project_resp.status_code == 404

            projects_resp = await client.get("/api/projects")
            assert projects_resp.status_code == 200
            assert projects_resp.json()["projects"] == []

            books_resp = await client.get("/api/books")
            assert books_resp.status_code == 200
            assert len(books_resp.json()["books"]) == 2
            assert {book["id"] for book in books_resp.json()["books"]} == {zh_book_id, en_book_id}

            assert not (tmp_path / "storage" / "projects" / str(project_id)).exists()

            cascade_project_resp = await client.post(
                "/api/projects",
                json={"zh_book_id": zh_book_id, "en_book_id": en_book_id},
            )
            assert cascade_project_resp.status_code == 200
            cascade_project_id = cascade_project_resp.json()["project"]["id"]
            assert (tmp_path / "storage" / "projects" / str(cascade_project_id)).exists()

            delete_book_resp = await client.delete(f"/api/books/{zh_book_id}")
            assert delete_book_resp.status_code == 200
            delete_book_payload = delete_book_resp.json()
            assert delete_book_payload["deleted"] is True
            assert delete_book_payload["book"]["id"] == zh_book_id
            assert delete_book_payload["deleted_project_ids"] == [cascade_project_id]
            assert not (tmp_path / "storage" / "books" / str(zh_book_id)).exists()
            assert not (tmp_path / "storage" / "projects" / str(cascade_project_id)).exists()

            deleted_book_resp = await client.get(f"/api/books/{zh_book_id}")
            assert deleted_book_resp.status_code == 404
            deleted_cascade_project_resp = await client.get(f"/api/projects/{cascade_project_id}")
            assert deleted_cascade_project_resp.status_code == 404

            books_after_delete_resp = await client.get("/api/books")
            assert books_after_delete_resp.status_code == 200
            books_after_delete = books_after_delete_resp.json()["books"]
            assert len(books_after_delete) == 1
            assert books_after_delete[0]["id"] == en_book_id

    asyncio.run(run_flow())


def test_align_chapter_falls_back_when_llm_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(tmp_path / "storage")
    zh_data = (REPO_ROOT / "data" / "CnMiddlemarch.epub").read_bytes()
    en_data = (REPO_ROOT / "data" / "EnMiddlemarch.epub").read_bytes()

    import web_server as web_server_module

    original_align = web_server_module.align_chapter_hybrid
    calls: list[bool] = []

    def fake_align(*args, **kwargs):
        allow_llm = bool(kwargs.get("allow_llm"))
        calls.append(allow_llm)
        if allow_llm:
            raise RuntimeError("AI API HTTP 429: rate_limit_exceeded")
        return original_align(*args, **kwargs)

    monkeypatch.setattr(web_server_module, "align_chapter_hybrid", fake_align)

    async def run_flow() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            zh_resp = await client.post(
                "/api/books",
                data={"language": "zh"},
                files={"file": ("CnMiddlemarch.epub", zh_data, "application/epub+zip")},
            )
            en_resp = await client.post(
                "/api/books",
                data={"language": "en"},
                files={"file": ("EnMiddlemarch.epub", en_data, "application/epub+zip")},
            )
            project_resp = await client.post(
                "/api/projects",
                json={"zh_book_id": zh_resp.json()["book"]["id"], "en_book_id": en_resp.json()["book"]["id"]},
            )
            project_id = project_resp.json()["project"]["id"]
            suggest_resp = await client.post(f"/api/projects/{project_id}/chapter-mapping/suggest?allow_llm=false")
            chapter_index = suggest_resp.json()["mappings"][0]["zh_chapter_index"]

            align_resp = await client.post(
                f"/api/projects/{project_id}/chapters/{chapter_index}/align",
                json={"force": False, "use_anchors": True, "allow_llm": True},
            )
            assert align_resp.status_code == 200
            payload = align_resp.json()
            assert payload["metrics"]["llm_rate_limited"] is True
            assert payload["metrics"]["alignment_source"] == "fallback"
            assert payload["metrics"]["llm_policy"] == "auto"
            assert "429" in payload["metrics"]["fallback_reason"]
            assert any(item["reason"] == "rate_limited_fallback" for item in payload["metrics"]["decision_log"])
            assert payload["local_sync_map"]
            assert payload["en_ranges_by_zh"]
            assert calls[:2] == [True, False]

    asyncio.run(run_flow())
