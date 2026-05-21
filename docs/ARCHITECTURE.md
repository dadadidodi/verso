# Architecture

这份文档是技术深水区。使用流程看 [ALIGNER.md](ALIGNER.md)，发布流程看 [PUBLISHING.md](PUBLISHING.md)，开发入口看 [DEVELOPER.md](DEVELOPER.md)。

## 系统边界

verso 有两个 surface：

- Local Align app：`web_server.py` 服务的本地完整应用，负责写入和修改数据。
- Static Reader site：`tools/export_reader_site.py` 生成的只读静态站，负责分享阅读内容。

Local Align app 是 source of truth。Static Reader 是从本地状态导出的 snapshot。

## Runtime Stack

| Area | Files | Responsibility |
| --- | --- | --- |
| FastAPI app | `web_server.py` | 本地静态文件服务和 API |
| Persistence | `storage.py` | SQLite schema、migration、artifact path、project state |
| EPUB parsing | `book_import.py`, `epub_parser.py` | EPUB 到 paragraphs/chapters |
| PDF tooling | `tools/pdf_to_epub_ocr.py`, `tools/pdf_text.py` | 实验性离线 PDF→EPUB |
| LLM utilities | `llm_client.py`, `utils.py` | `.env`、OpenAI-compatible JSON call、LLM debug log |
| Alignment | `hybrid_alignment.py`, `paragraph_alignment.py` | chapter mapping、block/range paragraph alignment、Anchor constraints |
| Server events | `server_events.py` | JSONL decision/job/cache logging |
| Local frontend | `index.html`, `app.js`, `frontend_logic.js`, `styles.css` | Library、Read Mode、Alignment Mode、Anchor UI |
| Static export | `tools/export_reader_site.py`, `publish_reader.sh` | Reader-only static assets |

## Storage Model

默认 storage root 是 `storage/`，可用 `VERSO_STORAGE_DIR` 覆盖。

主要 SQLite 表：

- `books`：source metadata、language、title、content hash、source path。
- `book_artifacts`：parser artifacts 和 stats。
- `projects`：一个中文 book 和一个英文 book 的 pairing。
- `chapter_mappings`：中文 chapter index 到英文 chapter index。
- `chapter_alignments`：每章 alignment state、blocks、sync map、review items、metrics、cache key。
- `anchors`：hard anchors 和 mismatch reports。
- `jobs`：prefetch 和 align-remaining background jobs。

主要文件 artifacts：

- `storage/books/{book_id}/source.epub`
- `storage/books/{book_id}/paragraphs.json`
- `storage/books/{book_id}/chapters.json`
- `storage/projects/{project_id}/...`

## Normalized Source Shape

所有上传 EPUB 最终都转成统一结构：

```text
paragraphs: list[str]
chapters: list[{title, path, start, end}]
```

章节和段落解析完成后，alignment engine 不关心原始来源是普通 EPUB 还是 PDF 转出的 EPUB。PDF 转换质量通常偏低，所以这条路径只适合导入前救急，不能当作可靠的 parser 输入。

## Public API Shape

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

Mapping APIs:

- `POST /api/projects/{project_id}/chapter-mapping/suggest`
- `GET /api/projects/{project_id}/chapter-mapping`
- `PUT /api/projects/{project_id}/chapter-mapping`
- `POST /api/projects/{project_id}/chapter-mapping/confirm`

Alignment APIs:

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

## Alignment Data Model

Paragraph alignment is block/range based.

Canonical fields:

- `blocks`：semantic truth，1-based `zh_start`, `zh_end`, `en_start`, `en_end`。
- `en_ranges_by_zh`：0-based English range per Chinese paragraph，用于 UI 语义高亮。
- `local_sync_map`：0-based English point projection，只用于 scroll sync 和兼容旧逻辑。
- `review_items`：低置信或可疑 spans。
- `metrics`：alignment source、decision log、LLM/heuristic counts、fallback reason。

This supports `1:N`, `N:1`, and `N:M` matches.

## Hybrid Alignment Flow

Main entry point：`align_chapter_hybrid(...)`。

Segment entry point：`align_segment_hybrid(...)`。

流程：

1. Load current mapped chapter paragraphs only.
2. Normalize confirmed hard Anchors.
3. Split chapter into free segments around hard Anchors.
4. Insert hard-anchor blocks directly.
5. Align each free segment according to `llm_policy`.
6. Repair and normalize blocks.
7. Derive `en_ranges_by_zh`, `local_sync_map`, review items, and metrics.
8. Persist result and cache key.

`llm_policy`:

- `auto`：small/imbalanced segments may use LLM; large balanced segments may use heuristic.
- `force`：try LLM for every non-anchor segment.
- `off`：pure heuristic.

Missing API keys and rate limits fall back to heuristic, but the reason is recorded in metrics and `server_events.log`.

## Anchor Constraints

Hard Anchor fields:

- `zh_start`, `zh_end`
- `en_start`, `en_end`
- `kind = "hard"`
- `confirmed = true`

Validation rejects out-of-bounds, overlapping, or crossing anchors.

Regeneration respects hard Anchors even when `llm_policy="force"`。Anchor blocks are not sent to LLM.

Mismatch reports share storage but are not constraints:

- `kind = "mismatch_report"`
- `confirmed = false`

They do not affect alignment automatically.

## Cache Keys

Chapter alignment cache keys include:

- Chinese chapter text hash.
- mapped English chapter text hash.
- hard Anchor ranges.
- engine version.
- prompt version.
- `llm_policy`.

Including `llm_policy` prevents `force` and `off` from accidentally reusing incompatible cached results.

## Static Reader Export Shape

`tools/export_reader_site.py` reads local storage and writes:

- `dist-reader/index.html`
- `dist-reader/reader.css`
- `dist-reader/reader.js`
- `dist-reader/manifest.json`
- `dist-reader/chapters/{chapter_index}.json`

Only draft and confirmed chapters are exported. Missing and skipped chapters are excluded.

Chapter JSON contains reader-safe data:

- `chapter_index`
- `zh_title`, `en_title`
- `zh_paragraphs`
- `en_paragraphs`
- `en_ranges_by_zh`
- `local_sync_map`
- `alignment_state`

It intentionally excludes metrics, decision logs, anchors, jobs, source EPUBs, SQLite, `.env`, and logs.

## Known Limits

- Local Align app has no authentication and should remain local.
- Static Reader password is a lightweight frontend gate, not strong security.
- Alignment quality depends on extraction quality. EPUB is the intended input; PDF→EPUB is experimental and often needs manual cleanup.
- Translator notes embedded as normal body paragraphs can still confuse alignment; use hard Anchors to correct those cases.
- Background jobs are in-process, not a production queue.
