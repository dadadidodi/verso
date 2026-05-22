# verso Docs

文档按“你想做什么”组织。第一次了解项目，优先看 [USER_GUIDE.md](USER_GUIDE.md)：它用实际宽版截图说明 verso 的阅读和校对工作流。

## 推荐阅读路径

| 你是谁 | 先看 | 用途 |
| --- | --- | --- |
| 第一次看到这个项目 | [USER_GUIDE.md](USER_GUIDE.md) | 看图了解 verso 能做什么，以及本地制作工具和阅读模式怎么配合 |
| 只负责阅读 | [READER.md](READER.md) | 学会打开 Reader、阅读译文、点击查看原文 |
| 项目 owner | [ALIGNER.md](ALIGNER.md) | 使用校对模式制作项目、检查章节配对、修正段落对齐、确认章节 |
| 发布者 | [PUBLISHING.md](PUBLISHING.md) | 导出并部署只读静态 Reader |
| 开发者 | [DEVELOPER.md](DEVELOPER.md) | 找代码入口、运行 verso 工作台和测试 |
| 想看底层设计 | [ARCHITECTURE.md](ARCHITECTURE.md) | 理解 API、数据模型、对齐引擎和导出边界 |

## 先记住这件事

verso 不是一个单一网站：

- verso 工作台是制作工具：私有、本地、可写，有阅读模式、校对模式、AI 辅助、固定对应和后台任务。
- 静态 Reader site 是阅读产品：可分享、只读、轻密码，没有校对模式，也不包含源 EPUB、SQLite、log 或 `.env`。

要分享内容时，只发布静态 Reader site，不要公开部署 verso 工作台。
