# DuReading V2 Architecture

This document describes the current implementation. Source code is the final authority.

## 1. Product Goal

DuReading is a local, reader-first bilingual workspace. It helps a reader use a Chinese translation as the primary reading text and quickly inspect the English source when the translation feels suspicious.

The product has two modes:

- `Read mode`: fast, cached, stable reading. It only serves stored chapter data and does not make AI calls.
- `Alignment mode`: editing and production mode for chapter mapping, paragraph alignment, anchors, mismatch reports, confirm/skip/regenerate, and background alignment jobs.

The application is local-first. There is no cloud sync, account system, or multi-user collaboration.

## 2. Runtime Stack

| Area | Files | Responsibility |
| --- | --- | --- |
| FastAPI app | `web_server.py` | Static app serving plus project/book/alignment APIs |
| Persistence | `storage_v2.py` | SQLite schema, migrations, artifacts, snapshots |
| Source parsing | `document_parser.py`, `chapter_catalog.py` | Parse uploaded EPUBs into normalized paragraphs and chapter ranges |
| PDF-to-EPUB tooling | `pdf_to_epub_ocr.py` | One-time local conversion of large scanned PDFs into clean EPUBs |
| LLM utilities | `alignment_common.py` | `.env`, API config, OpenAI-compatible JSON calls, LLM debug log |
| Chapter/paragraph alignment | `hybrid_alignment.py`, `paragraph_alignment.py`, `alignment_service.py` | Chapter mapping, hybrid alignment, fallback/debug LLM paths |
| Server events | `server_events.py` | JSONL decision/job/cache logging |
| Frontend | `index.html`, `app.js`, `frontend_logic.js`, `styles.css` | Library, reader, alignment UI, anchor interaction |
| Tests | `tests/` | Backend API, alignment regressions, frontend logic |

`alignment_service.py` and some older utilities remain available for compatibility/debug comparisons, but the main V2 flow is project-based through `web_server.py`, `storage_v2.py`, and `hybrid_alignment.py`.

## 3. Persistent Data Model

SQLite lives under `storage/app.db` by default. `DUREADING_STORAGE_DIR` can point to another storage root.

Main tables:

- `books`: uploaded EPUB metadata, language, content hash, title, source format/path.
- `book_artifacts`: parser artifact paths, stats, parser version.
- `projects`: one Chinese book paired with one English book.
- `chapter_mappings`: Chinese chapter index to English chapter index, confidence/source/reason/confirmation.
- `chapter_alignments`: per-Chinese-chapter state, blocks, sync map, review items, metrics, cache key.
- `anchors`: hard anchors and mismatch reports. Hard anchors are alignment constraints; mismatch reports are debug feedback.
- `jobs`: background prefetch/align-remaining jobs.

Filesystem layout:

- `storage/books/{book_id}/source.epub`
- `storage/books/{book_id}/paragraphs.json`
- `storage/books/{book_id}/chapters.json`
- `storage/projects/{project_id}/...`

Uploaded books are reusable. Projects reference book IDs rather than duplicating EPUB artifacts.

## 4. Source Parsing

All source files normalize to:

- `paragraphs: list[str]`
- `chapters: list[{title, path, start, end}]`

EPUB parsing remains in `chapter_catalog.py` and parses spine HTML/XHTML files.
Chapter titles come from EPUB nav/NCX when available, then fallback heading/title extraction.

Paragraph extraction is structure-first:

1. Remove non-reading elements such as scripts/styles.
2. Remove footnote-like elements and note references where the EPUB marks them structurally.
3. Extract text from paragraph/list/blockquote/heading tags.
4. If no structured paragraphs are found, fallback to stripped text split by blank lines.

The web app intentionally accepts EPUB uploads only. For PDFs, the supported path is the standalone `pdf_to_epub_ocr.py` tool before uploading:

- It extracts/OCRs each page once and writes `ocr_pages.jsonl` in a work directory.
- It uses PDF bookmarks as EPUB chapters when available, then heading detection, then a whole-book fallback.
- It emits a standard EPUB with `content.opf`, `nav.xhtml`, `toc.ncx`, chapter XHTML files, and simple CSS.
- It validates the generated EPUB with the existing `chapter_catalog.py` parser and writes `parse_report.json` plus `preview.md`.
- The generated EPUB can be uploaded through the normal Library flow and then follows the same alignment/reader path as any other EPUB.

`parser_version` is persisted in `book_artifacts`, so stale artifacts can be refreshed when parser behavior changes.

## 5. Public API Shape

The V2 API is project-based.

Book APIs:

- `POST /api/books`
- `GET /api/books`
- `GET /api/books/{book_id}`
- `DELETE /api/books/{book_id}`
- `GET /api/books/{book_id}/chapters`

Project APIs:

- `POST /api/projects`
- `GET /api/projects`
- `GET /api/projects/{project_id}`
- `DELETE /api/projects/{project_id}`
- `GET /api/projects/{project_id}/chapters`
- `GET /api/projects/{project_id}/export`

Chapter mapping APIs:

- `POST /api/projects/{project_id}/chapter-mapping/suggest`
- `GET /api/projects/{project_id}/chapter-mapping`
- `PUT /api/projects/{project_id}/chapter-mapping`
- `POST /api/projects/{project_id}/chapter-mapping/confirm`

Chapter alignment APIs:

- `POST /api/projects/{project_id}/chapters/{chapter_index}/align`
- `POST /api/projects/{project_id}/chapters/{chapter_index}/regenerate`
- `GET /api/projects/{project_id}/chapters/{chapter_index}/alignment`
- `POST /api/projects/{project_id}/chapters/{chapter_index}/confirm`
- `POST /api/projects/{project_id}/chapters/{chapter_index}/skip`

Reader APIs:

- `GET /api/projects/{project_id}/reader`
- `GET /api/projects/{project_id}/reader/chapters/{chapter_index}`

Anchor/report APIs:

- `GET /api/projects/{project_id}/anchors`
- `POST /api/projects/{project_id}/anchors`
- `DELETE /api/projects/{project_id}/anchors/{anchor_id}`
- `POST /api/projects/{project_id}/mismatch-reports`

Job APIs:

- `POST /api/projects/{project_id}/jobs/prefetch`
- `POST /api/projects/{project_id}/jobs/align-remaining`
- `GET /api/projects/{project_id}/jobs`

## 6. Chapter Mapping

Chapter mapping is generated per project and stored in `chapter_mappings`.

The primary path uses LLM chapter-title mapping because title-only mapping has been more reliable for the bundled Middlemarch pair than earlier heuristic title/position matching. The fallback path remains deterministic if LLM is unavailable.

Mappings store:

- Chinese chapter index.
- English chapter index.
- source (`llm`, `fallback`, `manual`, etc.).
- confidence/reason/alternatives.
- confirmation state.

Once confirmed, the mapping panel defaults to collapsed. Confirmation does not freeze paragraph alignments; it freezes the chapter pair choices until the user edits them again.

## 7. Chapter Alignment Model

The canonical alignment truth is block/range based, not a single English point per Chinese paragraph.

Stored alignment fields:

- `blocks`: canonical semantic blocks. Each block contains 1-based `zh_start`, `zh_end`, `en_start`, `en_end`, confidence, reason.
- `en_ranges_by_zh`: derived 0-based English ranges for each Chinese paragraph.
- `local_sync_map`: derived 0-based English point projection used for scroll sync and compatibility.
- `review_items`: low-confidence or suspicious spans.
- `metrics`: explainability and runtime metadata.

This representation supports:

- One Chinese paragraph to multiple English paragraphs.
- Multiple Chinese paragraphs to one English paragraph.
- Multiple Chinese paragraphs to multiple English paragraphs.

`expand_en_ranges_from_blocks(...)` is the legal range expansion path. `flatten_map_from_blocks(...)` is a scroll-sync projection and should not be treated as semantic truth.

## 8. Hybrid Alignment Engine

Main entry point:

- `align_chapter_hybrid(...)`

Segment entry point:

- `align_segment_hybrid(...)`

High-level flow:

1. Load only local chapter paragraphs.
2. Normalize and validate confirmed hard anchors.
3. Split the chapter into free segments around hard anchors.
4. Insert hard-anchor blocks directly.
5. Align each free segment with `auto`, `force`, or `off` LLM policy.
6. Repair/normalize blocks.
7. Derive `en_ranges_by_zh`, `local_sync_map`, review items, metrics.
8. Persist the result and cache key.

`llm_policy`:

- `auto`: use LLM for small or imbalanced segments; use heuristic for large balanced segments.
- `force`: try LLM for every non-hard-anchor segment.
- `off`: do not call LLM.

If an API key is missing, `auto`/`force` fall back to heuristic and record `missing_api_key`.

If LLM rate limits during a request, `web_server.py` retries the chapter with LLM disabled and records:

- `metrics.alignment_source = "fallback"`
- `metrics.llm_rate_limited = true`
- `metrics.fallback_reason`
- `decision_log[*].reason = "rate_limited_fallback"` for fallback heuristic segments.

## 9. Anchors and Mismatch Reports

Hard anchors are continuous range constraints:

- `zh_start`, `zh_end`
- `en_start`, `en_end`
- `kind = "hard"`
- `confirmed = true`

The backend also accepts legacy single-point fields and converts them into ranges.

Validation rejects:

- out-of-bounds ranges.
- `start > end`.
- overlapping hard anchors.
- crossing hard anchors.

Regeneration respects hard anchors even with `llm_policy="force"`. Anchor blocks are never sent to LLM.

Mismatch reports are reader feedback:

- `kind = "mismatch_report"`
- `confirmed = false`
- optional note/cache key payload.

Mismatch reports do not affect alignment automatically. They are logged for later review and can be manually converted into hard anchors.

## 10. Caching and Stability

Chapter alignment cache keys include:

- Chinese chapter text.
- mapped English chapter text.
- hard-anchor ranges.
- engine version.
- prompt version.
- `llm_policy`.

Including `llm_policy` prevents a user from selecting `off` and silently receiving a cached LLM result, or selecting `force` and silently receiving a heuristic result.

Confirmed alignments remain stable until explicit regenerate.

## 11. Jobs

Background jobs are stored in `jobs`:

- `prefetch`: align nearby future chapters.
- `align_remaining`: align chapters from a starting chapter through the rest of the mapped book.

Jobs record:

- status (`pending`, `running`, `completed`, `failed`).
- payload, including `llm_policy`.
- result progress (`done_count`, `total_count`, `current_chapter`, `aligned_chapters`).

The frontend polls active jobs and shows compact progress.

## 12. Logging

Two logs intentionally serve different purposes:

- `log/llm_debug.log`: full LLM prompts/responses. Only written when `DUREADING_LLM_DEBUG=1`.
- `log/server_events.log`: JSONL events for system decisions, cache hits, alignment saves, job progress/failure, and rate-limit fallback.

Server events include `timestamp`, `event_type`, `project_id`, `chapter_index`, `debug_label`, and relevant decision fields. They do not include full prompt bodies.

Neither `log/` nor `.env` should be committed.

## 13. Frontend Architecture

The frontend is framework-free:

- `index.html`: DOM structure.
- `app.js`: API calls, UI state, rendering, interactions.
- `frontend_logic.js`: pure helper logic with Node tests.
- `styles.css`: layout and visual system.

Current layout:

- Top compact Library panel for uploads, book list, project list, and status.
- Left column inside workspace for chapters and background jobs.
- Main Chinese reading column.
- Right English lookup panel.
- Alignment panel for current chapter actions.
- Floating anchor tool in Alignment mode, collapsible to a small button.

Reading behavior:

- Chinese translation is primary.
- Clicking a Chinese paragraph shows the matched English block plus one paragraph of context before/after.
- On mobile-width screens, Read mode uses a bottom English lookup sheet so the Chinese text remains the main page.
- Highlighting uses `en_ranges_by_zh`.
- Scroll sync may continue using `local_sync_map`.

Alignment behavior:

- Mapping panel defaults collapsed after mappings are confirmed.
- Current chapter alignment panel shows source (`LM`, `heuristic`, `mixed`, `fallback`) and decision summary.
- Chapter list labels draft source as `draft · LM`, `draft · heuristic`, `draft · mixed`, or `draft · fallback`.
- Anchor mode allows range-to-range hard anchors through the right lookup panel.

## 14. Tests and Fixtures

Key tests:

- `tests/test_v2_api.py`: end-to-end API flow for books, projects, mappings, alignments, anchors, reports, jobs, deletes.
- `tests/test_middlemarch_ch1_alignment.py`: fixed Middlemarch chapter-1 regression using real project alignment functions.
- `tests/test_hybrid_alignment_policy.py`: LLM policy and hard-anchor behavior.
- `tests/test_epub_footnotes.py`: structured footnote filtering regression.
- `tests/test_pdf_upload_rejected.py`: direct PDF upload is rejected; PDFs must be converted to EPUB first.
- `tests/test_pdf_to_epub_ocr.py`: standalone PDF-to-EPUB conversion and resume cache behavior.
- `tests/frontend_logic.test.js`: range/highlight/source-label logic.
- `tests/test_frontend_logic.py`: Python-side frontend helper expectations where applicable.

Middlemarch fixtures under `tests/fixtures/` are intentionally committed when they are part of regression tests. Local/private fixture variants should use the ignored `*.local.txt` suffix.

## 15. Known Limits

- No authentication yet. Alignment mode is visible in the UI. If password-gating Alignment mode is required, implement it as a separate feature with documentation and tests.
- LLM quality still depends on chapter/paragraph extraction quality.
- PDF-to-EPUB conversion preserves logical structure, not exact PDF typography or page images.
- EPUBs that embed translator notes as normal body paragraphs may still confuse alignment; structural footnotes are filtered, but semantically embedded notes need alignment-time handling or manual anchors.
- Background jobs run in-process. This is appropriate for local use, not a production multi-user service.
- The app is designed for local reading and debugging, not for storing secrets or private books in a remote deployment.

## 16. Static Reader Publishing

Align can remain local while a reader-only static site is published:

- `export_reader_site.py` reads local `storage/` and exports `dist-reader/`.
- Draft and confirmed chapters are exported by default; missing/skipped chapters are not.
- Exported assets are static: `index.html`, `reader.js`, `reader.css`, `manifest.json`, `chapters/{chapter_index}.json`.
- The static reader has no Library, Alignment mode, upload/delete actions, anchors, jobs, OpenAI key, SQLite, source EPUB files, or LLM debug logs.
- `publish_reader.sh` wraps export and prints the Vercel deploy command.

Publishing flow:

1. Run local Align and save the latest draft/confirmed chapter alignments.
2. Export `dist-reader/` with `publish_reader.sh` or `export_reader_site.py`.
3. Deploy with `vercel deploy dist-reader --prod`.
4. Check the stable alias, currently `https://dist-reader.vercel.app`.

When updating published content, reuse the existing `reader_password_hashes` from `dist-reader/manifest.json` if the reader passwords should stay unchanged. The legacy `reader_password_hash` field is still exported for compatibility. Vercel creates a new immutable production deployment URL each time, then moves the stable alias to the newest production deployment.

The static reader can accept multiple frontend password hashes and uses `sessionStorage` after unlock. This is intentionally lightweight and not a strong security boundary; use server-side auth or Cloudflare Access later if content protection becomes important.

The exported static Reader has the same mobile reading pattern as local Read mode: Chinese text is the primary natural scroll surface, and the matched English range opens in a dismissible bottom sheet below `760px` screen width. Desktop continues to use the right-side lookup panel.
