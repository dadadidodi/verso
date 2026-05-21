# Aligner 使用说明

这份文档给项目 owner：你要在本地制作、校对、修正中英对齐内容，然后导出 Reader 给别人读。

## 你在使用哪一个网站

你使用的是本地 Align app：

```bash
./run_web.sh
```

默认地址是 [http://localhost:8000](http://localhost:8000)。

本地 Align app 是私有制作工具，包含 Library、Read Mode、Alignment Mode、上传、删除、LLM、Anchor 和后台任务。不要把它公开部署。

要分享给别人，导出静态 Reader site。发布流程见 [PUBLISHING.md](PUBLISHING.md)。

## 基本制作流程

1. 打开本地 Align app。
2. 打开 `Library`。
3. 上传中文 EPUB 和英文 EPUB。
4. 创建一个项目。
5. 进入 `Alignment Mode`。
6. 点击 `生成建议`，生成章节映射。
7. 检查中章和英章是否对应。
8. 手动修正错误映射。
9. 点击 `确认映射`。
10. 选择一章，点击 `对齐当前章`。
11. 阅读对齐结果，必要时添加 Anchor。
12. 重新生成该章对齐。
13. 满意后点击 `确认当前章`。
14. 用 `后台对齐剩余章节` 批量处理后续章节。
15. 导出静态 Reader。

## Read Mode 和 Alignment Mode

Read Mode：

- 用来阅读已经存好的结果。
- 不调用 LLM。
- 点击中文段落查看英文原文。
- 可以报告 mismatch，但不直接改 alignment。

Alignment Mode：

- 用来制作和修正内容。
- 可以生成章节映射。
- 可以对齐当前章或后台对齐剩余章节。
- 可以选择 `自动`、`强制 LM`、`禁用 LM`。
- 可以创建 Anchor 修正错配。
- 可以确认、跳过、重新生成章节。

## 章节映射

章节映射决定“中文第几章对应英文第几章”。

推荐流程：

1. 点击 `生成建议`。
2. 检查每一行映射是否合理。
3. 如果错误，手动选择正确英文章节。
4. 点击 `保存手动调整`。
5. 点击 `确认映射`。

映射确认后，面板默认可以折叠。确认映射不会自动确认段落对齐；它只锁定章节配对。

## 段落对齐策略

Alignment Mode 有三个策略：

- `自动`：默认策略，系统决定哪些 segment 用 LLM，哪些用 heuristic。
- `强制 LM`：尽量让非 Anchor segment 走 LLM。
- `禁用 LM`：完全不用 LLM，只走 heuristic。

章节列表里的 draft 标签会显示来源：

- `draft · LM`
- `draft · heuristic`
- `draft · mixed`
- `draft · fallback`

如果想知道为什么走 heuristic 或 LLM，看当前章节面板里的来源摘要，或者查 `log/server_events.log`。

## Anchor 是什么

Anchor 是人工指定的硬约束。它告诉系统：这几段中文必须对应这几段英文。

例子：

```text
中 12-14 ↔ 英 9-10
```

Anchor 可以表示：

- 一段中文对应一段英文。
- 一段中文对应多段英文。
- 多段中文对应一段英文。
- 多段中文对应多段英文。

## 怎么创建 Anchor

1. 进入 `Alignment Mode`。
2. 选择要修正的章节。
3. 展开浮动的 `锚点` 面板。
4. 勾选 `点击添加`。
5. 点击中文起始段。
6. 点击中文结束段。
7. 在右侧英文原文区域点击英文起始段。
8. 再点击英文结束段。
9. 点击 `创建 anchor`。
10. 点击 `强制重算` 或重新对齐当前章。

如果只想选单段，就对同一段点击两次。

## Anchor 和 mismatch report 的区别

Anchor 会改变重新对齐的结果。它是硬约束，重新生成章节时会被 alignment engine 使用。

Mismatch report 只是记录反馈。它不会自动改变结果，适合在阅读时先把“这里不对”记下来，之后再人工决定是否转成 Anchor。

## 加 Anchor 后发生什么

重新生成章节时：

- Anchor block 会原样保留。
- 系统会把 Anchor 前后的空白区间切成 free segments。
- 只重新对齐 free segments。
- 即使用 `强制 LM`，Anchor 本身也不会被 LLM 覆盖。

## PDF 怎么处理

网页只上传 EPUB。

PDF→EPUB 是实验性的离线预处理，不是正式导入能力。转换准确率通常偏低，扫描版、双栏、复杂脚注、页眉页脚、图片文字和古怪排版尤其容易出错；转完后一定要检查 preview、章节切分和正文段落，再决定要不要上传到 Library。

如果仍然要试，把下面的 `path/to/book.pdf` 换成你自己的 PDF 路径：

```bash
python3 -m tools.pdf_to_epub_ocr path/to/book.pdf \
  --language zh \
  --title 书名 \
  --out path/to/book.ocr.epub \
  --work-dir tmp_books/book_ocr \
  --ocr-lang chi_sim+chi_tra+eng \
  --scale 1.0
```

检查生成的 preview 后，把生成的 EPUB 上传到 Library。质量不够时，优先找更干净的 EPUB 来源。
