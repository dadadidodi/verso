# DuReading Docs

这里按“你想做什么”组织文档，而不是按文件类型组织。

| 目标 | 文档 |
| --- | --- |
| 只想读别人分享的 Reader 网站 | [READER.md](READER.md) |
| 想制作、校对、修正对齐内容 | [ALIGNER.md](ALIGNER.md) |
| 想导出并部署静态 Reader | [PUBLISHING.md](PUBLISHING.md) |
| 想继续开发、跑测试、看代码入口 | [DEVELOPER.md](DEVELOPER.md) |
| 想看数据模型/API/alignment engine 设计 | [ARCHITECTURE.md](ARCHITECTURE.md) |

## 先记住这件事

DuReading 不是一个单一网站。

- 本地 Align app 是制作工具：私有、本地、可写、有 LLM、有 Alignment Mode。
- 静态 Reader site 是阅读产品：可分享、只读、轻密码、没有 Alignment Mode。

如果你是新用户，先从 [README.md](../README.md) 和 [READER.md](READER.md) 看起。如果你是项目 owner，直接看 [ALIGNER.md](ALIGNER.md)。
