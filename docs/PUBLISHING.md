# 发布静态 Reader

这份文档给项目 owner：你已经在本地 Align app 里做好对齐，现在想把只读 Reader 网站分享给别人。

## 发布的是哪一个网站

发布的是静态 Reader site，不是本地 Align app。

静态 Reader site 包含：

- `index.html`
- `reader.css`
- `reader.js`
- `manifest.json`
- `chapters/{chapter_index}.json`

静态 Reader site 不包含：

- Alignment Mode。
- Library。
- 上传或删除功能。
- Anchor 编辑。
- 后台任务。
- source EPUB。
- SQLite 数据库。
- `.env` 或 OpenAI key。
- 本地 log 或 LLM debug prompt。

## 密码模型

Reader 可以配置一个或多个阅读密码。

导出时只把密码的 SHA-256 hash 写入 `manifest.json`，不会写入明文密码。但这仍然只是前端轻密码，适合阻挡普通访问，不是强安全边界。

## 第一次导出

确认本地项目已经有 draft 或 confirmed 章节，然后运行：

```bash
DUREADING_READER_PASSWORDS="private-password,friend-password" ./publish_reader.sh PROJECT_ID
```

只需要一个密码时：

```bash
DUREADING_READER_PASSWORD="shared-reader-password" ./publish_reader.sh PROJECT_ID
```

导出结果在 `dist-reader/`。

## 本地预览

```bash
python3 -m http.server 9000 --directory dist-reader
```

打开 [http://localhost:9000](http://localhost:9000)，确认密码、章节和点击查原文都正常。

## 部署到 Vercel

如果已经安装 Vercel CLI：

```bash
vercel deploy dist-reader --prod
```

如果没有全局安装：

```bash
npx vercel deploy dist-reader --prod
```

Vercel 通常会返回两个地址：

- immutable production URL：一次部署一个固定 URL，例如 `https://your-project-xxxxx.vercel.app`。
- stable alias：稳定分享地址，例如 `https://your-project.vercel.app`。

分享给朋友时一般用 stable alias。

## 更新内容但保留旧密码

如果 `dist-reader/manifest.json` 还在，可以复用里面的旧 password hashes：

```bash
python3 - <<'PY' > /tmp/dureading_reader_hash_args.txt
import json
manifest = json.load(open("dist-reader/manifest.json"))
for item in manifest.get("reader_password_hashes") or [manifest["reader_password_hash"]]:
    print("--reader-password-hash", item)
PY

python3 export_reader_site.py --project-id PROJECT_ID --out dist-reader $(cat /tmp/dureading_reader_hash_args.txt)
npx vercel deploy dist-reader --prod
```

## 增加一个朋友密码

重新导出时传多个密码：

```bash
DUREADING_READER_PASSWORDS="private-password,friend-simple-password" ./publish_reader.sh PROJECT_ID
npx vercel deploy dist-reader --prod
```

新部署会同时接受这些密码。

## 手机阅读表现

桌面端保持中文正文和右侧英文 lookup。

手机端会把中文正文作为主页面。点击中文段落后，英文原文从底部弹出；关闭后中文阅读位置不跳。

## 发布前检查

1. 本地打开 `dist-reader/`。
2. 测试所有 reader passwords。
3. 确认章节数量符合预期。
4. 确认手机宽度下底部原文抽屉可用。
5. 确认 `dist-reader/` 没有 source EPUB、SQLite、log 或 `.env`。
6. 部署到 Vercel。
7. 打开 stable alias 再测试一次。
