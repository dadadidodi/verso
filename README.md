# verso 对页

verso 是一个面向文学译本的双语阅读和校对工具：让读者主要读中文译文，在觉得译文不可靠时快速查看对应英文原文。

## 图文版「对页 verso」使用指南

第一次了解 verso，建议先看这份图文入口：[打开图文版使用指南](docs/USER_GUIDE.md)。它用实际宽版截图说明 verso 的阅读模式、校对模式和本地制作流程。

## 它能做什么

- 在本地上传中文 EPUB 和英文 EPUB，创建一个中英项目。
- 用「校对模式」检查章节配对、生成段落对齐、添加「固定对应」修正错配。
- 用「阅读模式」模拟最终阅读体验：读中文，点击段落查看对应英文。
- 把校对好的内容导出成只读静态 Reader 网站，分享给朋友阅读。
- 保持制作工具和阅读网站分离：verso 工作台可写，Reader site 只读。

## 你应该先看哪篇文档

| 你的目标 | 入口 |
| --- | --- |
| 我只是想快速了解 verso 长什么样、能做什么 | [图文版 verso 使用指南](docs/USER_GUIDE.md) |
| 我只想读别人分享的 Reader 网站 | [Reader 使用说明](docs/READER.md) |
| 我要制作、校对、修正一本书 | [校对模式使用说明](docs/ALIGNER.md) |
| 我要把 Reader 网站发布出去 | [发布静态 Reader](docs/PUBLISHING.md) |
| 我要继续开发或跑测试 | [Developer Guide](docs/DEVELOPER.md) |
| 我要看 API、数据模型和架构 | [Architecture](docs/ARCHITECTURE.md) |

完整文档地图见 [docs/README.md](docs/README.md)。

## 两个使用界面

verso 有两个明确分开的形态：

- verso 工作台：私有制作工具，运行在 `localhost`，包含书库、阅读模式、校对模式、上传、删除、章节配对、段落对齐、固定对应、后台任务和可选 LLM 调用。
- 静态 Reader site：从本地项目导出的只读网站，供别人阅读，有轻密码、章节阅读和点击查原文，没有上传、删除、校对、LLM 或数据库。

不要把 verso 工作台公开部署。要分享内容时，只发布静态 Reader site。

## 本地运行

安装依赖：

```bash
python3 -m pip install -r requirements-dev.txt
```

启动 verso 工作台：

```bash
./run_web.sh
```

默认地址是 [http://localhost:8000](http://localhost:8000)。

如果需要 LLM 章节配对或更好的段落对齐，在本地 `.env` 放入：

```env
OPENAI_API_KEY=your-key-here
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1
```

不要提交 `.env`、`storage/`、`log/` 或 `dist-reader/`。

## 导出 Reader

先在 verso 工作台里完成校对，再导出只读 Reader：

```bash
VERSO_READER_PASSWORDS="private-password,friend-password" ./publish_reader.sh PROJECT_ID
```

部署到 Vercel：

```bash
npx vercel deploy dist-reader --prod
```

完整流程见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。
