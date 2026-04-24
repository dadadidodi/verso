# DuReading

中英对照阅读实验工具。

设计与实现说明（EPUB 解析、LLM 章节/段落对齐、`sync_map` 语义、API 与权衡）见 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**。

## 网页版运行

1. 启动本地网页服务（包含章节匹配 API）：

```bash
./run_web.sh
```

默认端口 `8000`，浏览器打开：

- <http://localhost:8000>

可指定端口：

```bash
./run_web.sh 9000
```

## 章节提取/匹配命令行测试

### 1) 配置 `.env`

```env
OPENAI_API_KEY=你的key
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1
```

### 2) 运行固定测试

```bash
./run_match_test.sh
```

说明：
- 会先比对章节映射结果 `result.txt` 与 `ref.txt`。
- 然后执行段落对齐并生成 `paragraph_result.txt`。
- 若存在 `paragraph_ref.txt`，会继续做严格比对。
