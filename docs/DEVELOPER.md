# Developer Guide

这份文档给想理解设计、跑测试、继续开发的人。更底层的数据模型和 API 细节见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 代码从哪里开始看

| 你想理解什么 | 入口 |
| --- | --- |
| 本地 FastAPI app 和 API | `web_server.py` |
| SQLite、storage、project/book/alignment 状态 | `storage_v2.py` |
| EPUB 解析 | `document_parser.py`, `chapter_catalog.py` |
| PDF 转 EPUB 工具 | `pdf_to_epub_ocr.py` |
| 章节和段落对齐 | `hybrid_alignment.py`, `paragraph_alignment.py` |
| LLM 配置和调用 | `alignment_common.py` |
| server event logging | `server_events.py` |
| 本地网页 UI | `index.html`, `app.js`, `styles.css` |
| 可测试的前端纯逻辑 | `frontend_logic.js` |
| 静态 Reader 导出 | `export_reader_site.py`, `publish_reader.sh` |

## 本地运行

```bash
./run_web.sh
```

默认地址是 [http://localhost:8000](http://localhost:8000)。

指定端口：

```bash
./run_web.sh 9000
```

直接运行 FastAPI：

```bash
python3 web_server.py
```

## 环境变量

LLM 可选。没有 API key 时，系统仍可以用 heuristic fallback。

本地 `.env` 示例：

```env
OPENAI_API_KEY=your-key-here
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1
```

常用变量：

- `DUREADING_STORAGE_DIR`：storage root，默认 `storage/`。
- `DUREADING_LLM_DEBUG=1`：写完整 LLM prompt/response。
- `DUREADING_LLM_DEBUG_FILE`：覆盖 `log/llm_debug.log`。
- `DUREADING_SERVER_EVENTS_FILE`：覆盖 `log/server_events.log`。

## 数据流速览

本地制作流程：

```text
EPUB upload
-> normalized paragraphs.json + chapters.json
-> project chapter mapping
-> chapter alignment blocks
-> en_ranges_by_zh + local_sync_map
-> Read Mode / static Reader export
```

静态发布流程：

```text
local storage/app.db + artifacts
-> export_reader_site.py
-> dist-reader/
-> Vercel/static hosting
```

## 测试

安装测试依赖：

```bash
python3 -m pip install -r requirements-dev.txt
```

后端测试：

```bash
python3 -m pytest -q
```

前端逻辑和语法：

```bash
node --test tests/frontend_logic.test.js
node --check app.js
```

如果已导出 `dist-reader/`：

```bash
node --check dist-reader/reader.js
```

重要测试：

- `tests/test_v2_api.py`：book/project/mapping/alignment/anchor/job API。
- `tests/test_middlemarch_ch1_alignment.py`：Middlemarch 第一章段落对齐回归。
- `tests/test_hybrid_alignment_policy.py`：LLM policy、hard Anchor、missing-key 行为。
- `tests/test_epub_footnotes.py`：EPUB footnote 过滤。
- `tests/test_pdf_upload_rejected.py`：网页拒绝直接 PDF 上传。
- `tests/test_pdf_to_epub_ocr.py`：PDF-to-EPUB 工具和 resume cache。
- `tests/test_reader_export.py`：静态 Reader 导出安全。
- `tests/frontend_logic.test.js`：前端 range/highlight/source-label 逻辑。

## 日志

日志分两类：

- `log/llm_debug.log`：完整 LLM prompt/response，只在开启 `DUREADING_LLM_DEBUG=1` 时写入。
- `log/server_events.log`：JSONL 系统事件，包括 alignment decision、cache hit、job progress、rate-limit fallback。

如果想知道某章为什么走 heuristic、LM、mixed 或 fallback，优先看 `server_events.log`。

## PDF 开发路径

网页只接受 EPUB。

PDF 支持通过本地工具完成。把下面的 `path/to/book.pdf` 换成你自己的 PDF 路径：

```bash
python3 pdf_to_epub_ocr.py path/to/book.pdf \
  --language zh \
  --title 书名 \
  --out path/to/book.ocr.epub \
  --work-dir tmp_books/book_ocr \
  --ocr-lang chi_sim+chi_tra+eng \
  --scale 1.0
```

工具输出：

- 生成的 EPUB。
- `tmp_books/.../ocr_pages.jsonl`。
- `tmp_books/.../parse_report.json`。
- `tmp_books/.../preview.md`。

## 提交安全

提交前检查：

```bash
git status --short
rg -n "sk-[A-Za-z0-9_-]+|OPENAI_API_KEY\\s*=|Authorization: Bearer|Bearer [A-Za-z0-9._-]+" . --glob '!storage/**' --glob '!log/**' --glob '!dist-reader/**' --glob '!.git/**'
```

应该保持 ignored 的本地文件：

- `.env`
- `storage/`
- `log/`
- `dist-reader/`
- `tmp_books/`
- `data/*.pdf`
- `data/*.ocr.epub`
- `tests/fixtures/*.local.txt`

提交时优先逐个文件 `git add`，不要随手 `git add .`。
