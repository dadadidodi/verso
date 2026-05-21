from __future__ import annotations

import json
from pathlib import Path

import pytest

from storage import VersoStore
from tools.export_reader_site import export_reader_site, password_hash


REPO_ROOT = Path(__file__).resolve().parents[1]
ZH_MIDDLEMARCH_EPUB = REPO_ROOT / "data" / "CnMiddlemarch.epub"
EN_MIDDLEMARCH_EPUB = REPO_ROOT / "data" / "EnMiddlemarch.epub"
requires_middlemarch_epubs = pytest.mark.skipif(
    not (ZH_MIDDLEMARCH_EPUB.exists() and EN_MIDDLEMARCH_EPUB.exists()),
    reason="local Middlemarch EPUB fixtures are not tracked",
)


def _chapter_lengths(store: VersoStore, project_id: int, chapter_index: int) -> tuple[int, int]:
    overview = store.build_project_overview(project_id)
    project = overview["project"]
    zh_paragraphs, _ = store.load_book_document(int(project["zh_book_id"]))
    en_paragraphs, en_chapters = store.load_book_document(int(project["en_book_id"]))
    chapter = overview["chapters"][chapter_index]
    en_chapter = en_chapters[int(chapter["mapped_en_chapter_index"])]
    zh_len = int(chapter["zh_end"]) - int(chapter["zh_start"]) + 1
    en_len = int(en_chapter["end"]) - int(en_chapter["start"]) + 1
    assert len(zh_paragraphs) >= zh_len
    assert len(en_paragraphs) >= en_len
    return zh_len, en_len


def _save_alignment(store: VersoStore, project_id: int, chapter_index: int, state: str) -> None:
    zh_len, en_len = _chapter_lengths(store, project_id, chapter_index)
    store.save_chapter_alignment(
        project_id,
        chapter_index,
        state=state,
        blocks=[
            {
                "zh_start": 1,
                "zh_end": zh_len,
                "en_start": 1,
                "en_end": en_len,
                "confidence": 0.9,
                "reason": "test_fixture",
            }
        ],
        local_sync_map=[0 for _ in range(zh_len)],
        review_items=[],
        metrics={
            "llm_calls": 99,
            "heuristic_segments": 88,
            "decision_log": [{"debug_label": "should_not_export"}],
            "alignment_source": "mixed",
        },
        cache_key=f"test:{chapter_index}:{state}",
    )


@requires_middlemarch_epubs
def test_export_reader_site_exports_draft_and_confirmed_safe_payload(tmp_path: Path) -> None:
    store = VersoStore(tmp_path / "storage")
    zh_book = store.create_or_get_book(
        language="zh",
        filename="CnMiddlemarch.epub",
        data=ZH_MIDDLEMARCH_EPUB.read_bytes(),
    )
    en_book = store.create_or_get_book(
        language="en",
        filename="EnMiddlemarch.epub",
        data=EN_MIDDLEMARCH_EPUB.read_bytes(),
    )
    project = store.create_project(
        zh_book_id=int(zh_book["id"]),
        en_book_id=int(en_book["id"]),
        alignment_engine_version="test",
        prompt_version="test",
    )
    project_id = int(project["id"])
    store.replace_chapter_mappings(
        project_id,
        [
            {
                "zh_chapter_index": 3,
                "en_chapter_index": 11,
                "source": "manual",
                "confidence": None,
                "reason": "test",
                "alternatives": [],
                "confirmed": True,
            },
            {
                "zh_chapter_index": 4,
                "en_chapter_index": 12,
                "source": "manual",
                "confidence": None,
                "reason": "test",
                "alternatives": [],
                "confirmed": True,
            },
        ],
        confirmed=True,
    )
    _save_alignment(store, project_id, 3, "confirmed")
    _save_alignment(store, project_id, 4, "draft")

    out_dir = tmp_path / "dist-reader"
    manifest = export_reader_site(
        project_id=project_id,
        out_dir=out_dir,
        reader_password_hash=password_hash("reader-pass"),
        reader_password_hashes=[password_hash("friend-pass")],
        storage_root=tmp_path / "storage",
    )

    assert manifest["reader_password_hash"] == password_hash("reader-pass")
    assert manifest["reader_password_hashes"] == [password_hash("reader-pass"), password_hash("friend-pass")]
    assert [item["chapter_index"] for item in manifest["chapters"]] == [3, 4]
    assert [item["alignment_state"] for item in manifest["chapters"]] == ["confirmed", "draft"]
    assert (out_dir / "index.html").exists()
    assert (out_dir / "reader.js").exists()
    assert (out_dir / "reader.css").exists()
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "chapters" / "3.json").exists()
    assert (out_dir / "chapters" / "4.json").exists()

    chapter_payload = json.loads((out_dir / "chapters" / "3.json").read_text(encoding="utf-8"))
    assert chapter_payload["chapter_index"] == 3
    assert chapter_payload["alignment_state"] == "confirmed"
    assert chapter_payload["zh_paragraphs"]
    assert chapter_payload["en_paragraphs"]
    assert len(chapter_payload["en_ranges_by_zh"]) == len(chapter_payload["zh_paragraphs"])
    assert "metrics" not in chapter_payload
    assert "decision_log" not in chapter_payload
    assert "anchors" not in chapter_payload
    assert "jobs" not in chapter_payload

    exported_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in out_dir.rglob("*")
        if path.is_file()
    )
    assert "OPENAI_API_KEY" not in exported_text
    assert "api_key" not in exported_text
    assert "should_not_export" not in exported_text
    assert "上传到书库" not in exported_text
    assert "Alignment Mode" not in exported_text
    assert "创建 anchor" not in exported_text
    reader_js = (out_dir / "reader.js").read_text(encoding="utf-8")
    reader_css = (out_dir / "reader.css").read_text(encoding="utf-8")
    assert "reader_password_hashes" in reader_js
    assert "lookup-close-btn" in reader_js
    assert "setLookupOpen" in reader_js
    assert "@media (max-width: 760px)" in reader_css
    assert "bottom: 0" in reader_css
    assert ".lookup-panel.is-open" in reader_css
    exported_manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert exported_manifest["reader_password_hashes"] == [password_hash("reader-pass"), password_hash("friend-pass")]


@requires_middlemarch_epubs
def test_export_reader_site_skips_missing_and_skipped_chapters(tmp_path: Path) -> None:
    store = VersoStore(tmp_path / "storage")
    zh_book = store.create_or_get_book(
        language="zh",
        filename="CnMiddlemarch.epub",
        data=ZH_MIDDLEMARCH_EPUB.read_bytes(),
    )
    en_book = store.create_or_get_book(
        language="en",
        filename="EnMiddlemarch.epub",
        data=EN_MIDDLEMARCH_EPUB.read_bytes(),
    )
    project = store.create_project(
        zh_book_id=int(zh_book["id"]),
        en_book_id=int(en_book["id"]),
        alignment_engine_version="test",
        prompt_version="test",
    )
    project_id = int(project["id"])
    store.replace_chapter_mappings(
        project_id,
        [
            {
                "zh_chapter_index": 3,
                "en_chapter_index": 11,
                "source": "manual",
                "confidence": None,
                "reason": "test",
                "alternatives": [],
                "confirmed": True,
            },
            {
                "zh_chapter_index": 4,
                "en_chapter_index": 12,
                "source": "manual",
                "confidence": None,
                "reason": "test",
                "alternatives": [],
                "confirmed": True,
            },
        ],
        confirmed=True,
    )
    _save_alignment(store, project_id, 3, "skipped")

    try:
        export_reader_site(
            project_id=project_id,
            out_dir=tmp_path / "dist-reader",
            reader_password_hash=password_hash("reader-pass"),
            storage_root=tmp_path / "storage",
        )
    except ValueError as exc:
        assert "no draft or confirmed chapters" in str(exc)
    else:
        raise AssertionError("expected export to fail without draft or confirmed chapters")
