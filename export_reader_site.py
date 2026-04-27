#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from storage_v2 import DuReadingStore


READER_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>DuReading Reader</title>
  <link rel="stylesheet" href="reader.css">
</head>
<body>
  <main class="shell">
    <section id="login-panel" class="login-panel">
      <p class="eyebrow">DuReading Reader</p>
      <h1>这要命的译文！！！</h1>
      <p class="muted">请输入阅读密码。这个静态站只包含阅读内容。</p>
      <form id="login-form" class="login-form">
        <input id="password-input" type="password" autocomplete="current-password" placeholder="Reader password">
        <button type="submit">进入阅读</button>
      </form>
      <p id="login-error" class="error hidden">密码不对。</p>
      <p class="fineprint">轻量密码门只用于阻挡普通访问；静态 JSON 不是强安全边界。</p>
    </section>

    <section id="reader-app" class="reader-app hidden">
      <header class="reader-header">
        <div>
          <p class="eyebrow">DuReading Reader</p>
          <h1 id="project-title">Reader</h1>
          <p id="project-meta" class="muted"></p>
        </div>
        <button id="lock-btn" type="button" class="secondary-btn">退出</button>
      </header>
      <section class="reader-grid">
        <aside class="chapter-panel">
          <h2>章节</h2>
          <div id="chapter-list" class="chapter-list"></div>
        </aside>
        <article class="zh-panel">
          <h2 id="chapter-title">译文</h2>
          <div id="zh-content" class="scroll-panel"></div>
        </article>
        <aside class="lookup-panel">
          <div class="lookup-header">
            <h2>原文</h2>
            <span id="lookup-label" class="tag">EN</span>
          </div>
          <div id="lookup-content" class="scroll-panel lookup-content">
            <p class="muted">点击中文段落查看对应英文原文。</p>
          </div>
        </aside>
      </section>
    </section>
  </main>
  <script src="reader.js"></script>
</body>
</html>
"""


READER_CSS = """:root {
  --bg: #eef1eb;
  --panel: #f9f6ef;
  --panel-strong: #fffdfa;
  --line: #d7d0c1;
  --text: #1c1f16;
  --muted: #5d6654;
  --accent: #2f5e4e;
  --accent-soft: #dce7e1;
  --warm: #8a5a2b;
  --shadow: 0 16px 40px rgba(41, 42, 34, 0.08);
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(82, 119, 93, 0.16), transparent 30%),
    linear-gradient(180deg, #f4f1e8 0%, var(--bg) 100%);
  font-family: "Iowan Old Style", "Palatino Linotype", "Noto Serif SC", serif;
}

button,
input {
  font: inherit;
}

button {
  border: 1px solid #3d5e4a;
  background: #8fb5a0;
  color: #0f2218;
  border-radius: 10px;
  padding: 9px 14px;
  cursor: pointer;
}

button:hover {
  background: #7aa088;
}

.secondary-btn {
  background: #e8f0eb;
  color: #1a3d2c;
  border-color: #5d8a6f;
}

.hidden {
  display: none !important;
}

.shell {
  padding: 18px;
}

.login-panel,
.reader-header,
.chapter-panel,
.zh-panel,
.lookup-panel {
  background: rgba(249, 246, 239, 0.92);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow);
}

.login-panel {
  width: min(560px, calc(100vw - 32px));
  margin: 12vh auto 0;
  padding: 28px;
}

.login-panel h1,
.reader-header h1 {
  margin: 0 0 8px;
}

.login-form {
  display: flex;
  gap: 10px;
  margin-top: 18px;
}

.login-form input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: #fffdfa;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--warm);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.muted,
.fineprint {
  color: var(--muted);
}

.fineprint {
  font-size: 12px;
}

.error {
  color: #9a2e24;
}

.reader-app {
  display: grid;
  gap: 12px;
}

.reader-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
}

.reader-grid {
  display: grid;
  grid-template-columns: 220px minmax(560px, 1fr) minmax(320px, 400px);
  gap: 12px;
  align-items: start;
}

.chapter-panel,
.zh-panel,
.lookup-panel {
  padding: 14px;
}

.chapter-panel h2,
.zh-panel h2,
.lookup-panel h2 {
  margin: 0 0 10px;
}

.chapter-list {
  display: grid;
  gap: 8px;
  max-height: calc(100vh - 150px);
  overflow: auto;
}

.chapter-btn {
  text-align: left;
  background: #fffdfa;
  border-color: var(--line);
}

.chapter-btn.active {
  background: var(--accent-soft);
  border-color: var(--accent);
}

.scroll-panel {
  height: calc(100vh - 150px);
  min-height: 560px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(240, 245, 241, 0.9);
  padding: 16px;
}

.para {
  margin: 0 0 10px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: rgba(255, 253, 250, 0.68);
  line-height: 1.64;
  font-size: 17px;
  cursor: pointer;
}

.para.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.lookup-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.tag {
  display: inline-flex;
  border: 1px solid var(--warm);
  color: var(--warm);
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
}

.lookup-para {
  margin: 0 0 8px;
  padding: 9px 10px;
  border-left: 3px solid transparent;
  border-radius: 8px;
  color: #5b6558;
  background: rgba(255, 253, 250, 0.55);
  line-height: 1.62;
}

.lookup-para.active {
  color: #263228;
  border-left-color: var(--accent);
  background: rgba(220, 231, 225, 0.92);
}

.lookup-index {
  display: block;
  margin-bottom: 4px;
  color: var(--warm);
  font-size: 11px;
  letter-spacing: 0.04em;
}

@media (max-width: 1100px) {
  .reader-grid {
    grid-template-columns: 1fr;
  }

  .scroll-panel,
  .chapter-list {
    height: auto;
    min-height: 40vh;
    max-height: none;
  }

  .reader-header,
  .login-form {
    flex-direction: column;
    align-items: stretch;
  }
}
"""


READER_JS = """const state = {
  manifest: null,
  currentChapter: null,
  currentChapterIndex: null,
  activeZhIndex: null,
};

const els = {
  loginPanel: document.getElementById("login-panel"),
  loginForm: document.getElementById("login-form"),
  passwordInput: document.getElementById("password-input"),
  loginError: document.getElementById("login-error"),
  readerApp: document.getElementById("reader-app"),
  projectTitle: document.getElementById("project-title"),
  projectMeta: document.getElementById("project-meta"),
  chapterList: document.getElementById("chapter-list"),
  chapterTitle: document.getElementById("chapter-title"),
  zhContent: document.getElementById("zh-content"),
  lookupLabel: document.getElementById("lookup-label"),
  lookupContent: document.getElementById("lookup-content"),
  lockBtn: document.getElementById("lock-btn"),
};

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function authKey() {
  const hashes = passwordHashes();
  return `dureading_reader_auth_${hashes.join("_").slice(0, 32)}`;
}

function isUnlocked() {
  return sessionStorage.getItem(authKey()) === "1";
}

function setUnlocked(value) {
  if (value) {
    sessionStorage.setItem(authKey(), "1");
  } else {
    sessionStorage.removeItem(authKey());
  }
}

function showLogin() {
  els.loginPanel.classList.remove("hidden");
  els.readerApp.classList.add("hidden");
  els.passwordInput.focus();
}

function showReader() {
  els.loginPanel.classList.add("hidden");
  els.readerApp.classList.remove("hidden");
}

function englishRangeForZh(chapter, zhIndex) {
  const raw = Array.isArray(chapter.en_ranges_by_zh) ? chapter.en_ranges_by_zh[zhIndex] : null;
  if (Array.isArray(raw) && raw.length >= 2) {
    const start = Number(raw[0] || 0);
    const end = Number(raw[1] ?? start);
    return { start: Math.max(0, Math.min(start, end)), end: Math.max(start, end) };
  }
  const fallback = Number((chapter.local_sync_map || [])[zhIndex] || 0);
  return { start: fallback, end: fallback };
}

function englishContextWindow(enLength, range, before = 1, after = 1) {
  const rangeStart = Math.max(0, Math.min(enLength - 1, Number(range.start || 0)));
  const rangeEnd = Math.max(rangeStart, Math.min(enLength - 1, Number(range.end ?? rangeStart)));
  return {
    start: Math.max(0, rangeStart - before),
    end: Math.min(enLength - 1, rangeEnd + after),
  };
}

function formatEnglishRange(range) {
  const start = Number(range.start || 0) + 1;
  const end = Number(range.end ?? range.start ?? 0) + 1;
  return start === end ? `EN ${start}` : `EN ${start}-${end}`;
}

function renderManifest() {
  els.projectTitle.textContent = state.manifest.project_title || "DuReading Reader";
  els.projectMeta.textContent = `${state.manifest.chapters.length} readable chapters · generated ${state.manifest.generated_at}`;
  els.chapterList.innerHTML = state.manifest.chapters
    .map((chapter) => {
      const active = chapter.chapter_index === state.currentChapterIndex ? " active" : "";
      return `<button class="chapter-btn${active}" type="button" data-chapter-index="${chapter.chapter_index}">中${chapter.chapter_index + 1}. ${escapeHtml(chapter.zh_title || "Untitled")}</button>`;
    })
    .join("");
}

function renderLookup(range) {
  const chapter = state.currentChapter;
  if (!chapter || !range) {
    els.lookupLabel.textContent = "EN";
    els.lookupContent.innerHTML = `<p class="muted">点击中文段落查看对应英文原文。</p>`;
    return;
  }
  els.lookupLabel.textContent = formatEnglishRange(range);
  const context = englishContextWindow(chapter.en_paragraphs.length, range);
  const lines = [];
  for (let enIndex = context.start; enIndex <= context.end; enIndex += 1) {
    const text = chapter.en_paragraphs[enIndex];
    if (!text) {
      continue;
    }
    const active = enIndex >= range.start && enIndex <= range.end ? " active" : "";
    lines.push(`<p class="lookup-para${active}"><span class="lookup-index">EN ${enIndex + 1}</span>${escapeHtml(text)}</p>`);
  }
  els.lookupContent.innerHTML = lines.join("") || `<p class="muted">当前中文段暂无英文对应。</p>`;
}

function renderChapter() {
  const chapter = state.currentChapter;
  if (!chapter) {
    els.chapterTitle.textContent = "译文";
    els.zhContent.innerHTML = `<p class="muted">请选择章节。</p>`;
    renderLookup(null);
    return;
  }
  els.chapterTitle.textContent = `中${chapter.chapter_index + 1}《${chapter.zh_title || "Untitled"}》 ↔ 《${chapter.en_title || "Untitled"}》`;
  els.zhContent.innerHTML = chapter.zh_paragraphs
    .map((text, index) => `<p class="para" data-index="${index}">${escapeHtml(text)}</p>`)
    .join("");
  renderLookup(null);
  renderManifest();
}

async function loadChapter(chapterIndex) {
  const meta = state.manifest.chapters.find((item) => item.chapter_index === chapterIndex);
  if (!meta) {
    return;
  }
  const response = await fetch(meta.chapter_file);
  if (!response.ok) {
    throw new Error(`Failed to load chapter ${chapterIndex + 1}`);
  }
  state.currentChapter = await response.json();
  state.currentChapterIndex = chapterIndex;
  state.activeZhIndex = null;
  renderChapter();
}

async function unlockWithPassword(password) {
  const hash = await sha256Hex(password);
  return passwordHashes().includes(hash);
}

function passwordHashes() {
  const hashes = Array.isArray(state.manifest?.reader_password_hashes)
    ? state.manifest.reader_password_hashes
    : [];
  if (state.manifest?.reader_password_hash) {
    hashes.push(state.manifest.reader_password_hash);
  }
  return [...new Set(hashes.filter(Boolean))];
}

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.loginError.classList.add("hidden");
  if (await unlockWithPassword(els.passwordInput.value)) {
    setUnlocked(true);
    showReader();
    await loadChapter(state.manifest.chapters[0].chapter_index);
  } else {
    setUnlocked(false);
    els.loginError.classList.remove("hidden");
  }
});

els.lockBtn.addEventListener("click", () => {
  setUnlocked(false);
  state.currentChapter = null;
  state.currentChapterIndex = null;
  showLogin();
});

els.chapterList.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-chapter-index]");
  if (!btn) {
    return;
  }
  loadChapter(Number(btn.dataset.chapterIndex)).catch((error) => {
    els.zhContent.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  });
});

els.zhContent.addEventListener("click", (event) => {
  const para = event.target.closest(".para[data-index]");
  if (!para || !state.currentChapter) {
    return;
  }
  const zhIndex = Number(para.dataset.index);
  state.activeZhIndex = zhIndex;
  els.zhContent.querySelectorAll(".para.active").forEach((el) => el.classList.remove("active"));
  para.classList.add("active");
  renderLookup(englishRangeForZh(state.currentChapter, zhIndex));
});

async function boot() {
  const response = await fetch("manifest.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Failed to load manifest.json");
  }
  state.manifest = await response.json();
  if (!state.manifest.chapters.length) {
    els.loginPanel.innerHTML = `<h1>暂无可阅读章节</h1><p class="muted">请先在本地 Align app 确认章节后重新导出。</p>`;
    return;
  }
  if (isUnlocked()) {
    showReader();
    await loadChapter(state.manifest.chapters[0].chapter_index);
  } else {
    showLogin();
  }
}

boot().catch((error) => {
  els.loginPanel.classList.remove("hidden");
  els.loginPanel.innerHTML = `<h1>Reader failed to load</h1><p class="error">${escapeHtml(error.message)}</p>`;
});
"""


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def normalize_password_hashes(*, password_hashes: Sequence[str], password_hash_value: str = "") -> List[str]:
    hashes: List[str] = []
    for value in [password_hash_value, *password_hashes]:
        clean = value.strip().lower()
        if not clean:
            continue
        if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
            raise ValueError(f"invalid reader password hash: {value}")
        if clean not in hashes:
            hashes.append(clean)
    if not hashes:
        raise ValueError("at least one reader password hash is required")
    return hashes


def _ranges_from_alignment(alignment: Dict[str, Any], zh_len: int, en_len: int) -> List[List[int]]:
    sync_map = [int(item) for item in alignment.get("local_sync_map", [])]
    ranges: List[List[int]] = []
    for zh_index in range(zh_len):
        fallback = sync_map[zh_index] if zh_index < len(sync_map) else 0
        fallback = max(0, min(max(0, en_len - 1), fallback))
        ranges.append([fallback, fallback])
    for block in alignment.get("blocks", []):
        zh_start = max(0, int(block.get("zh_start", 1)) - 1)
        zh_end = min(zh_len - 1, int(block.get("zh_end", zh_start + 1)) - 1)
        en_start = max(0, min(max(0, en_len - 1), int(block.get("en_start", 1)) - 1))
        en_end = max(en_start, min(max(0, en_len - 1), int(block.get("en_end", en_start + 1)) - 1))
        for zh_index in range(zh_start, zh_end + 1):
            ranges[zh_index] = [en_start, en_end]
    return ranges


def _clean_sync_map(sync_map: Sequence[Any], en_len: int) -> List[int]:
    max_en = max(0, en_len - 1)
    return [max(0, min(max_en, int(item))) for item in sync_map]


def export_reader_site(
    *,
    project_id: int,
    out_dir: Path,
    reader_password_hash: str = "",
    reader_password_hashes: Sequence[str] = (),
    storage_root: Path | str = "storage",
) -> Dict[str, Any]:
    password_hashes = normalize_password_hashes(
        password_hash_value=reader_password_hash,
        password_hashes=reader_password_hashes,
    )
    store = DuReadingStore(storage_root)
    overview = store.build_project_overview(project_id)
    project = overview["project"]
    zh_paragraphs, _ = store.load_book_document(int(project["zh_book_id"]))
    en_paragraphs, en_chapters = store.load_book_document(int(project["en_book_id"]))

    if out_dir.exists():
        shutil.rmtree(out_dir)
    chapters_dir = out_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    manifest_chapters: List[Dict[str, Any]] = []
    for chapter in overview["chapters"]:
        chapter_index = int(chapter["zh_chapter_index"])
        alignment = store.get_chapter_alignment(project_id, chapter_index)
        if alignment is None:
            continue
        alignment_state = str(alignment.get("state") or "")
        if alignment_state not in {"confirmed", "draft"}:
            continue
        en_index = chapter.get("mapped_en_chapter_index")
        if en_index is None or not (0 <= int(en_index) < len(en_chapters)):
            continue
        zh_start = int(chapter["zh_start"])
        zh_end = int(chapter["zh_end"])
        en_chapter = en_chapters[int(en_index)]
        en_start = int(en_chapter.get("start", 0))
        en_end = int(en_chapter.get("end", 0))
        local_zh = zh_paragraphs[zh_start : zh_end + 1]
        local_en = en_paragraphs[en_start : en_end + 1]
        chapter_file = f"chapters/{chapter_index}.json"
        chapter_payload = {
            "chapter_index": chapter_index,
            "zh_title": str(chapter.get("zh_title") or ""),
            "en_title": str(chapter.get("mapped_en_title") or ""),
            "zh_paragraphs": local_zh,
            "en_paragraphs": local_en,
            "en_ranges_by_zh": _ranges_from_alignment(alignment, len(local_zh), len(local_en)),
            "local_sync_map": _clean_sync_map(alignment.get("local_sync_map", []), len(local_en)),
            "alignment_state": alignment_state,
        }
        (out_dir / chapter_file).write_text(
            json.dumps(chapter_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest_chapters.append(
            {
                "chapter_index": chapter_index,
                "zh_title": chapter_payload["zh_title"],
                "en_title": chapter_payload["en_title"],
                "chapter_file": chapter_file,
                "alignment_state": alignment_state,
            }
        )

    if not manifest_chapters:
        raise ValueError(f"project {project_id} has no draft or confirmed chapters to export")

    manifest = {
        "version": 1,
        "project_id": project_id,
        "project_title": f"{project.get('zh_title', '')} ↔ {project.get('en_title', '')}",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "reader_password_hash": password_hashes[0],
        "reader_password_hashes": password_hashes,
        "chapters": manifest_chapters,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "index.html").write_text(READER_INDEX_HTML, encoding="utf-8")
    (out_dir / "reader.css").write_text(READER_CSS, encoding="utf-8")
    (out_dir / "reader.js").write_text(READER_JS, encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a draft/confirmed DuReading project as a static reader site.")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--out", type=Path, default=Path("dist-reader"))
    parser.add_argument("--storage-root", type=Path, default=Path("storage"))
    parser.add_argument("--reader-password", action="append", default=[], help="Plain reader password; only its SHA-256 hash is exported. Can be repeated.")
    parser.add_argument("--reader-password-hash", action="append", default=[], help="Precomputed SHA-256 reader password hash. Can be repeated.")
    args = parser.parse_args()

    hash_values = [password_hash(password) for password in args.reader_password]
    hash_values.extend(args.reader_password_hash)
    if not hash_values:
        parser.error("provide at least one --reader-password or --reader-password-hash")
    manifest = export_reader_site(
        project_id=args.project_id,
        out_dir=args.out,
        reader_password_hashes=hash_values,
        storage_root=args.storage_root,
    )
    print(f"Exported {len(manifest['chapters'])} readable chapters to {args.out}")
    print("Preview locally: python3 -m http.server 9000 --directory", args.out)
    print("Deploy to Vercel: vercel deploy", args.out, "--prod")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
