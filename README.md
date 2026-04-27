# DuReading

DuReading V2 is a local bilingual reading workspace for pairing Chinese translations with English source books.

The product is reader-first:

- `Library`: upload and reuse multiple EPUB books.
- `Project`: pair one Chinese book with one English book.
- `Read mode`: fast chapter reading from stored alignment only; no AI calls while reading.
- `Alignment mode`: chapter mapping, chapter alignment, block anchors, mismatch reports, confirm/skip/regenerate.

The current UI slogan is intentionally opinionated: `这要命的译文！！！`

## Run

```bash
./run_web.sh
```

The default port is `8000`: [http://localhost:8000](http://localhost:8000).

To choose another port:

```bash
./run_web.sh 9000
```

You can also run the FastAPI app directly:

```bash
python3 web_server.py
```

## Environment

LLM features are optional. Without an API key, DuReading still runs with deterministic fallback/heuristic behavior.

For LLM chapter mapping and ambiguous paragraph alignment, create a local `.env` file:

```env
OPENAI_API_KEY=your-key-here
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1
```

Useful optional variables:

- `DUREADING_STORAGE_DIR`: local storage directory, default `storage/`.
- `DUREADING_LLM_DEBUG=1`: write full LLM prompts/responses to `log/llm_debug.log`.
- `DUREADING_LLM_DEBUG_FILE`: override the LLM debug log path.
- `DUREADING_SERVER_EVENTS_FILE`: override the server decision/event log path, default `log/server_events.log`.

Do not commit `.env`, `log/`, or `storage/`.

Security note: the current app is intended for local use and does not implement authentication yet. Do not expose it as a public remote service with private books or API credentials.

## Storage

V2 persists state locally with SQLite plus files:

- `storage/app.db`: book/project/mapping/alignment/anchor/job metadata.
- `storage/books/{book_id}/source.epub`: uploaded source file.
- `storage/books/{book_id}/paragraphs.json`: parsed paragraph artifact.
- `storage/books/{book_id}/chapters.json`: parsed chapter artifact.
- `storage/projects/{project_id}/`: optional project artifacts/debug snapshots.

Books are reusable across projects. Deleting a book also deletes dependent projects.

## Alignment Model

DuReading no longer treats a chapter as a single point map. The canonical paragraph alignment output is block/range based:

- `blocks`: the semantic truth, supporting 1:N, N:1, and N:M paragraph matches.
- `en_ranges_by_zh`: derived Chinese paragraph to English range lookup for UI highlighting.
- `local_sync_map`: compatibility/scroll-sync projection only.

`Alignment mode` supports hard anchors as continuous Chinese range to continuous English range constraints. Regeneration respects confirmed hard anchors.

The LLM policy is explicit:

- `auto`: use heuristics first; use LLM for small/imbalanced segments.
- `force`: try LLM for every non-anchor segment.
- `off`: pure heuristic.

Each alignment stores `metrics.decision_log` and `metrics.alignment_source` (`lm`, `heuristic`, `mixed`, `fallback`, `skipped`) so draft results are explainable in the UI.

## Logging

Logs are intentionally split:

- `log/llm_debug.log`: full prompt/response records, only when `DUREADING_LLM_DEBUG=1`.
- `log/server_events.log`: JSONL server events such as alignment decisions, cache hits, job progress, rate-limit fallback.

`server_events.log` does not contain full prompts or source book text by design.

## EPUB Import And PDF Conversion

The web app accepts EPUB uploads only. EPUB import keeps using the existing structure-first parser and writes normalized `paragraphs.json` and `chapters.json`, so alignment and Reader mode reuse the same data path.

For PDFs, use the one-time local PDF-to-EPUB tooling first, then upload the generated EPUB:

```bash
python3 pdf_to_epub_ocr.py data/CnVIllette.pdf \
  --language zh \
  --title 维莱特 \
  --out data/CnVillette.ocr.epub \
  --work-dir tmp_books/CnVillette_ocr \
  --ocr-lang chi_sim+chi_tra+eng \
  --scale 1.0
```

The tool writes a standard EPUB plus `tmp_books/.../ocr_pages.jsonl`, `parse_report.json`, and `preview.md`. It resumes from the page cache by default, so a long OCR run does not need to restart from page 1. Upload the generated EPUB through the normal library flow after checking the preview.

## Tests

Install dev dependencies if needed:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run the full test suite:

```bash
python3 -m pytest -q
node --test tests/frontend_logic.test.js
node --check app.js
node --check dist-reader/reader.js
```

Important tests:

- `tests/test_v2_api.py`: FastAPI project/book/alignment/anchor/job flow.
- `tests/test_middlemarch_ch1_alignment.py`: fixed Middlemarch chapter-1 block alignment regression.
- `tests/test_hybrid_alignment_policy.py`: `llm_policy`, hard-anchor, missing-key behavior.
- `tests/test_epub_footnotes.py`: EPUB footnote filtering regression.
- `tests/test_pdf_upload_rejected.py`: direct PDF upload is rejected; PDFs must be converted to EPUB first.
- `tests/test_pdf_to_epub_ocr.py`: local PDF-to-EPUB tooling and resume cache behavior.
- `tests/frontend_logic.test.js`: frontend range/highlight/source-label logic.

LLM integration tests skip when no API key/network is available.

## Publish A Static Reader

Keep Align local, then export a reader-only static site:

```bash
DUREADING_READER_PASSWORD="shared-reader-password" ./publish_reader.sh PROJECT_ID
```

You can allow more than one password, for example one private password and one simpler friend password:

```bash
DUREADING_READER_PASSWORDS="my-private-password,friend-simple-password" ./publish_reader.sh PROJECT_ID
```

This writes `dist-reader/` with only static reader assets and readable chapter JSON. Draft and confirmed chapters are exported; missing/skipped chapters are not. It does not include Align Mode, Library, source EPUB files, SQLite, logs, jobs, anchors, or LLM debug data.

On mobile-width screens, the static Reader prioritizes the Chinese text and opens matched English text in a bottom sheet after tapping a paragraph. Desktop keeps the side-by-side lookup panel.

To update an existing Reader deployment without changing the reader password, reuse the current exported password hash:

```bash
python3 - <<'PY' > /tmp/dureading_reader_hash_args.txt
import json
manifest = json.load(open("dist-reader/manifest.json"))
for item in manifest.get("reader_password_hashes") or [manifest["reader_password_hash"]]:
    print("--reader-password-hash", item)
PY
python3 export_reader_site.py --project-id PROJECT_ID --out dist-reader $(cat /tmp/dureading_reader_hash_args.txt)
vercel deploy dist-reader --prod
```

Preview locally:

```bash
python3 -m http.server 9000 --directory dist-reader
```

Deploy manually to Vercel:

```bash
vercel deploy dist-reader --prod
```

Vercel prints a unique production deployment URL on every deploy, such as `https://dist-reader-xxxxx.vercel.app`. It also updates the stable alias, currently `https://dist-reader.vercel.app`, to point at the newest production deployment. Share the stable alias unless you specifically need to inspect one immutable deployment.

The reader password is a lightweight frontend gate. It is useful for avoiding casual access, but it is not a strong security boundary because the site is still static.

## Commit Hygiene

Before pushing:

```bash
git status --short
rg -n "sk-[A-Za-z0-9_-]+|OPENAI_API_KEY\\s*=|Authorization: Bearer|Bearer [A-Za-z0-9._-]+" . --glob '!storage/**' --glob '!log/**' --glob '!.git/**'
```

Expected non-source local artifacts are ignored:

- `.env`
- `log/`
- `storage/`
- `tmp_test_*/`
- `tests/fixtures/*.local.txt`

Architecture details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
