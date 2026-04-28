# DuReading

DuReading 是一个双语阅读和翻译校对工具：把中文译文和英文原文按章节、段落对齐，让读者主要读中文，在觉得译文不可靠时快速查看对应英文。它的核心不是“并排对照”，而是“中文主读 + 原文查阅”。内容制作和校对在本地完成，最后可以导出一个只读的静态 Reader 网站分享给别人。

当前 UI slogan：`这要命的译文！！！`

## 它现在能提供什么

- 读者可以打开一个 reader-only 网站，输入阅读密码，按章节阅读中文译文。
- 点击中文段落时，Reader 会显示匹配到的英文原文 block 和少量上下文。
- 项目 owner 可以在本地上传 EPUB、创建中英项目、生成章节映射、做段落对齐、人工加 Anchor 修正错配。
- 对齐结果会存到本地，确认或 draft 的章节都可以导出到静态 Reader。
- PDF 不直接上传到网页；需要先用本地工具一次性转成 EPUB，再走同一套流程。

## 你是谁？

| 你的目标 | 先看这里 |
| --- | --- |
| 我是阅读者/朋友，只想知道怎么读 | [docs/READER.md](docs/READER.md) |
| 我是项目 owner，要制作和校对对齐内容 | [docs/ALIGNER.md](docs/ALIGNER.md) |
| 我要把 Reader 网站发布出去 | [docs/PUBLISHING.md](docs/PUBLISHING.md) |
| 我是 developer，要理解设计或继续开发 | [docs/DEVELOPER.md](docs/DEVELOPER.md) |
| 我要看更底层的技术架构 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |

## 两套网站

DuReading 有两个明确分开的使用形态：

- 本地 Align app：运行在 `localhost:8000`，私有、可写、有 Library、Read Mode、Alignment Mode、上传、删除、章节映射、段落对齐、Anchor、后台任务和可选 LLM 调用。
- 静态 Reader site：从本地项目导出到 `dist-reader/` 后部署，供别人阅读，只读、有前端轻密码、没有 Align Mode、没有上传/删除/LLM/SQLite/log/source EPUB。

不要把本地 Align app 公开部署。要分享内容时，只发布静态 Reader site。

## 最快开始

安装依赖：

```bash
python3 -m pip install -r requirements-dev.txt
```

启动本地 Align app：

```bash
./run_web.sh
```

默认地址是 [http://localhost:8000](http://localhost:8000)。

如果需要 LLM 章节映射或更好的段落对齐，在本地 `.env` 放入：

```env
OPENAI_API_KEY=your-key-here
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1
```

不要提交 `.env`、`storage/`、`log/` 或 `dist-reader/`。

## 最短发布提示

先在本地 Align app 里完成对齐，再导出 reader-only 网站：

```bash
DUREADING_READER_PASSWORDS="private-password,friend-password" ./publish_reader.sh PROJECT_ID
```

部署到 Vercel：

```bash
npx vercel deploy dist-reader --prod
```

完整流程见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。

## 文档目录

完整文档入口在 [docs/README.md](docs/README.md)。
