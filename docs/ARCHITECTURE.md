# DuReading 架构与设计说明

本文档描述本仓库的**代码逻辑**与**重要工程决策**，便于维护与二次开发。实现细节以源码为准。

## 1. 目标与范围

DuReading 是一套**中英对照阅读**实验工具：输入两本 EPUB（同一作品的中、英译本），在**段落粒度**上建立对应关系，供前端并排展示。对齐依赖大语言模型（LLM）的 JSON 输出，而非统计对齐器（如 hunalign）。

## 2. 模块总览

| 模块 | 文件 | 职责 |
|------|------|------|
| EPUB 解析 | `chapter_catalog.py` | 从 EPUB 提取**段落列表**与**章节边界**（每章在段落数组上的 `[start, end]`） |
| LLM 调用 | `alignment_common.py` | `.env` 加载、`ApiConfig`、OpenAI 兼容 `chat/completions`、JSON 模式、可选调试日志 |
| 章节映射 | `alignment_service.py` | `map_chapters_ai`：用 LLM 将每个中文章节标题映射到英文章节索引 |
| 段落对齐 | `paragraph_alignment.py` | 章内 LLM 粗对齐、大块二次细化、块修复、段落级 `sync_map` 展开、低置信度复核项 |
| 全书编排 | `alignment_service.py` | `align_book_by_chapter_mapping` / `align_single_chapter`：按章切片调用对齐并合并全局索引 |
| HTTP API | `web_server.py` | 静态页 + `/api/*` JSON 接口，供浏览器 `app.js` 调用 |
| 前端 | `index.html`, `app.js`, `styles.css` | 上传 EPUB、调 API、展示对齐结果与交互 |
| 工具脚本 | `epub_to_txt.py`, `epub_to_html.py`, `paragraph_debug.py`, `chapter_debug.py` 等 | 离线导出与调试 |

## 3. EPUB 解析逻辑（`chapter_catalog.py`）

### 3.1 读取顺序与 OPF

- 从 `META-INF/container.xml` 解析 OPF 路径。
- 读取 OPF 的 `manifest` 与 `spine`，**仅处理** `media-type` 或 `href` 看起来像 HTML/XHTML 的 spine 项。

### 3.2 章节标题来源（优先级）

1. **EPUB3 nav**：`manifest` 中带 `properties` 含 `nav` 的文档，解析其中 `<a href>` 与锚文本，得到 `(内容路径 → 标题)`。
2. **NCX**：若无 nav，则解析 `application/x-dtbncx+xml` 的 `navPoint`。
3. **回退**：从该 spine 文件的 HTML 中取首个 `h1|h2|h3|title` 标签内文本。

### 3.3 段落如何产生

对每段 spine HTML：

1. 去掉 `script/style/noscript/svg/math`。
2. 用正则抽取 `<p|li|blockquote|h1–h6>` 的内文，规范化空白；长度 ≥ 2 的视为一段。
3. 若一个文件内没有任何匹配，则退化为「剥标签后的全文」再按空行分段。

**决策**：段落边界由**标签结构**主导，而不是 Bitextual 类工具常用的「html-to-text 后按行切」。这样更贴近「一个 `<p>` 一段」的编辑结构，但对排版很乱的 EPUB 会退化为粗粒度块。

### 3.4 全书数据结构

- `paragraphs: List[str]`：全书所有段落顺序拼接。
- `chapters: List[ChapterSegment]`：每项含 `title`, `path`, `start`, `end`（闭区间下标，与代码中切片 `zh_start : zh_end + 1` 一致）。

`extract_epub_document_from_bytes` 与 `extract_epub_document` 供 CLI / `web_server` 的 base64 上传使用。

## 4. LLM 基础设施（`alignment_common.py`）

### 4.1 配置

- `load_env_file()` 读取项目根目录 `.env`（不覆盖已有环境变量）。
- `get_api_config()`：`OPENAI_API_BASE_URL`（默认官方）、`OPENAI_API_KEY`、`OPENAI_MODEL`（默认 `gpt-4.1`）。

### 4.2 请求约定

- `call_chat_json`：`temperature: 0`，`response_format: json_object`，解析 `choices[0].message.content` 为 JSON **对象**。
- 超时默认 120s；章内对齐调用使用更长超时（如 600s）。

### 4.3 调试

- `DUREADING_LLM_DEBUG=1` 等：将每次调用的 system/user prompt 与响应追加写入 `log/llm_debug.log`（或 `DUREADING_LLM_DEBUG_FILE`）。

**决策**：统一走 OpenAI 兼容接口，便于换兼容供应商；**不**在仓库内实现重试/流式，失败即抛错由上层处理。

## 5. 章节级对齐（`map_chapters_ai`）

**输入**：中文书名章节标题列表、英文书名章节标题列表（已由前端/API 做 `norm_space`）。

**提示词约束要点**：

- 输出 JSON：`pairs[{ zh_index, en_index, confidence, reason }]`（模型侧为 **1-based** 章节序号）。
- 每个中文章节**恰好出现一次**，`zh_index` 覆盖 `1..N`。
- **英文索引随中文章节非递减**（不允许「后面的中文章」映射到更靠前的英文章），与译本阅读顺序一致。

**后处理**：

- 转为 0-based `ChapterPair`，按 `zh_index` 排序。
- 若某 `zh_i` 缺失，用**上一已成功映射的 `en_index`** 填充并标记低置信（`missing_from_ai_output_filled`）。
- 对已有项：`en_i = max(last_en, min(p.en_index, len(en_titles)-1))`，保证单调不减。

**决策**：章节映射**完全依赖 LLM**，没有用编辑距离或规则匹配做预筛选；单调性在提示词 + 代码两侧双重约束，减少交叉映射。

## 6. 章内段落对齐（`paragraph_alignment.py`）

### 6.1 粗对齐 `align_paragraphs_in_chapter_llm`

- 将当前章的中、英段落编号写入 prompt（1-based 展示）。
- 要求输出 `blocks`，每块为**连续**中文下标范围与**连续**英文下标范围的 N:M 对齐。
- 规则强调：**语义/翻译等价**，而非长度或位置；中文侧须**划分完整**且无重叠；英文侧块间**单调**（允许边界相接）。
- 特别强调：**不要**把相邻的多个 1:1 对**合并**成一个大块，以保持最细合理粒度。

### 6.2 块规范化 `_coerce_blocks` / `_repair_monotonic_blocks`

- 解析 JSON 后为每个块裁剪到合法范围，排序。
- `_repair_monotonic_blocks`：按块顺序推进 `cursor_zh` / `cursor_en`，修正越界与顺序，尾部用 `filled_tail` 低置信块补齐。

**决策**：宁可后处理修复，也不在首轮提示词里追求过完美的边界情况，以降低空返回率。

### 6.3 大块细化 `refine_large_blocks_llm`

- 若某块中文或英文跨度 **> 8**（默认 `threshold`），视为「大块」。
- 默认最多对**按跨度排序后的前 2 个大块**（`max_refine_calls`）再调用一次 `align_paragraphs_in_chapter_llm`（子问题：仅该块内的局部段落）。
- 子块坐标**回写到全书章内 1-based 索引**，`reason` 前缀 `refined:`。
- 最后再跑 `_repair_monotonic_blocks`。

**决策**：两阶段（粗 + 局部细）平衡费用与质量；只细化少量最大块，避免全书级调用爆炸。

### 6.4 从块到「每中文段一行英文索引」`flatten_map_from_blocks`

- 模型给出的是**块**，UI 需要**每个中文段落**对应一个英文段落下标（用于并排滚动或高亮）。
- 块内使用 `_even_zh_to_en_indices`：在块内将 `zh_span` 个中文行映射到 `en_span` 个英文索引，**尽量均匀分摊**（多中文对少英文时）；少中文多英文时用端点插值。
- 再对整个 `mapping` 做**非递减修正**（若某格小于前一格则抬升到前一格），与「不回读」的阅读顺序一致。

**决策**：块内映射是**启发式**的，不是模型逐段输出；因此 1:N 块内英文行的「哪一行对哪句中文」可能不精确，但全局顺序一致。

### 6.5 复核列表 `build_review_items`

- `score_alignment_confidence` 综合模型 `confidence` 与中英跨度不平衡；对「多中文对单英文」且置信度尚可时略微降低不平衡惩罚。
- 低于阈值（默认 0.55）的块进入 `review_items`，供前端或人工关注。

## 7. 全书对齐编排（`alignment_service.py`）

### 7.1 `align_book_by_chapter_mapping`

对每一中文 `ChapterSegment`：

1. 用 `chapter_map[c_idx]` 取对应的英文章节索引，切片 `local_zh` / `local_en`。
2. `align_paragraphs_in_chapter_llm` → `refine_large_blocks_llm`。
3. `flatten_map_from_blocks` 得到章内 `local_map`，写入全书 `sync_map[zh_start + i] = en_start + local_value`。
4. 块与 `review_items` 的下标**全部转换为全书段落绝对下标**。
5. 最后对 **`sync_map` 整体**再做一次非递减修正。

### 7.2 `align_single_chapter`

- 仅处理一章，返回 `local_sync_map`（已是**英文绝对段落下标**）、块、复核项，用于前端单章重算或调试。

## 8. Web 服务（`web_server.py`）

- `ThreadingHTTPServer` + `SimpleHTTPRequestHandler`：默认除 POST 外可服务静态文件（根目录 `index.html` 等）。
- **POST `/api/chapter-match`**：`map_chapters_ai`。
- **POST `/api/extract-epub`**：body 内 `epub_base64` → `extract_epub_document_from_bytes` → `paragraphs` + `chapters`。
- **POST `/api/align-paragraphs`**：全书段落对齐（传全书段落与 `chapter_map`）。
- **POST `/api/align-chapter`**：单章对齐。

异常返回 HTTP 400 + `{"error": "..."}`，服务端打印 traceback。

## 9. 前端与数据流（概要）

前端（`app.js`）典型流程：

1. 用户选择两本 EPUB → base64 → `/api/extract-epub` 各一次。
2. 用章节标题列表 → `/api/chapter-match` 得 `chapter_map`（与中文列表等长的 `en_index` 序列）。
3. `/api/align-paragraphs` 得 `sync_map`、`chapter_results`、`review_items`。
4. 本地根据 `sync_map` 渲染中英对照视图（具体 DOM 逻辑见 `app.js`）。

**决策**：**不在浏览器里解析 EPUB**；解析与对齐均在 Python 侧，避免重复实现与密钥暴露（API Key 仅服务器环境）。

## 10. 命令行与测试

- `run_web.sh`：启动 `web_server.py`。
- `paragraph_debug.py` / `chapter_debug.py`：离线跑章节映射与全书对齐，输出文本结果便于 diff。
- `tests/`：`tests/test_align_paragraphs_in_chapter_llm.py` 会在配置了 `OPENAI_API_KEY` 时**真实调用**聊天补全接口；需本机可访问 `OPENAI_API_BASE_URL`（无拦截的 HTTP 代理，或正确配置 `NO_PROXY`）。在沙箱、公司代理返回 403、或未设置 Key 时，测试会跳过或失败，属环境而非业务逻辑错误。
- `.gitignore` 已忽略 `tests/fixtures/*.local.txt` 等本地大文件占位。

## 11. 已知权衡与限制

1. **成本与延迟**：全书对齐 = 1 次章节映射 + 每章至少 1～3 次 LLM（粗对齐 + 可能的大块细化）。
2. **语言假设**：提示词与变量命名以**中-英**译本为主；换语言对需改 prompt 与章节映射逻辑。
3. **sync_map 语义**：表示「每个中文段落锚定到哪个英文段落下标」，块内多对多由均匀/插值展开，**不等于**人工句级对齐。
4. **EPUB 质量**：极差排版或 spine 中非 HTML 内容过多时，章节边界与段落列表可能不理想。

## 12. 与统计对齐器路线的对比（设计层面）

若采用 hunalign 等工具，通常是**全书线性文本**一次性对齐，不强制「先章后段」。本项目的**先章节映射、再章内 LLM** 是为了处理：**章节数不一致、译本增删章节、标题译法差异**等情况，用语义与顺序约束换取对译本文结构的鲁棒性，代价是 API 依赖与工程复杂度。

---

文档版本与仓库代码同步维护；修改核心流程时请更新本节对应段落。
