from __future__ import annotations

import hashlib
import json
import sqlite3
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from book_import import (
    DocumentParseResult,
    chapter_from_dict,
    chapter_to_dict,
    extract_document_from_bytes,
    parser_version_for_format,
    source_filename_for_format,
)


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    if heuristic_segments > 0:
        return "heuristic"
    return "heuristic" if state in {"draft", "confirmed"} else "missing"


@dataclass
class StorageConfig:
    root: Path

    @property
    def db_path(self) -> Path:
        return self.root / "app.db"

    @property
    def books_dir(self) -> Path:
        return self.root / "books"

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"


class VersoStore:
    def __init__(self, root: Path | str = "storage") -> None:
        self.config = StorageConfig(Path(root).resolve())
        self.config.root.mkdir(parents=True, exist_ok=True)
        self.config.books_dir.mkdir(parents=True, exist_ok=True)
        self.config.projects_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.config.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    language TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_filename TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    epub_path TEXT NOT NULL,
                    source_format TEXT NOT NULL DEFAULT 'epub',
                    source_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS book_artifacts (
                    book_id INTEGER PRIMARY KEY,
                    paragraphs_path TEXT NOT NULL,
                    chapters_path TEXT NOT NULL,
                    chapter_count INTEGER NOT NULL,
                    paragraph_count INTEGER NOT NULL,
                    char_total INTEGER NOT NULL,
                    parser_version TEXT NOT NULL DEFAULT '',
                    parse_warnings_json TEXT NOT NULL DEFAULT '[]',
                    quality_stats_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zh_book_id INTEGER NOT NULL,
                    en_book_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    alignment_engine_version TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(zh_book_id) REFERENCES books(id) ON DELETE CASCADE,
                    FOREIGN KEY(en_book_id) REFERENCES books(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS chapter_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    zh_chapter_index INTEGER NOT NULL,
                    en_chapter_index INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL,
                    reason TEXT NOT NULL,
                    alternatives_json TEXT NOT NULL DEFAULT '[]',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, zh_chapter_index),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS chapter_alignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    zh_chapter_index INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    blocks_json TEXT NOT NULL,
                    local_sync_map_json TEXT NOT NULL,
                    review_items_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    cache_key TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, zh_chapter_index),
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS anchors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    zh_chapter_index INTEGER,
                    zh_paragraph_index INTEGER NOT NULL,
                    en_paragraph_index INTEGER NOT NULL,
                    zh_start INTEGER,
                    zh_end INTEGER,
                    en_start INTEGER,
                    en_end INTEGER,
                    kind TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 1,
                    note TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                """
            )
            book_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(books)").fetchall()
            }
            if "source_format" not in book_columns:
                conn.execute("ALTER TABLE books ADD COLUMN source_format TEXT NOT NULL DEFAULT 'epub'")
            if "source_path" not in book_columns:
                conn.execute("ALTER TABLE books ADD COLUMN source_path TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                UPDATE books
                SET source_format = COALESCE(NULLIF(source_format, ''), 'epub'),
                    source_path = COALESCE(NULLIF(source_path, ''), epub_path)
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(book_artifacts)").fetchall()
            }
            if "parser_version" not in columns:
                conn.execute("ALTER TABLE book_artifacts ADD COLUMN parser_version TEXT NOT NULL DEFAULT ''")
            if "parse_warnings_json" not in columns:
                conn.execute("ALTER TABLE book_artifacts ADD COLUMN parse_warnings_json TEXT NOT NULL DEFAULT '[]'")
            if "quality_stats_json" not in columns:
                conn.execute("ALTER TABLE book_artifacts ADD COLUMN quality_stats_json TEXT NOT NULL DEFAULT '{}'")
            anchor_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(anchors)").fetchall()
            }
            for column in ("zh_start", "zh_end", "en_start", "en_end"):
                if column not in anchor_columns:
                    conn.execute(f"ALTER TABLE anchors ADD COLUMN {column} INTEGER")
            if "note" not in anchor_columns:
                conn.execute("ALTER TABLE anchors ADD COLUMN note TEXT NOT NULL DEFAULT ''")
            if "payload_json" not in anchor_columns:
                conn.execute("ALTER TABLE anchors ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'")
            conn.execute(
                """
                UPDATE anchors
                SET
                    zh_start = COALESCE(zh_start, zh_paragraph_index),
                    zh_end = COALESCE(zh_end, zh_paragraph_index),
                    en_start = COALESCE(en_start, en_paragraph_index),
                    en_end = COALESCE(en_end, en_paragraph_index)
                """
            )

    def _book_dir(self, book_id: int) -> Path:
        path = self.config.books_dir / str(book_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _project_dir(self, project_id: int) -> Path:
        path = self.config.projects_dir / str(project_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _row_to_dict(self, row: sqlite3.Row | None) -> Dict[str, Any] | None:
        return None if row is None else dict(row)

    def _write_book_artifacts(
        self,
        conn: sqlite3.Connection,
        *,
        book_id: int,
        filename: str,
        data: bytes,
        parsed: DocumentParseResult,
    ) -> None:
        paragraphs = parsed.paragraphs
        chapters = parsed.chapters
        book_dir = self._book_dir(book_id)
        source_path = book_dir / source_filename_for_format(parsed.source_format)
        paras_path = book_dir / "paragraphs.json"
        chapters_path = book_dir / "chapters.json"
        source_path.write_bytes(data)
        paras_path.write_text(json.dumps(paragraphs, ensure_ascii=False, indent=2), encoding="utf-8")
        chapters_path.write_text(
            json.dumps(
                [chapter_to_dict(c) for c in chapters],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        epub_path_value = str(source_path) if parsed.source_format == "epub" else ""
        conn.execute(
            """
            UPDATE books
            SET source_filename = ?, epub_path = ?, source_format = ?, source_path = ?
            WHERE id = ?
            """,
            (filename, epub_path_value, parsed.source_format, str(source_path), book_id),
        )
        conn.execute(
            """
            UPDATE book_artifacts
            SET paragraphs_path = ?, chapters_path = ?, chapter_count = ?, paragraph_count = ?,
                char_total = ?, parser_version = ?, parse_warnings_json = ?, quality_stats_json = ?
            WHERE book_id = ?
            """,
            (
                str(paras_path),
                str(chapters_path),
                len(chapters),
                len(paragraphs),
                sum(len(p) for p in paragraphs),
                parsed.parser_version,
                json.dumps(parsed.parse_warnings, ensure_ascii=False),
                json.dumps(parsed.quality_stats, ensure_ascii=False),
                book_id,
            ),
        )

    def _refresh_book_artifacts(self, conn: sqlite3.Connection, *, book_id: int, data: bytes, book: Dict[str, Any]) -> None:
        parsed = extract_document_from_bytes(
            data,
            filename=str(book.get("source_filename") or source_filename_for_format(str(book.get("source_format") or "epub"))),
            content_type="",
            language=str(book.get("language") or ""),
        )
        self._write_book_artifacts(
            conn,
            book_id=book_id,
            filename=str(book.get("source_filename") or source_filename_for_format(parsed.source_format)),
            data=data,
            parsed=parsed,
        )

    def create_or_get_book_from_parsed(
        self,
        *,
        language: str,
        filename: str,
        data: bytes,
        parsed: DocumentParseResult,
    ) -> Dict[str, Any]:
        if not parsed.paragraphs:
            raise ValueError("no readable paragraphs extracted")
        if not parsed.chapters:
            raise ValueError("no readable chapters extracted")
        content_hash = sha256_bytes(data)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT b.*, a.chapter_count, a.paragraph_count, a.char_total, a.parser_version,
                       a.parse_warnings_json, a.quality_stats_json
                FROM books b
                JOIN book_artifacts a ON a.book_id = b.id
                WHERE b.content_hash = ?
                """,
                (content_hash,),
            ).fetchone()
            if row is not None:
                existing = dict(row)
                if existing.get("parser_version") == parsed.parser_version:
                    return existing
                book_id = int(existing["id"])
                self._write_book_artifacts(conn, book_id=book_id, filename=filename, data=data, parsed=parsed)
                refreshed = conn.execute(
                    """
                    SELECT b.*, a.chapter_count, a.paragraph_count, a.char_total, a.parser_version,
                           a.parse_warnings_json, a.quality_stats_json
                    FROM books b
                    JOIN book_artifacts a ON a.book_id = b.id
                    WHERE b.id = ?
                    """,
                    (book_id,),
                ).fetchone()
                return dict(refreshed) if refreshed is not None else existing

        title = Path(filename).stem or f"{language.upper()} Book"
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO books(language, title, source_filename, content_hash, epub_path, source_format, source_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (language, title, filename, content_hash, "", parsed.source_format, "", now),
            )
            book_id = int(cur.lastrowid)
            self._write_book_artifacts(conn, book_id=book_id, filename=filename, data=data, parsed=parsed)
            conn.execute(
                """
                INSERT INTO book_artifacts(
                    book_id, paragraphs_path, chapters_path, chapter_count, paragraph_count, char_total,
                    parser_version, parse_warnings_json, quality_stats_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    str(self._book_dir(book_id) / "paragraphs.json"),
                    str(self._book_dir(book_id) / "chapters.json"),
                    len(parsed.chapters),
                    len(parsed.paragraphs),
                    sum(len(p) for p in parsed.paragraphs),
                    parsed.parser_version,
                    json.dumps(parsed.parse_warnings, ensure_ascii=False),
                    json.dumps(parsed.quality_stats, ensure_ascii=False),
                ),
            )
            row = conn.execute(
                """
                SELECT b.*, a.chapter_count, a.paragraph_count, a.char_total, a.parser_version,
                       a.parse_warnings_json, a.quality_stats_json
                FROM books b
                JOIN book_artifacts a ON a.book_id = b.id
                WHERE b.id = ?
                """,
                (book_id,),
            ).fetchone()
            return dict(row) if row is not None else {}

    def create_or_get_book(
        self,
        *,
        language: str,
        filename: str,
        data: bytes,
        content_type: str = "",
    ) -> Dict[str, Any]:
        parsed = extract_document_from_bytes(data, filename=filename, content_type=content_type, language=language)
        return self.create_or_get_book_from_parsed(
            language=language,
            filename=filename,
            data=data,
            parsed=parsed,
        )

    def list_books(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT b.*, a.chapter_count, a.paragraph_count, a.char_total, a.parser_version,
                       a.parse_warnings_json, a.quality_stats_json
                FROM books b
                JOIN book_artifacts a ON a.book_id = b.id
                ORDER BY b.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def get_book(self, book_id: int) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT b.*, a.chapter_count, a.paragraph_count, a.char_total, a.parser_version,
                       a.paragraphs_path, a.chapters_path, a.parse_warnings_json, a.quality_stats_json
                FROM books b
                JOIN book_artifacts a ON a.book_id = b.id
                WHERE b.id = ?
                """,
                (book_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"book {book_id} not found")
            return dict(row)

    def delete_book(self, book_id: int) -> Dict[str, Any]:
        book = self.get_book(book_id)
        book_dir = self.config.books_dir / str(book_id)
        with self._connect() as conn:
            project_rows = conn.execute(
                "SELECT id FROM projects WHERE zh_book_id = ? OR en_book_id = ?",
                (book_id, book_id),
            ).fetchall()
            deleted_project_ids = [int(row["id"]) for row in project_rows]
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))

        for project_id in deleted_project_ids:
            project_dir = self.config.projects_dir / str(project_id)
            if project_dir.exists():
                shutil.rmtree(project_dir)
        if book_dir.exists():
            shutil.rmtree(book_dir)

        return {
            "book": book,
            "deleted_project_ids": deleted_project_ids,
        }

    def load_book_document(self, book_id: int) -> Tuple[List[str], List[Dict[str, Any]]]:
        book = self.get_book(book_id)
        source_format = str(book.get("source_format") or "epub")
        expected_parser_version = parser_version_for_format(source_format)
        if book.get("parser_version") != expected_parser_version:
            source_path = Path(book.get("source_path") or book.get("epub_path") or "")
            if source_path.exists():
                with self._connect() as conn:
                    self._refresh_book_artifacts(conn, book_id=book_id, data=source_path.read_bytes(), book=book)
                book = self.get_book(book_id)
        paragraphs = json.loads(Path(book["paragraphs_path"]).read_text(encoding="utf-8"))
        chapters = json.loads(Path(book["chapters_path"]).read_text(encoding="utf-8"))
        return paragraphs, chapters

    def create_project(
        self,
        *,
        zh_book_id: int,
        en_book_id: int,
        alignment_engine_version: str,
        prompt_version: str,
    ) -> Dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO projects(zh_book_id, en_book_id, status, alignment_engine_version, prompt_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (zh_book_id, en_book_id, "new", alignment_engine_version, prompt_version, now, now),
            )
            project_id = int(cur.lastrowid)
            self._project_dir(project_id)
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return dict(row) if row is not None else {}

    def delete_project(self, project_id: int) -> Dict[str, Any]:
        project = self.get_project(project_id)
        project_dir = self.config.projects_dir / str(project_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        if project_dir.exists():
            shutil.rmtree(project_dir)
        return project

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.*,
                    zb.title AS zh_title,
                    eb.title AS en_title,
                    (SELECT COUNT(*) FROM chapter_mappings cm WHERE cm.project_id = p.id) AS mapping_count,
                    (SELECT COUNT(*) FROM chapter_alignments ca WHERE ca.project_id = p.id AND ca.state = 'confirmed') AS confirmed_count,
                    (SELECT COUNT(*) FROM chapter_alignments ca WHERE ca.project_id = p.id) AS aligned_count
                FROM projects p
                JOIN books zb ON zb.id = p.zh_book_id
                JOIN books eb ON eb.id = p.en_book_id
                ORDER BY p.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def get_project(self, project_id: int) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    p.*,
                    zb.title AS zh_title,
                    zb.language AS zh_language,
                    eb.title AS en_title,
                    eb.language AS en_language
                FROM projects p
                JOIN books zb ON zb.id = p.zh_book_id
                JOIN books eb ON eb.id = p.en_book_id
                WHERE p.id = ?
                """,
                (project_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"project {project_id} not found")
            return dict(row)

    def get_project_books(self, project_id: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        project = self.get_project(project_id)
        return self.get_book(int(project["zh_book_id"])), self.get_book(int(project["en_book_id"]))

    def touch_project(self, project_id: int, *, status: Optional[str] = None) -> None:
        now = utc_now()
        with self._connect() as conn:
            if status is None:
                conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
            else:
                conn.execute(
                    "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, project_id),
                )

    def replace_chapter_mappings(self, project_id: int, items: Sequence[Dict[str, Any]], *, confirmed: bool = False) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute("DELETE FROM chapter_mappings WHERE project_id = ?", (project_id,))
            for item in items:
                conn.execute(
                    """
                    INSERT INTO chapter_mappings(
                        project_id, zh_chapter_index, en_chapter_index, source, confidence, reason,
                        alternatives_json, confirmed, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        int(item["zh_chapter_index"]),
                        int(item["en_chapter_index"]),
                        str(item.get("source", "manual")),
                        item.get("confidence"),
                        str(item.get("reason", "")),
                        json.dumps(item.get("alternatives", []), ensure_ascii=False),
                        1 if confirmed or item.get("confirmed") else 0,
                        now,
                    ),
                )
        self.touch_project(project_id, status="mapped")

    def list_chapter_mappings(self, project_id: int) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM chapter_mappings
                WHERE project_id = ?
                ORDER BY zh_chapter_index ASC
                """,
                (project_id,),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["alternatives"] = json.loads(item.get("alternatives_json") or "[]")
                item["confirmed"] = bool(item.get("confirmed"))
                out.append(item)
            return out

    def confirm_chapter_mappings(self, project_id: int) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE chapter_mappings SET confirmed = 1, updated_at = ? WHERE project_id = ?",
                (now, project_id),
            )
        self.touch_project(project_id, status="mapped")

    def save_chapter_alignment(
        self,
        project_id: int,
        zh_chapter_index: int,
        *,
        state: str,
        blocks: Sequence[Dict[str, Any]],
        local_sync_map: Sequence[int],
        review_items: Sequence[Dict[str, Any]],
        metrics: Dict[str, Any],
        cache_key: str,
    ) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chapter_alignments(
                    project_id, zh_chapter_index, state, blocks_json, local_sync_map_json,
                    review_items_json, metrics_json, cache_key, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, zh_chapter_index) DO UPDATE SET
                    state=excluded.state,
                    blocks_json=excluded.blocks_json,
                    local_sync_map_json=excluded.local_sync_map_json,
                    review_items_json=excluded.review_items_json,
                    metrics_json=excluded.metrics_json,
                    cache_key=excluded.cache_key,
                    updated_at=excluded.updated_at
                """,
                (
                    project_id,
                    zh_chapter_index,
                    state,
                    json.dumps(list(blocks), ensure_ascii=False),
                    json.dumps(list(local_sync_map), ensure_ascii=False),
                    json.dumps(list(review_items), ensure_ascii=False),
                    json.dumps(metrics, ensure_ascii=False),
                    cache_key,
                    now,
                ),
            )
        status = "reading_ready" if state == "confirmed" else "aligned"
        self.touch_project(project_id, status=status)

    def get_chapter_alignment(self, project_id: int, zh_chapter_index: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM chapter_alignments
                WHERE project_id = ? AND zh_chapter_index = ?
                """,
                (project_id, zh_chapter_index),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["blocks"] = json.loads(item["blocks_json"])
            item["local_sync_map"] = json.loads(item["local_sync_map_json"])
            item["review_items"] = json.loads(item["review_items_json"])
            item["metrics"] = json.loads(item["metrics_json"])
            return item

    def list_anchors(self, project_id: int, zh_chapter_index: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM anchors WHERE project_id = ?"
        params: List[Any] = [project_id]
        if zh_chapter_index is not None:
            sql += " AND zh_chapter_index = ?"
            params.append(zh_chapter_index)
        sql += " ORDER BY COALESCE(zh_chapter_index, -1), zh_paragraph_index, en_paragraph_index"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            out = [dict(r) for r in rows]
            for item in out:
                item["confirmed"] = bool(item["confirmed"])
                item["zh_start"] = int(item["zh_start"] if item.get("zh_start") is not None else item["zh_paragraph_index"])
                item["zh_end"] = int(item["zh_end"] if item.get("zh_end") is not None else item["zh_paragraph_index"])
                item["en_start"] = int(item["en_start"] if item.get("en_start") is not None else item["en_paragraph_index"])
                item["en_end"] = int(item["en_end"] if item.get("en_end") is not None else item["en_paragraph_index"])
                item["zh_paragraph_index"] = item["zh_start"]
                item["en_paragraph_index"] = item["en_start"]
                item["payload"] = json.loads(item.get("payload_json") or "{}")
            return out

    def add_anchor(
        self,
        project_id: int,
        *,
        zh_chapter_index: Optional[int],
        zh_paragraph_index: Optional[int] = None,
        en_paragraph_index: Optional[int] = None,
        zh_start: Optional[int] = None,
        zh_end: Optional[int] = None,
        en_start: Optional[int] = None,
        en_end: Optional[int] = None,
        kind: str = "hard",
        confirmed: bool = True,
        note: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if zh_start is None:
            zh_start = int(zh_paragraph_index if zh_paragraph_index is not None else 0)
        if zh_end is None:
            zh_end = int(zh_start)
        if en_start is None:
            en_start = int(en_paragraph_index if en_paragraph_index is not None else 0)
        if en_end is None:
            en_end = int(en_start)
        zh_start, zh_end = sorted((int(zh_start), int(zh_end)))
        en_start, en_end = sorted((int(en_start), int(en_end)))
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO anchors(
                    project_id, zh_chapter_index, zh_paragraph_index, en_paragraph_index,
                    zh_start, zh_end, en_start, en_end, kind, confirmed, note, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    zh_chapter_index,
                    zh_start,
                    en_start,
                    zh_start,
                    zh_end,
                    en_start,
                    en_end,
                    kind,
                    1 if confirmed else 0,
                    note,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            anchor_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM anchors WHERE id = ?", (anchor_id,)).fetchone()
            item = dict(row) if row is not None else {}
            if item:
                item["confirmed"] = bool(item["confirmed"])
                item["zh_start"] = int(item["zh_start"] if item.get("zh_start") is not None else item["zh_paragraph_index"])
                item["zh_end"] = int(item["zh_end"] if item.get("zh_end") is not None else item["zh_paragraph_index"])
                item["en_start"] = int(item["en_start"] if item.get("en_start") is not None else item["en_paragraph_index"])
                item["en_end"] = int(item["en_end"] if item.get("en_end") is not None else item["en_paragraph_index"])
                item["zh_paragraph_index"] = item["zh_start"]
                item["en_paragraph_index"] = item["en_start"]
                item["payload"] = json.loads(item.get("payload_json") or "{}")
            return item

    def delete_anchor(self, project_id: int, anchor_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM anchors WHERE project_id = ? AND id = ?", (project_id, anchor_id))

    def create_job(self, project_id: int, job_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO jobs(project_id, type, status, payload_json, result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, job_type, "pending", json.dumps(payload, ensure_ascii=False), "{}", now, now),
            )
            job_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._job_row_to_dict(row)

    def get_active_job(self, project_id: int, job_type: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM jobs
                WHERE project_id = ? AND type = ? AND status IN ('pending', 'running')
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id, job_type),
            ).fetchone()
            return self._job_row_to_dict(row) if row is not None else None

    def update_job(self, job_id: int, *, status: str, result: Dict[str, Any]) -> Dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(result, ensure_ascii=False), now, job_id),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._job_row_to_dict(row)

    def list_jobs(self, project_id: int) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()
            return [self._job_row_to_dict(r) for r in rows]

    def _job_row_to_dict(self, row: sqlite3.Row | None) -> Dict[str, Any]:
        if row is None:
            return {}
        item = dict(row)
        item["payload"] = json.loads(item.get("payload_json") or "{}")
        item["result"] = json.loads(item.get("result_json") or "{}")
        return item

    def build_project_overview(self, project_id: int) -> Dict[str, Any]:
        project = self.get_project(project_id)
        zh_paragraphs, zh_chapters = self.load_book_document(int(project["zh_book_id"]))
        en_paragraphs, en_chapters = self.load_book_document(int(project["en_book_id"]))
        mappings = {m["zh_chapter_index"]: m for m in self.list_chapter_mappings(project_id)}
        with self._connect() as conn:
            alignment_rows = conn.execute(
                "SELECT zh_chapter_index, state, metrics_json FROM chapter_alignments WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        alignments = {int(r["zh_chapter_index"]): dict(r) for r in alignment_rows}
        chapters: List[Dict[str, Any]] = []
        for idx, zh_ch in enumerate(zh_chapters):
            mapping = mappings.get(idx)
            alignment = alignments.get(idx)
            alignment_state = str(alignment["state"]) if alignment is not None else "missing"
            alignment_source = _alignment_source_from_metrics(
                alignment_state,
                json.loads(alignment.get("metrics_json") or "{}") if alignment is not None else {},
            )
            en_idx = int(mapping["en_chapter_index"]) if mapping is not None else None
            en_title = ""
            if en_idx is not None and 0 <= en_idx < len(en_chapters):
                en_title = str(en_chapters[en_idx].get("title", ""))
            chapters.append(
                {
                    "zh_chapter_index": idx,
                    "zh_title": str(zh_ch.get("title", "")),
                    "zh_start": int(zh_ch.get("start", 0)),
                    "zh_end": int(zh_ch.get("end", 0)),
                    "mapped_en_chapter_index": en_idx,
                    "mapped_en_title": en_title,
                    "mapping_confidence": None if mapping is None else mapping.get("confidence"),
                    "mapping_source": None if mapping is None else mapping.get("source"),
                    "mapping_confirmed": False if mapping is None else bool(mapping.get("confirmed")),
                    "alignment_state": alignment_state,
                    "alignment_source": alignment_source,
                }
            )
        return {
            "project": project,
            "stats": {
                "zh_chapter_count": len(zh_chapters),
                "en_chapter_count": len(en_chapters),
                "zh_paragraph_count": len(zh_paragraphs),
                "en_paragraph_count": len(en_paragraphs),
                "mapping_count": len(mappings),
                "confirmed_alignment_count": sum(
                    1 for item in alignments.values() if str(item.get("state")) == "confirmed"
                ),
            },
            "chapters": chapters,
            "en_chapters": [
                {
                    "en_chapter_index": idx,
                    "title": str(chapter.get("title", "")),
                    "start": int(chapter.get("start", 0)),
                    "end": int(chapter.get("end", 0)),
                }
                for idx, chapter in enumerate(en_chapters)
            ],
        }

    def export_project_snapshot(self, project_id: int) -> Dict[str, Any]:
        return {
            "version": 2,
            "project": self.get_project(project_id),
            "chapter_mappings": self.list_chapter_mappings(project_id),
            "anchors": self.list_anchors(project_id),
            "chapter_alignments": [
                self.get_chapter_alignment(project_id, item["zh_chapter_index"])
                for item in self.build_project_overview(project_id)["chapters"]
                if self.get_chapter_alignment(project_id, item["zh_chapter_index"]) is not None
            ],
        }
