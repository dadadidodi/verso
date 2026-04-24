const zhInput = document.getElementById("zh-input");
const enInput = document.getElementById("en-input");
const zhEpubInput = document.getElementById("zh-epub");
const enEpubInput = document.getElementById("en-epub");
const loadBtn = document.getElementById("load-btn");
const reapplyBtn = document.getElementById("reapply-btn");
const clearAnchorsBtn = document.getElementById("clear-anchors-btn");
const anchorModeInput = document.getElementById("anchor-mode");
const anchorHint = document.getElementById("anchor-hint");
const anchorList = document.getElementById("anchor-list");
const chapterPanel = document.getElementById("chapter-panel");
const chapterList = document.getElementById("chapter-list");
const paragraphReviewList = document.getElementById("paragraph-review-list");
const suggestChaptersBtn = document.getElementById("suggest-chapters-btn");
const exportMappingBtn = document.getElementById("export-mapping-btn");
const importMappingBtn = document.getElementById("import-mapping-btn");
const importMappingFile = document.getElementById("import-mapping-file");
const applyChaptersBtn = document.getElementById("apply-chapters-btn");
const alignCurrentChapterBtn = document.getElementById("align-current-chapter-btn");
const confirmCurrentChapterBtn = document.getElementById("confirm-current-chapter-btn");
const skipCurrentChapterBtn = document.getElementById("skip-current-chapter-btn");
const nextChapterBtn = document.getElementById("next-chapter-btn");
const prevChapterBtn = document.getElementById("prev-chapter-btn");
const chapterProgress = document.getElementById("chapter-progress");
const exportProgressBtn = document.getElementById("export-progress-btn");
const importProgressBtn = document.getElementById("import-progress-btn");
const importProgressFile = document.getElementById("import-progress-file");
const exportParaMappingBtn = document.getElementById("export-para-mapping-btn");
const importParaMappingBtn = document.getElementById("import-para-mapping-btn");
const importParaMappingFile = document.getElementById("import-para-mapping-file");
const chapterQuickActions = document.getElementById("chapter-quick-actions");
const quickChapterMeta = document.getElementById("quick-chapter-meta");
const zhScroll = document.getElementById("zh-scroll");
const enScroll = document.getElementById("en-scroll");
const statusText = document.getElementById("status-text");
const statusSummaryEl = document.getElementById("status-summary");
const activityLogEl = document.getElementById("activity-log");
const clearLogBtn = document.getElementById("clear-log-btn");

const MAX_ACTIVITY_LOG_LINES = 200;

let zhParagraphs = [];
let enParagraphs = [];
let zhElements = [];
let enElements = [];
let isSyncing = false;
let activeIndex = -1;
let syncMap = [];
let syncQueued = false;
let anchors = [];
let pendingZhAnchor = null;
let zhOffsets = [];
let activeZhIndex = -1;
let activeEnIndex = -1;
let zhChapters = [];
let enChapters = [];
let chapterMap = [];
let chapterMatchMeta = [];
let paragraphReviewItems = [];
let chapterMappingReady = false;
let chapterMappingApproved = false;
let chapterFlowStarted = false;
let currentChapterIndex = 0;
let chapterDraftResults = {};
let chapterConfirmedResults = {};
let renderedZhGlobalIndexes = [];
let renderedEnGlobalIndexes = [];
let renderedSyncMap = [];
let readerScope = { mode: "book", chapterIndex: -1, zhStart: 0, zhEnd: -1, enStart: 0, enEnd: -1 };
let pairHoverClearTimer = null;

function formatNowForLog() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function logActivity(message, isError = false) {
  if (!activityLogEl) {
    return;
  }
  const line = document.createElement("div");
  line.className = isError ? "log-line err" : "log-line";
  line.textContent = `[${formatNowForLog()}] ${message}`;
  activityLogEl.appendChild(line);
  while (activityLogEl.children.length > MAX_ACTIVITY_LOG_LINES) {
    activityLogEl.removeChild(activityLogEl.firstChild);
  }
  activityLogEl.scrollTop = activityLogEl.scrollHeight;
}

function refreshStatusSummary() {
  if (!statusSummaryEl) {
    return;
  }
  const zhN = zhParagraphs.length;
  const enN = enParagraphs.length;
  const zhCh = zhChapters.length;
  const enCh = enChapters.length;
  const mapReady = chapterMappingReady ? "已就绪" : "未就绪";
  const mapApproved = chapterMappingApproved ? "已确认" : "未确认";
  const flow = chapterFlowStarted ? "已进入" : "未进入";
  const totalCh = zhCh || 0;
  const curLabel = chapterFlowStarted && totalCh ? `${currentChapterIndex + 1}/${totalCh}` : "—";
  const confirmed = getConfirmedChapterCount();
  let chapterLine = "—";
  if (chapterFlowStarted && zhCh) {
    const d = chapterDraftResults[currentChapterIndex];
    const c = chapterConfirmedResults[currentChapterIndex];
    if (c?.skipped) {
      chapterLine = "本章已跳过（占位映射）";
    } else if (c) {
      chapterLine = "本章已确认并写入总映射";
    } else if (d) {
      chapterLine = "本章有 AI 对齐草稿，待确认";
    } else {
      chapterLine = "本章尚未对齐";
    }
  }
  let readerLine = "全书视图";
  if (readerScope.mode === "chapter" && readerScope.zhEnd >= readerScope.zhStart) {
    readerLine = `当前章视图 · 中文全局段号 ${readerScope.zhStart + 1}–${readerScope.zhEnd + 1} · 英文 ${readerScope.enStart + 1}–${readerScope.enEnd + 1}`;
  }
  const lines = [
    "段落对齐: 后端 LLM（章内块映射）",
    `文本: 中文 ${zhN} 段 / 英文 ${enN} 段`,
    `章节: 中文 ${zhCh} 章 / 英文 ${enCh} 章`,
    `章节映射: ${mapReady} · 对应关系 ${mapApproved} · 逐章流程 ${flow}`,
    `逐章进度: 当前中文章节 ${curLabel} · 已确认 ${confirmed}/${totalCh || "—"} 章`,
    `当前章状态: ${chapterLine}`,
    `阅读区: ${readerLine}`,
    `待审: 低置信条目 ${paragraphReviewItems.length} 条 · 锚点标记 ${anchors.length} 组`,
  ];
  statusSummaryEl.textContent = lines.join("\n");
}

function setStatus(message, isError = false, logOptions = {}) {
  const { skipLog = false } = logOptions;
  statusText.textContent = message;
  statusText.classList.toggle("error", isError);
  if (!skipLog) {
    logActivity(message, isError);
  }
  refreshStatusSummary();
}

function parseParagraphs(text) {
  return text
    .split(/\n\s*\n/g)
    .map((p) => p.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return window.btoa(binary);
}

async function extractEpubDocument(file, sideLabel) {
  setStatus(`正在解析${sideLabel} EPUB（${(file.size / 1024 / 1024).toFixed(2)} MB）...`);
  const buffer = await file.arrayBuffer();
  const response = await fetch("/api/extract-epub", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      epub_base64: arrayBufferToBase64(buffer),
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error || `${sideLabel} EPUB 解析失败。`);
  }
  if (!Array.isArray(payload?.paragraphs) || !Array.isArray(payload?.chapters)) {
    throw new Error(`${sideLabel} EPUB 解析返回格式错误。`);
  }
  return { paragraphs: payload.paragraphs, chapters: payload.chapters };
}

function createParagraphElement(content, index, isEmpty = false) {
  const p = document.createElement("p");
  p.className = "para";
  p.dataset.index = String(index);
  p.textContent = isEmpty ? " " : content;
  if (isEmpty) {
    p.classList.add("empty");
  }
  return p;
}

async function alignParagraphsViaServer() {
  setStatus("正在调用章内段落对齐服务...");
  const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
  const response = await fetch("/api/align-paragraphs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      zh_paragraphs: zhParagraphs,
      en_paragraphs: enParagraphs,
      zh_chapters: zhChapters,
      en_chapters: enChapters,
      chapter_map: chapterMap,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error || "段落对齐服务请求失败。");
  }
  if (!Array.isArray(payload?.sync_map)) {
    throw new Error("段落对齐服务返回格式错误。");
  }
  const reviewItems = Array.isArray(payload?.review_items) ? payload.review_items : [];
  const elapsed = Math.round(
    (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
  );
  setStatus(`章内对齐完成，低置信条目 ${reviewItems.length} 个（请求耗时约 ${elapsed} ms，后端详见终端）。`);
  logActivity(`POST /api/align-paragraphs 结束 · ${elapsed} ms · review_items=${reviewItems.length}`);
  return {
    syncMap: normalizeSyncMapLength(
      payload.sync_map,
      zhParagraphs.length,
      Math.max(0, enParagraphs.length - 1),
    ),
    reviewItems,
  };
}

function renderParagraphReviewItems() {
  paragraphReviewList.innerHTML = "";
  if (!paragraphReviewItems.length) {
    paragraphReviewList.innerHTML = "<div class=\"review-item\">没有低置信条目。</div>";
    return;
  }
  paragraphReviewItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "review-item";
    row.textContent = `章${Number(item.chapter_index) + 1} | 中[${Number(item.zh_start) + 1}-${Number(item.zh_end) + 1}] -> 英[${Number(item.en_start) + 1}-${Number(item.en_end) + 1}] | conf=${Number(item.confidence).toFixed(3)} | ${item.reason || "low_confidence"}`;
    paragraphReviewList.appendChild(row);
  });
  refreshStatusSummary();
}

function mergeConfirmedSyncMap() {
  syncMap = new Array(zhParagraphs.length).fill(0);
  const confirmedIndexes = Object.keys(chapterConfirmedResults)
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v))
    .sort((a, b) => a - b);
  confirmedIndexes.forEach((idx) => {
    const result = chapterConfirmedResults[idx];
    if (!result || !result.zh_range || !Array.isArray(result.local_sync_map)) {
      return;
    }
    const start = Number(result.zh_range.start);
    const end = Number(result.zh_range.end);
    for (let i = start; i <= end; i += 1) {
      const localIdx = i - start;
      const mapped = Number(result.local_sync_map[localIdx] ?? 0);
      syncMap[i] = mapped;
    }
  });
  const enCap = Math.max(0, enParagraphs.length - 1);
  confirmedIndexes.forEach((idx) => {
    const result = chapterConfirmedResults[idx];
    if (!result || !result.zh_range || !Array.isArray(result.local_sync_map)) {
      return;
    }
    const start = Number(result.zh_range.start);
    const end = Number(result.zh_range.end);
    if (start > end) {
      return;
    }
    let last = Number(syncMap[start]);
    if (!Number.isFinite(last)) {
      last = 0;
    }
    last = Math.max(0, Math.min(enCap, last));
    syncMap[start] = last;
    for (let i = start + 1; i <= end; i += 1) {
      let v = Number(syncMap[i]);
      if (!Number.isFinite(v)) {
        v = last;
      }
      if (v < last) {
        v = last;
      }
      v = Math.max(0, Math.min(enCap, v));
      syncMap[i] = v;
      last = v;
    }
  });
}

function getConfirmedChapterCount() {
  return Object.keys(chapterConfirmedResults).length;
}

function getChapterScope(chapterIndex) {
  const idx = Math.max(0, Math.min(zhChapters.length - 1, chapterIndex));
  const zhChapter = zhChapters[idx] || { start: 0, end: Math.max(0, zhParagraphs.length - 1), title: "" };
  const enChapterIndex = Math.max(0, Math.min(enChapters.length - 1, Number(chapterMap[idx] ?? 0)));
  const enChapter = enChapters[enChapterIndex] || { start: 0, end: Math.max(0, enParagraphs.length - 1), title: "" };
  return {
    mode: "chapter",
    chapterIndex: idx,
    mappedEnChapterIndex: enChapterIndex,
    zhStart: Number(zhChapter.start) || 0,
    zhEnd: Number(zhChapter.end) || 0,
    enStart: Number(enChapter.start) || 0,
    enEnd: Number(enChapter.end) || 0,
  };
}

function getBookScope() {
  return {
    mode: "book",
    chapterIndex: -1,
    mappedEnChapterIndex: -1,
    zhStart: 0,
    zhEnd: Math.max(0, zhParagraphs.length - 1),
    enStart: 0,
    enEnd: Math.max(0, enParagraphs.length - 1),
  };
}

function updateQuickChapterMeta() {
  if (!quickChapterMeta) {
    return;
  }
  if (!chapterFlowStarted || !zhChapters.length || !enChapters.length) {
    quickChapterMeta.textContent = "未进入逐章模式。";
    return;
  }
  const scope = getChapterScope(currentChapterIndex);
  const zhTitle = (zhChapters[currentChapterIndex]?.title || "未命名章节").trim();
  const enTitle = (enChapters[scope.mappedEnChapterIndex]?.title || "Untitled chapter").trim();
  quickChapterMeta.textContent = `当前：中${currentChapterIndex + 1}《${zhTitle}》 -> 英${scope.mappedEnChapterIndex + 1}《${enTitle}》`;
}

function updateChapterProgress() {
  if (!chapterFlowStarted) {
    chapterProgress.textContent = "当前未进入逐章对齐模式。";
    updateQuickChapterMeta();
    return;
  }
  const total = zhChapters.length;
  const confirmed = getConfirmedChapterCount();
  const current = Math.min(total - 1, Math.max(0, currentChapterIndex));
  const mapped = chapterMap[current];
  const zhTitle = (zhChapters[current]?.title || "未命名章节").trim();
  const enTitle = (enChapters[mapped]?.title || "Untitled chapter").trim();
  chapterProgress.textContent = `当前章节：中${current + 1}《${zhTitle}》 -> 英${mapped + 1}《${enTitle}》；已确认 ${confirmed}/${total}。`;
  updateQuickChapterMeta();
  refreshStatusSummary();
}

function updateChapterActionButtons() {
  const hasFlow = chapterFlowStarted && zhChapters.length > 0;
  const hasChapters = zhChapters.length > 0 && enChapters.length > 0;
  const canEnterChapterFlow = hasChapters && zhChapters.length > 1 && enChapters.length > 1;
  reapplyBtn.disabled = hasFlow;
  suggestChaptersBtn.disabled = !hasChapters || hasFlow;
  applyChaptersBtn.disabled = !canEnterChapterFlow || hasFlow || !chapterMappingReady;
  exportMappingBtn.disabled = !hasChapters || !chapterMappingReady;
  importMappingBtn.disabled = !hasChapters || hasFlow;
  alignCurrentChapterBtn.disabled = !hasFlow;
  confirmCurrentChapterBtn.disabled = !hasFlow || !chapterDraftResults[currentChapterIndex];
  skipCurrentChapterBtn.disabled = !hasFlow;
  prevChapterBtn.disabled = !hasFlow || currentChapterIndex <= 0;
  const currentConfirmed = Boolean(chapterConfirmedResults[currentChapterIndex]);
  nextChapterBtn.disabled = !hasFlow || !currentConfirmed || currentChapterIndex >= zhChapters.length - 1;
  exportProgressBtn.disabled = !hasFlow;
  importProgressBtn.disabled = !hasFlow;
  exportParaMappingBtn.disabled = !hasFlow || !hasAnyParagraphMapping();
  importParaMappingBtn.disabled = !hasChapters || hasFlow;
  if (chapterQuickActions) {
    chapterQuickActions.classList.toggle("hidden", !hasFlow);
  }
}

async function alignCurrentChapter() {
  if (!chapterFlowStarted) {
    throw new Error("请先进入逐章对齐模式。");
  }
  const chapterIndex = currentChapterIndex;
  setStatus(`正在对齐当前章节：中${chapterIndex + 1}...`);
  const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
  const response = await fetch("/api/align-chapter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      zh_paragraphs: zhParagraphs,
      en_paragraphs: enParagraphs,
      zh_chapters: zhChapters,
      en_chapters: enChapters,
      chapter_map: chapterMap,
      chapter_index: chapterIndex,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error || "当前章节对齐失败。");
  }
  chapterDraftResults[chapterIndex] = payload;
  paragraphReviewItems = Array.isArray(payload?.review_items) ? payload.review_items : [];
  renderParagraphReviewItems();
  updateChapterActionButtons();
  const elapsed = Math.round(
    (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
  );
  const revN = paragraphReviewItems.length;
  setStatus(
    `当前章节对齐完成：中${chapterIndex + 1}（请求约 ${elapsed} ms，低置信 ${revN} 条）。请确认后继续下一章节。`,
  );
  logActivity(`POST /api/align-chapter 结束 · 中${chapterIndex + 1} · ${elapsed} ms · review=${revN}`);
}

function confirmCurrentChapter() {
  const draft = chapterDraftResults[currentChapterIndex];
  if (!draft) {
    throw new Error("当前章节还未对齐，请先点击“对齐当前章节”。");
  }
  chapterConfirmedResults[currentChapterIndex] = draft;
  paragraphReviewItems = Array.isArray(draft.review_items) ? draft.review_items : [];
  renderParagraphReviewItems();
  mergeConfirmedSyncMap();
}

function buildSkippedChapterResult(chapterIndex) {
  const scope = getChapterScope(chapterIndex);
  const zhLength = Math.max(0, scope.zhEnd - scope.zhStart + 1);
  const localSyncMap = [];
  let lastGlobal = scope.enStart;

  for (let i = 0; i < zhLength; i += 1) {
    let mappedGlobal;
    if (
      readerScope.mode === "chapter"
      && readerScope.chapterIndex === chapterIndex
      && i < renderedSyncMap.length
    ) {
      mappedGlobal = scope.enStart + Number(renderedSyncMap[i] ?? 0);
    } else {
      mappedGlobal = Number(syncMap[scope.zhStart + i]);
    }
    if (!Number.isFinite(mappedGlobal)) {
      mappedGlobal = lastGlobal;
    }
    mappedGlobal = Math.max(scope.enStart, Math.min(scope.enEnd, mappedGlobal));
    if (mappedGlobal < lastGlobal) {
      mappedGlobal = lastGlobal;
    }
    localSyncMap.push(mappedGlobal);
    lastGlobal = mappedGlobal;
  }

  return {
    chapter_index: chapterIndex,
    mapped_en_chapter_index: scope.mappedEnChapterIndex,
    blocks: [],
    local_sync_map: localSyncMap,
    review_items: [],
    zh_range: { start: scope.zhStart, end: scope.zhEnd },
    en_range: { start: scope.enStart, end: scope.enEnd },
    skipped: true,
  };
}

function skipCurrentChapter() {
  chapterConfirmedResults[currentChapterIndex] = buildSkippedChapterResult(currentChapterIndex);
  delete chapterDraftResults[currentChapterIndex];
  paragraphReviewItems = [];
  renderParagraphReviewItems();
  mergeConfirmedSyncMap();
}

function buildProgressSnapshot() {
  return {
    version: 1,
    zh_titles: zhChapters.map((c) => (c.title || "").trim()),
    en_titles: enChapters.map((c) => (c.title || "").trim()),
    chapter_map: chapterMap,
    current_chapter_index: currentChapterIndex,
    confirmed_results: chapterConfirmedResults,
  };
}

function buildChapterMappingSnapshot() {
  return {
    version: 1,
    type: "chapter_mapping",
    zh_titles: zhChapters.map((c) => (c.title || "").trim()),
    en_titles: enChapters.map((c) => (c.title || "").trim()),
    chapter_map: chapterMap,
    chapter_match_meta: chapterMatchMeta,
  };
}

function buildParagraphMappingSnapshot() {
  const chapters = {};
  for (let i = 0; i < zhChapters.length; i += 1) {
    const r = chapterConfirmedResults[i] || chapterDraftResults[i];
    if (!r || !Array.isArray(r.local_sync_map) || !r.local_sync_map.length) {
      continue;
    }
    chapters[String(i)] = {
      local_sync_map: r.local_sync_map.map((v) => Number(v)),
      zh_range: r.zh_range,
      en_range: r.en_range,
      mapped_en_chapter_index: r.mapped_en_chapter_index,
      skipped: Boolean(r.skipped),
      source: chapterConfirmedResults[i] ? "confirmed" : "draft",
    };
  }
  return {
    version: 1,
    type: "chapter_paragraph_mapping",
    zh_titles: zhChapters.map((c) => (c.title || "").trim()),
    en_titles: enChapters.map((c) => (c.title || "").trim()),
    chapter_map: chapterMap.slice(),
    current_chapter_index: currentChapterIndex,
    chapters,
  };
}

function hasAnyParagraphMapping() {
  for (let i = 0; i < zhChapters.length; i += 1) {
    const r = chapterConfirmedResults[i] || chapterDraftResults[i];
    if (r && Array.isArray(r.local_sync_map) && r.local_sync_map.length) {
      return true;
    }
  }
  return false;
}

function formatTimestampForFilename() {
  const now = new Date();
  const pad = (v) => String(v).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function normalizeTitleForKey(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function assertSnapshotTitlesMatch(snapshot) {
  const snapshotZh = Array.isArray(snapshot.zh_titles) ? snapshot.zh_titles : [];
  const snapshotEn = Array.isArray(snapshot.en_titles) ? snapshot.en_titles : [];
  const zhNow = zhChapters.map((c) => normalizeTitleForKey(c.title));
  const enNow = enChapters.map((c) => normalizeTitleForKey(c.title));
  const snapshotZhNorm = snapshotZh.map((v) => normalizeTitleForKey(v));
  const snapshotEnNorm = snapshotEn.map((v) => normalizeTitleForKey(v));
  if (snapshotZhNorm.length !== zhNow.length || snapshotEnNorm.length !== enNow.length) {
    throw new Error("文件与当前书籍章节数量不一致。");
  }
  if (!snapshotZhNorm.every((v, idx) => v === zhNow[idx]) || !snapshotEnNorm.every((v, idx) => v === enNow[idx])) {
    throw new Error("文件与当前书籍章节标题不一致。");
  }
}

function downloadJsonFile(filename, obj) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadProgressSnapshot() {
  downloadJsonFile(`alignment_progress_${formatTimestampForFilename()}.json`, buildProgressSnapshot());
}

function downloadChapterMappingSnapshot() {
  downloadJsonFile(`chapter_mapping_${formatTimestampForFilename()}.json`, buildChapterMappingSnapshot());
}

function downloadParagraphMappingSnapshot() {
  downloadJsonFile(`chapter_paragraph_mapping_${formatTimestampForFilename()}.json`, buildParagraphMappingSnapshot());
}

function restoreProgressSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.chapter_map) || typeof snapshot.confirmed_results !== "object") {
    throw new Error("进度文件格式不正确。");
  }
  assertSnapshotTitlesMatch(snapshot);
  chapterMap = snapshot.chapter_map.map((v) => Number(v) || 0);
  chapterConfirmedResults = snapshot.confirmed_results || {};
  chapterDraftResults = {};
  chapterFlowStarted = true;
  currentChapterIndex = Math.max(0, Math.min(zhChapters.length - 1, Number(snapshot.current_chapter_index) || 0));
  chapterMappingApproved = true;
  const restoredCurrent = chapterConfirmedResults[currentChapterIndex];
  paragraphReviewItems = restoredCurrent && Array.isArray(restoredCurrent.review_items) ? restoredCurrent.review_items : [];
  mergeConfirmedSyncMap();
  renderChapterMappingEditor();
  renderParagraphReviewItems();
  updateChapterProgress();
  updateChapterActionButtons();
}

function restoreChapterMappingSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.chapter_map)) {
    throw new Error("章节映射文件格式不正确。");
  }
  assertSnapshotTitlesMatch(snapshot);

  chapterMap = snapshot.chapter_map.map((v, idx) => {
    const raw = Number(v);
    const fallback = Math.min(enChapters.length - 1, idx);
    if (!Number.isFinite(raw)) {
      return fallback;
    }
    return Math.max(0, Math.min(enChapters.length - 1, raw));
  });
  if (!isNonDecreasing(chapterMap)) {
    throw new Error("导入的章节映射顺序逆序，请检查后重试。");
  }

  chapterMatchMeta = Array.isArray(snapshot.chapter_match_meta)
    ? snapshot.chapter_match_meta.map((meta) => (
      meta && typeof meta === "object"
        ? {
          confidence: Number.isFinite(Number(meta.confidence)) ? Number(meta.confidence) : null,
          reason: typeof meta.reason === "string" ? meta.reason : "",
          source: typeof meta.source === "string" ? meta.source : "imported",
        }
        : { confidence: null, reason: "imported", source: "imported" }
    ))
    : new Array(zhChapters.length).fill(0).map(() => ({ confidence: null, reason: "imported", source: "imported" }));

  chapterMappingReady = true;
  chapterMappingApproved = false;
  chapterFlowStarted = false;
  currentChapterIndex = 0;
  chapterDraftResults = {};
  chapterConfirmedResults = {};
  paragraphReviewItems = [];
  syncMap = new Array(zhParagraphs.length).fill(0);
  renderParagraphReviewItems();
  renderChapterMappingEditor();
  updateChapterProgress();
  updateChapterActionButtons();
}

function restoreParagraphMappingSnapshot(snapshot) {
  if (!snapshot || snapshot.type !== "chapter_paragraph_mapping" || typeof snapshot.chapters !== "object") {
    throw new Error("章节段落映射文件格式不正确。");
  }
  if (!Object.keys(snapshot.chapters).length) {
    throw new Error("文件中没有章节段落数据。");
  }
  assertSnapshotTitlesMatch(snapshot);

  if (Array.isArray(snapshot.chapter_map)) {
    chapterMap = snapshot.chapter_map.map((v, idx) => {
      const raw = Number(v);
      const fallback = Math.min(enChapters.length - 1, idx);
      if (!Number.isFinite(raw)) {
        return fallback;
      }
      return Math.max(0, Math.min(enChapters.length - 1, raw));
    });
    if (!isNonDecreasing(chapterMap)) {
      throw new Error("章节目录映射顺序逆序。");
    }
  }

  chapterDraftResults = {};
  chapterConfirmedResults = {};
  Object.entries(snapshot.chapters).forEach(([key, entry]) => {
    const i = Number(key);
    if (!Number.isFinite(i) || i < 0 || i >= zhChapters.length) {
      return;
    }
    const lsm = entry.local_sync_map;
    if (!Array.isArray(lsm) || !lsm.length) {
      return;
    }
    const mappedEn = Number(entry.mapped_en_chapter_index);
    const enI = Number.isFinite(mappedEn)
      ? Math.max(0, Math.min(enChapters.length - 1, mappedEn))
      : chapterMap[i];
    const zhCh = zhChapters[i];
    const enCh = enChapters[enI] || { start: 0, end: 0 };
    const obj = {
      chapter_index: i,
      mapped_en_chapter_index: enI,
      local_sync_map: lsm.map((x) => Number(x)),
      zh_range: entry.zh_range && typeof entry.zh_range === "object"
        ? entry.zh_range
        : { start: zhCh.start, end: zhCh.end },
      en_range: entry.en_range && typeof entry.en_range === "object"
        ? entry.en_range
        : { start: enCh.start, end: enCh.end },
      blocks: [],
      review_items: [],
      skipped: Boolean(entry.skipped),
    };
    if (entry.source === "draft") {
      chapterDraftResults[i] = obj;
    } else {
      chapterConfirmedResults[i] = obj;
    }
  });
  chapterMappingReady = true;
  chapterMappingApproved = true;
  chapterFlowStarted = true;
  currentChapterIndex = Math.max(0, Math.min(zhChapters.length - 1, Number(snapshot.current_chapter_index) || 0));
  chapterMatchMeta = new Array(zhChapters.length).fill(null).map(() => ({
    confidence: null,
    reason: "imported_paragraph_mapping",
    source: "imported",
  }));
  paragraphReviewItems = [];
  mergeConfirmedSyncMap();
  renderParagraphReviewItems();
  renderChapterMappingEditor();
  updateChapterProgress();
  updateChapterActionButtons();
}

async function suggestChapterMappingByAI() {
  if (!zhChapters.length || !enChapters.length) {
    chapterMap = [];
    return;
  }
  const zhTitles = zhChapters.map((c, i) => {
    const t = (c.title || "").replace(/\s+/g, " ").trim();
    return t || `Chapter ${i + 1}`;
  });
  const enTitles = enChapters.map((c, i) => {
    const t = (c.title || "").replace(/\s+/g, " ").trim();
    return t || `Chapter ${i + 1}`;
  });
  setStatus("正在调用章节匹配服务...");
  const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
  const response = await fetch("/api/chapter-match", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ zh_titles: zhTitles, en_titles: enTitles }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error || "章节匹配服务请求失败。");
  }
  const pairs = payload?.pairs;
  if (!Array.isArray(pairs) || !pairs.length) {
    throw new Error("章节匹配服务返回为空。");
  }

  chapterMap = new Array(zhChapters.length).fill(0);
  chapterMatchMeta = new Array(zhChapters.length).fill(null);
  let lastEn = 0;
  for (let i = 0; i < chapterMap.length; i += 1) {
    const pair = pairs.find((p) => Number(p.zh_index) === i);
    let enIdx = pair ? Number(pair.en_index) : lastEn;
    if (!Number.isFinite(enIdx)) {
      enIdx = lastEn;
    }
    enIdx = Math.max(lastEn, Math.min(enChapters.length - 1, enIdx));
    chapterMap[i] = enIdx;
    chapterMatchMeta[i] = {
      confidence: Number.isFinite(Number(pair?.confidence)) ? Number(pair.confidence) : null,
      reason: typeof pair?.reason === "string" ? pair.reason : "",
      source: pair ? "api" : "filled",
    };
    lastEn = enIdx;
  }
  chapterMappingReady = true;
  chapterMappingApproved = false;
  const elapsed = Math.round(
    (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0,
  );
  logActivity(`POST /api/chapter-match 结束 · ${elapsed} ms · pairs=${chapterMap.length}`);
}

function isNonDecreasing(arr) {
  for (let i = 1; i < arr.length; i += 1) {
    if (arr[i] < arr[i - 1]) {
      return false;
    }
  }
  return true;
}

function renderChapterMappingEditor() {
  if (!zhChapters.length || !enChapters.length) {
    chapterPanel.classList.add("hidden");
    return;
  }
  chapterPanel.classList.remove("hidden");
  chapterList.innerHTML = "";

  zhChapters.forEach((chapter, idx) => {
    const row = document.createElement("div");
    row.className = "chapter-row";
    if (idx === currentChapterIndex && chapterFlowStarted) {
      row.classList.add("current");
    }
    if (chapterConfirmedResults[idx]) {
      row.classList.add("confirmed");
      if (chapterConfirmedResults[idx]?.skipped) {
        row.classList.add("skipped");
      }
    }

    const left = document.createElement("div");
    left.className = "chapter-title";
    left.title = chapter.title;
    left.textContent = `中${idx + 1}. ${chapter.title}`;

    const arrow = document.createElement("div");
    arrow.className = "chapter-arrow";
    arrow.textContent = "=>";

    const right = document.createElement("div");
    right.className = "chapter-right";

    const select = document.createElement("select");
    select.dataset.index = String(idx);
    enChapters.forEach((enChapter, enIdx) => {
      const option = document.createElement("option");
      option.value = String(enIdx);
      option.textContent = `英${enIdx + 1}. ${enChapter.title}`;
      select.appendChild(option);
    });
    select.value = String(Math.max(0, Math.min(enChapters.length - 1, chapterMap[idx] ?? idx)));
    select.addEventListener("change", (e) => {
      const chapterIndex = Number(e.target.dataset.index);
      chapterMap[chapterIndex] = Number(e.target.value);
      chapterMatchMeta[chapterIndex] = {
        confidence: null,
        reason: "manual_override",
        source: "manual",
      };
      chapterMappingReady = true;
      chapterMappingApproved = false;
      if (isNonDecreasing(chapterMap)) {
        setStatus("章节对应已更新，请点击“确认章节对应并开始段落对齐”。");
      } else {
        setStatus("章节对应必须保持顺序不逆序，请调整后再确认。", true);
      }
      renderChapterMappingEditor();
      updateChapterProgress();
      updateChapterActionButtons();
    });

    const meta = chapterMatchMeta[idx] || { confidence: null, reason: "", source: "unknown" };
    const metaEl = document.createElement("div");
    metaEl.className = "chapter-meta";
    const confText = Number.isFinite(meta.confidence) ? `conf=${meta.confidence.toFixed(3)}` : "conf=n/a";
    const sourceText = meta.source || "unknown";
    const reasonText = (meta.reason || "").trim() || "no_reason";
    metaEl.textContent = `${confText} | source=${sourceText} | reason=${reasonText}`;
    if (Number.isFinite(meta.confidence) && meta.confidence < 0.45) {
      metaEl.classList.add("low-confidence");
    }

    right.appendChild(select);
    right.appendChild(metaEl);

    row.appendChild(left);
    row.appendChild(arrow);
    row.appendChild(right);
    chapterList.appendChild(row);
  });
  renderParagraphReviewItems();
}

function getAnchorSummaryText(text) {
  const clean = (text || "").replace(/\s+/g, " ").trim();
  if (clean.length <= 22) {
    return clean;
  }
  return `${clean.slice(0, 22)}...`;
}

function updateAnchorHint() {
  if (!anchorModeInput.checked) {
    anchorHint.textContent =
      "锚点模式：开启后可在左右段落上成对标记，便于肉眼对照；不参与 LLM 对齐计算。";
    return;
  }
  if (pendingZhAnchor === null) {
    anchorHint.textContent = "锚点模式已开启：请先点击左侧一个中文段落。";
    return;
  }
  anchorHint.textContent = `已选择中文第 ${pendingZhAnchor + 1} 段，请点击右侧英文段落完成标记。`;
}

function renderAnchorList() {
  anchorList.innerHTML = "";
  anchors.forEach((pair, idx) => {
    const item = document.createElement("li");
    item.className = "anchor-item";

    const text = document.createElement("span");
    const zhText = getAnchorSummaryText(zhParagraphs[pair.zh]);
    const enText = getAnchorSummaryText(enParagraphs[pair.en]);
    text.textContent = `#${idx + 1} 中${pair.zh + 1} -> 英${pair.en + 1} | ${zhText} / ${enText}`;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "删除";
    removeBtn.addEventListener("click", () => {
      anchors = anchors.filter((_, i) => i !== idx);
      renderAnchorList();
      updateAnchorVisuals();
      setStatus("已删除锚点。需要时可点击「重新整本对齐」刷新 LLM 映射。");
    });

    item.appendChild(text);
    item.appendChild(removeBtn);
    anchorList.appendChild(item);
  });
  refreshStatusSummary();
}

function updateAnchorVisuals() {
  zhElements.forEach((el) => {
    el.classList.remove("anchor");
    el.classList.remove("pending-anchor");
  });
  enElements.forEach((el) => el.classList.remove("anchor"));

  anchors.forEach((pair) => {
    const zhLocal = renderedZhGlobalIndexes.indexOf(pair.zh);
    const enLocal = renderedEnGlobalIndexes.indexOf(pair.en);
    if (zhLocal >= 0) {
      zhElements[zhLocal]?.classList.add("anchor");
    }
    if (enLocal >= 0) {
      enElements[enLocal]?.classList.add("anchor");
    }
  });
  if (pendingZhAnchor !== null) {
    const pendingLocal = renderedZhGlobalIndexes.indexOf(pendingZhAnchor);
    if (pendingLocal >= 0) {
      zhElements[pendingLocal]?.classList.add("pending-anchor");
    }
  }
  updateAnchorHint();
}

function isMonotonicAnchorSet(pairs) {
  for (let i = 1; i < pairs.length; i += 1) {
    if (pairs[i].zh <= pairs[i - 1].zh || pairs[i].en <= pairs[i - 1].en) {
      return false;
    }
  }
  return true;
}

function addAnchor(zhIndex, enIndex) {
  const candidate = [...anchors.filter((p) => p.zh !== zhIndex && p.en !== enIndex), { zh: zhIndex, en: enIndex }]
    .sort((a, b) => a.zh - b.zh);
  if (!isMonotonicAnchorSet(candidate)) {
    setStatus("该锚点会破坏顺序单调性，请换一个更对应的英文段落。", true);
    return false;
  }
  anchors = candidate;
  renderAnchorList();
  updateAnchorVisuals();
  setStatus(`已添加锚点标记：中${zhIndex + 1} ↔ 英${enIndex + 1}（仅视觉标记；对齐请用「重新整本对齐」）。`);
  return true;
}

function handleParagraphClick(side, index, isEmpty) {
  if (!anchorModeInput.checked || isEmpty) {
    return;
  }
  if (side === "zh") {
    pendingZhAnchor = index;
    updateAnchorVisuals();
    return;
  }
  if (pendingZhAnchor === null) {
    setStatus("请先点击左侧中文段落，再点击右侧英文段落。", true);
    return;
  }
  addAnchor(pendingZhAnchor, index);
  pendingZhAnchor = null;
  updateAnchorVisuals();
}

function clearPairHover() {
  zhElements.forEach((el) => el.classList.remove("pair-hover"));
  enElements.forEach((el) => el.classList.remove("pair-hover"));
}

function cancelPairHoverClear() {
  if (pairHoverClearTimer !== null) {
    window.clearTimeout(pairHoverClearTimer);
    pairHoverClearTimer = null;
  }
}

function schedulePairHoverClear() {
  cancelPairHoverClear();
  pairHoverClearTimer = window.setTimeout(() => {
    pairHoverClearTimer = null;
    clearPairHover();
  }, 120);
}

function scrollPeerIntoView(el) {
  if (!el) {
    return;
  }
  try {
    el.scrollIntoView({ block: "nearest", behavior: "smooth", inline: "nearest" });
  } catch (_) {
    el.scrollIntoView(true);
  }
}

function applyPairHoverFromZhLocal(zhLocalIdx) {
  cancelPairHoverClear();
  clearPairHover();
  if (zhLocalIdx < 0 || zhLocalIdx >= renderedSyncMap.length) {
    return;
  }
  const enLocal = Number(renderedSyncMap[zhLocalIdx]);
  if (!Number.isFinite(enLocal)) {
    return;
  }
  zhElements[zhLocalIdx]?.classList.add("pair-hover");
  const enEl = enElements[zhLocalIdx];
  enEl?.classList.add("pair-hover");
  scrollPeerIntoView(enEl);
}

function applyPairHoverFromEnLocal(enLocalIdx) {
  cancelPairHoverClear();
  clearPairHover();
  if (enLocalIdx < 0 || !Number.isFinite(enLocalIdx)) {
    return;
  }
  const zhLocals = [];
  for (let zi = 0; zi < renderedSyncMap.length; zi += 1) {
    if (Number(renderedSyncMap[zi]) === enLocalIdx) {
      zhLocals.push(zi);
    }
  }
  const enRows = [];
  const maxLen = zhElements.length;
  for (let r = 0; r < maxLen; r += 1) {
    if (displayedEnLocalForRow(r, readerScope, renderedSyncMap) === enLocalIdx) {
      enRows.push(r);
    }
  }
  if (!zhLocals.length && !enRows.length) {
    return;
  }
  zhLocals.forEach((zi) => zhElements[zi]?.classList.add("pair-hover"));
  enRows.forEach((r) => enElements[r]?.classList.add("pair-hover"));
  const zhEl = zhElements[zhLocals[0]];
  scrollPeerIntoView(zhEl || enElements[enRows[0]]);
}

function getRenderedScope(options = {}) {
  if (options.mode === "chapter") {
    return getChapterScope(options.chapterIndex ?? currentChapterIndex);
  }
  return getBookScope();
}

function chapterEnSpan(scope) {
  return Math.max(0, scope.enEnd - scope.enStart + 1);
}

function toLocalEnIndex(globalEnIndex, scope) {
  const enSpan = chapterEnSpan(scope);
  if (enSpan <= 0) {
    return 0;
  }
  const rawLocal = Number(globalEnIndex) - scope.enStart;
  if (!Number.isFinite(rawLocal)) {
    return 0;
  }
  return Math.max(0, Math.min(enSpan - 1, rawLocal));
}

/**
 * 将服务端返回的 sync_map 拉齐到中文段数。
 * 已有下标：无效或倒退时按单调修正（与后端 flatten 一致）。
 * 尾部缺失：在「最后一个有效英文下标」与 enGlobalMax 之间线性铺开，避免整段复制同一英文段。
 */
function normalizeSyncMapLength(raw, zhLen, enGlobalMax) {
  if (!zhLen) {
    return [];
  }
  const src = Array.isArray(raw) ? raw : [];
  const cap = Number.isFinite(Number(enGlobalMax)) ? Math.max(0, Math.floor(Number(enGlobalMax))) : null;
  const clamp = (x) => {
    if (cap === null) {
      return Math.max(0, x);
    }
    return Math.max(0, Math.min(cap, x));
  };
  const out = [];
  let last = 0;
  let tailAnchor = null;

  for (let i = 0; i < zhLen; i += 1) {
    if (i < src.length) {
      let v = Number(src[i]);
      if (!Number.isFinite(v)) {
        v = last;
      } else if (v < last) {
        v = last;
      }
      v = clamp(v);
      out.push(v);
      last = v;
    } else {
      if (tailAnchor === null) {
        tailAnchor = last;
      }
      const tailCount = zhLen - src.length;
      const pos = i - src.length;
      const endTarget = cap !== null ? Math.max(tailAnchor, cap) : tailAnchor;
      const t = tailCount <= 1 ? 1 : pos / (tailCount - 1);
      let v = Math.round(tailAnchor + t * (endTarget - tailAnchor));
      if (v < last) {
        v = last;
      }
      v = clamp(v);
      out.push(v);
      last = v;
    }
  }
  return out;
}

/**
 * 段落对齐（LLM）之前的占位映射：只按「本视图内中英段数」线性铺开本地英文下标，
 * 不读正文长度。避免按字符比例时一大段英文吃掉多段中文预览，造成同一段英文重复多行。
 */
function approximateIndexMapByCount(zhCount, enCount) {
  if (zhCount <= 0) {
    return [];
  }
  if (enCount <= 0) {
    return new Array(zhCount).fill(0);
  }
  if (zhCount === 1) {
    return [0];
  }
  const maxLocal = enCount - 1;
  return Array.from({ length: zhCount }, (_, i) => Math.round((i / (zhCount - 1)) * maxLocal));
}

/**
 * 将章内 local_sync_map（全局英文段下标）规范为与当前章中文行数一致；缺项、越界或尾部过短时
 * 做单调补齐，避免大量行落在 scope.enStart（常见为整章第一段英文反复出现）。
 */
function chapterLocalSyncGlobalsForRender(lsm, zhLength, localSyncLooksLikeOffsets, scope) {
  const enSpan = chapterEnSpan(scope);
  if (!Array.isArray(lsm) || zhLength <= 0 || enSpan <= 0) {
    return null;
  }
  const enEndGlobal = scope.enEnd;
  const out = [];
  let lastG = scope.enStart;

  const head = Math.min(lsm.length, zhLength);
  for (let i = 0; i < head; i += 1) {
    const cell = lsm[i];
    const raw = Number(cell);
    let g;
    if (cell === undefined || cell === null || !Number.isFinite(raw)) {
      g = lastG;
    } else {
      g = localSyncLooksLikeOffsets ? scope.enStart + raw : raw;
    }
    g = Math.max(scope.enStart, Math.min(enEndGlobal, g));
    if (g < lastG) {
      g = lastG;
    }
    out.push(g);
    lastG = g;
  }

  if (out.length < zhLength) {
    const tailLen = zhLength - out.length;
    const anchorG = lastG;
    for (let j = 0; j < tailLen; j += 1) {
      const t = tailLen <= 1 ? 1 : j / (tailLen - 1);
      let g = Math.round(anchorG + t * (enEndGlobal - anchorG));
      g = Math.max(lastG, Math.min(enEndGlobal, g));
      out.push(g);
      lastG = g;
    }
  }

  return out;
}

function ensureSyncMapCoversZhParagraphs() {
  const n = zhParagraphs.length;
  if (!n || syncMap.length >= n) {
    return;
  }
  const old = syncMap;
  syncMap = new Array(n).fill(0);
  for (let i = 0; i < old.length; i += 1) {
    syncMap[i] = old[i];
  }
}

function buildRenderedSyncMap(scope) {
  const zhLength = Math.max(0, scope.zhEnd - scope.zhStart + 1);
  const enSpan = chapterEnSpan(scope);
  if (!zhLength) {
    return [];
  }

  const chapterResult = scope.mode === "chapter"
    ? (chapterConfirmedResults[scope.chapterIndex] || chapterDraftResults[scope.chapterIndex] || null)
    : null;
  let localSyncLooksLikeOffsets = false;
  const lsm = chapterResult && Array.isArray(chapterResult.local_sync_map)
    ? chapterResult.local_sync_map
    : null;
  if (lsm && lsm.length > 0 && scope.enStart > 0) {
    const nums = lsm.map((v) => Number(v)).filter(Number.isFinite);
    const rawMax = nums.length ? Math.max(...nums) : -Infinity;
    if (rawMax !== -Infinity && rawMax < scope.enStart) {
      localSyncLooksLikeOffsets = true;
    }
  }

  let chapterApproxLocals = null;
  if (scope.mode === "chapter" && !lsm && enSpan > 0) {
    chapterApproxLocals = approximateIndexMapByCount(zhLength, enSpan);
  }

  let bookApproxGlobals = null;
  if (scope.mode === "book" && !lsm && enSpan > 0 && zhLength > 0) {
    let allZero = true;
    for (let localZhIdx = 0; localZhIdx < zhLength; localZhIdx += 1) {
      const zhGlobalIdx = scope.zhStart + localZhIdx;
      const cell = zhGlobalIdx < syncMap.length ? syncMap[zhGlobalIdx] : undefined;
      const v = Number(cell);
      if (Number.isFinite(v) && v !== 0) {
        allZero = false;
        break;
      }
    }
    if (allZero) {
      const locals = approximateIndexMapByCount(zhLength, enSpan);
      bookApproxGlobals = locals.map((local) => scope.enStart + local);
    }
  }

  const chapterSyncGlobals = lsm
    ? chapterLocalSyncGlobalsForRender(lsm, zhLength, localSyncLooksLikeOffsets, scope)
    : null;

  const map = [];

  for (let localZhIdx = 0; localZhIdx < zhLength; localZhIdx += 1) {
    const zhGlobalIdx = scope.zhStart + localZhIdx;
    let mappedGlobal = null;
    if (chapterSyncGlobals) {
      mappedGlobal = chapterSyncGlobals[localZhIdx];
    } else if (chapterApproxLocals) {
      mappedGlobal = scope.enStart + chapterApproxLocals[localZhIdx];
    } else if (bookApproxGlobals) {
      mappedGlobal = bookApproxGlobals[localZhIdx];
    } else if (zhGlobalIdx < syncMap.length && Number.isFinite(Number(syncMap[zhGlobalIdx]))) {
      mappedGlobal = Number(syncMap[zhGlobalIdx]);
    } else {
      mappedGlobal = scope.enStart;
    }

    let localEnIdx = toLocalEnIndex(mappedGlobal, scope);
    if (enSpan > 0) {
      localEnIdx = Math.max(0, Math.min(enSpan - 1, localEnIdx));
    } else {
      localEnIdx = 0;
    }
    map.push(localEnIdx);
  }
  return map;
}

function displayedEnLocalForRow(rowIdx, scope = readerScope, map = renderedSyncMap) {
  const zhLength = Math.max(0, scope.zhEnd - scope.zhStart + 1);
  const enSpan = chapterEnSpan(scope);
  if (rowIdx < zhLength) {
    if (enSpan <= 0) {
      return -1;
    }
    const v = Number(map[rowIdx]);
    return Math.max(0, Math.min(enSpan - 1, Number.isFinite(v) ? v : 0));
  }
  if (rowIdx < enSpan) {
    return rowIdx;
  }
  return -1;
}

function enRowIndexForLocalEn(enLocal, scope = readerScope, map = renderedSyncMap) {
  const zhLength = Math.max(0, scope.zhEnd - scope.zhStart + 1);
  const enSpan = chapterEnSpan(scope);
  const maxLen = Math.max(zhLength, enSpan);
  if (enLocal < 0 || !Number.isFinite(enLocal)) {
    return 0;
  }
  for (let r = 0; r < maxLen; r += 1) {
    if (displayedEnLocalForRow(r, scope, map) === enLocal) {
      return r;
    }
  }
  return Math.min(Math.max(0, enLocal), Math.max(0, maxLen - 1));
}

async function renderReader(options = {}) {
  ensureSyncMapCoversZhParagraphs();
  const scope = getRenderedScope(options);
  readerScope = scope;
  zhScroll.innerHTML = "";
  enScroll.innerHTML = "";
  zhElements = [];
  enElements = [];
  renderedZhGlobalIndexes = [];
  renderedEnGlobalIndexes = [];
  cancelPairHoverClear();
  clearPairHover();
  zhOffsets = [];
  activeIndex = -1;
  activeZhIndex = -1;
  activeEnIndex = -1;
  const zhLength = Math.max(0, scope.zhEnd - scope.zhStart + 1);
  const enSpan = chapterEnSpan(scope);
  const maxLen = Math.max(zhLength, enSpan);
  const chunkSize = 300;

  if (!maxLen) {
    zhScroll.innerHTML = "<p class=\"para\">当前章节暂无中文段落。</p>";
    enScroll.innerHTML = "<p class=\"para\">Current chapter has no English paragraphs.</p>";
    renderedSyncMap = [];
    return;
  }

  renderedSyncMap = buildRenderedSyncMap(scope);

  for (let start = 0; start < maxLen; start += chunkSize) {
    const end = Math.min(maxLen, start + chunkSize);
    const zhFrag = document.createDocumentFragment();
    const enFrag = document.createDocumentFragment();

    for (let i = start; i < end; i += 1) {
      const hasZh = i < zhLength;
      const zhGlobalIndex = hasZh ? scope.zhStart + i : -1;
      const zh = hasZh ? (zhParagraphs[zhGlobalIndex] || "") : "";

      let enGlobalIndex = -1;
      let en = "";
      if (hasZh) {
        if (enSpan <= 0) {
          enGlobalIndex = -1;
          en = "";
        } else {
          const enLocal = Number(renderedSyncMap[i] ?? 0);
          const safeLocal = Math.max(0, Math.min(enSpan - 1, Number.isFinite(enLocal) ? enLocal : 0));
          enGlobalIndex = scope.enStart + safeLocal;
          en = enParagraphs[enGlobalIndex] ?? "";
        }
      } else if (i < enSpan) {
        enGlobalIndex = scope.enStart + i;
        en = enParagraphs[enGlobalIndex] || "";
      }

      const zhNode = createParagraphElement(zh || "", i, !zh);
      const enNode = createParagraphElement(en || "", i, !en);
      const enLocalForHover = displayedEnLocalForRow(i, scope, renderedSyncMap);
      if (hasZh) {
        zhNode.addEventListener("mouseenter", () => applyPairHoverFromZhLocal(i));
        zhNode.addEventListener("mouseleave", () => schedulePairHoverClear());
      }
      if (enLocalForHover >= 0) {
        enNode.addEventListener("mouseenter", () => applyPairHoverFromEnLocal(enLocalForHover));
        enNode.addEventListener("mouseleave", () => schedulePairHoverClear());
      }
      zhNode.addEventListener("click", () => handleParagraphClick("zh", zhGlobalIndex, !zh));
      enNode.addEventListener("click", () => handleParagraphClick("en", enGlobalIndex, !en));
      zhFrag.appendChild(zhNode);
      enFrag.appendChild(enNode);
      zhElements.push(zhNode);
      enElements.push(enNode);
      renderedZhGlobalIndexes.push(zhGlobalIndex);
      renderedEnGlobalIndexes.push(enGlobalIndex);
    }

    zhScroll.appendChild(zhFrag);
    enScroll.appendChild(enFrag);

    if (maxLen > 500) {
      setStatus(`正在渲染阅读视图：${end}/${maxLen}`, false, { skipLog: true });
    }
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
  }
  zhOffsets = zhElements.map((el) => el.offsetTop);
  updateAnchorVisuals();
  refreshStatusSummary();
}

function findFloorIndex(sorted, value) {
  let left = 0;
  let right = sorted.length - 1;
  let answer = 0;
  while (left <= right) {
    const mid = (left + right) >> 1;
    if (sorted[mid] <= value) {
      answer = mid;
      left = mid + 1;
    } else {
      right = mid - 1;
    }
  }
  return answer;
}

function getMostVisibleZhIndex() {
  if (!zhElements.length || !zhOffsets.length) {
    return 0;
  }
  const probe = zhScroll.scrollTop + zhScroll.clientHeight * 0.25;
  let idx = findFloorIndex(zhOffsets, probe);
  idx = Math.max(0, Math.min(zhElements.length - 1, idx));
  while (idx < zhElements.length - 1 && zhElements[idx].classList.contains("empty")) {
    idx += 1;
  }
  return idx;
}

function setActive(index, map) {
  if (index === activeIndex) {
    return;
  }
  activeIndex = index;
  if (activeZhIndex >= 0) {
    zhElements[activeZhIndex]?.classList.remove("active");
  }
  if (activeEnIndex >= 0) {
    enElements[activeEnIndex]?.classList.remove("active");
  }
  const enLocal = map[index] ?? 0;
  const enRow = enRowIndexForLocalEn(enLocal, readerScope, map);
  zhElements[index]?.classList.add("active");
  enElements[enRow]?.classList.add("active");
  activeZhIndex = index;
  activeEnIndex = enRow;
}

function syncEnglishToChinese(map) {
  if (!map.length || !enElements.length) {
    return;
  }
  const zhIndex = getMostVisibleZhIndex();
  const enLocal = map[zhIndex] ?? 0;
  const enRow = enRowIndexForLocalEn(enLocal, readerScope, map);
  const targetEl = enElements[enRow];
  if (!targetEl) {
    return;
  }

  setActive(zhIndex, map);
  isSyncing = true;
  enScroll.scrollTo({ top: Math.max(0, targetEl.offsetTop - enScroll.clientHeight * 0.2), behavior: "smooth" });
  window.setTimeout(() => {
    isSyncing = false;
  }, 180);
}

function requestSync() {
  if (syncQueued) {
    return;
  }
  syncQueued = true;
  window.requestAnimationFrame(() => {
    syncQueued = false;
    syncEnglishToChinese(renderedSyncMap);
  });
}

function loadDefaultExampleIfEmpty() {
  if (zhInput.value.trim() || enInput.value.trim()) {
    return;
  }
  zhInput.value = `第一段：这是一个用于演示的中文段落。它说明用户在阅读时以中文为主。

第二段：当用户对翻译产生疑问时，可以快速查看右侧英文内容，不需要跳转或搜索。

第三段：段落对齐由后端 LLM 按章内块映射完成，两侧分段不必一致。`;

  enInput.value = `Paragraph 1: This is a demo Chinese-to-English reading pair. The user mainly reads Chinese.

Paragraph 2: When the translation feels unclear, the user glances at the English text on the right without searching.

Paragraph 3: Alignment uses server-side LLM block mapping; paragraph splits need not match.`;
}

async function recomputeMapAndRender() {
  if (!zhParagraphs.length) {
    throw new Error("请先加载文本后再对齐。");
  }
  if (!enParagraphs.length) {
    syncMap = new Array(zhParagraphs.length).fill(0);
    paragraphReviewItems = [];
    renderParagraphReviewItems();
    await renderReader({ mode: "book" });
    syncEnglishToChinese(renderedSyncMap);
    return;
  }

  if (chapterMappingReady && !chapterMappingApproved) {
    throw new Error("请先确认章节对应，再开始段落对齐。");
  }
  const aligned = await alignParagraphsViaServer();
  syncMap = aligned.syncMap;
  paragraphReviewItems = aligned.reviewItems;
  renderParagraphReviewItems();

  await renderReader({ mode: "book" });
  syncEnglishToChinese(renderedSyncMap);
  const mode = chapterMappingApproved ? "章节确认后整本 LLM 对齐" : "整本 LLM 对齐";
  setStatus(`对齐完成：中文 ${zhParagraphs.length} 段，英文 ${enParagraphs.length} 段（${mode}）。`);
}

function resetAlignmentState() {
  anchors = [];
  pendingZhAnchor = null;
  zhChapters = [];
  enChapters = [];
  chapterMap = [];
  chapterMatchMeta = [];
  paragraphReviewItems = [];
  chapterMappingReady = false;
  chapterMappingApproved = false;
  chapterFlowStarted = false;
  currentChapterIndex = 0;
  chapterDraftResults = {};
  chapterConfirmedResults = {};
  renderedZhGlobalIndexes = [];
  renderedEnGlobalIndexes = [];
  renderedSyncMap = [];
  readerScope = { mode: "book", chapterIndex: -1, zhStart: 0, zhEnd: -1, enStart: 0, enEnd: -1 };
  cancelPairHoverClear();
  chapterPanel.classList.add("hidden");
  chapterList.innerHTML = "";
  paragraphReviewList.innerHTML = "";
  renderAnchorList();
  updateAnchorHint();
  updateChapterProgress();
  updateChapterActionButtons();
}

updateAnchorHint();
updateChapterProgress();
updateChapterActionButtons();

if (clearLogBtn) {
  clearLogBtn.addEventListener("click", () => {
    if (activityLogEl) {
      activityLogEl.innerHTML = "";
    }
    logActivity("已清空前端日志。");
  });
}

loadBtn.addEventListener("click", async () => {
  loadBtn.disabled = true;
  reapplyBtn.disabled = true;
  applyChaptersBtn.disabled = true;
  suggestChaptersBtn.disabled = true;
  setStatus("准备加载内容...");
  try {
    loadDefaultExampleIfEmpty();
    resetAlignmentState();

    const zhFile = zhEpubInput.files?.[0];
    const enFile = enEpubInput.files?.[0];
    if (zhFile) {
      const zhDoc = await extractEpubDocument(zhFile, "中文");
      zhParagraphs = zhDoc.paragraphs;
      zhChapters = zhDoc.chapters;
    } else {
      zhParagraphs = parseParagraphs(zhInput.value);
      zhChapters = zhParagraphs.length ? [{ title: "全文", start: 0, end: zhParagraphs.length - 1 }] : [];
    }
    if (enFile) {
      const enDoc = await extractEpubDocument(enFile, "英文");
      enParagraphs = enDoc.paragraphs;
      enChapters = enDoc.chapters;
    } else {
      enParagraphs = parseParagraphs(enInput.value);
      enChapters = enParagraphs.length ? [{ title: "Full Text", start: 0, end: enParagraphs.length - 1 }] : [];
    }

    if (!zhParagraphs.length) {
      zhScroll.innerHTML = "<p class=\"para\">请先输入中文文本或选择中文 EPUB。</p>";
      enScroll.innerHTML = "<p class=\"para\">Please input English text or choose an English EPUB.</p>";
      throw new Error("未检测到可阅读的中文内容。");
    }

    const shouldUseChapterFlow = zhChapters.length > 1 && enChapters.length > 1;
    if (shouldUseChapterFlow) {
      chapterMap = new Array(zhChapters.length).fill(0).map((_, i) => Math.min(enChapters.length - 1, i));
      chapterMatchMeta = new Array(zhChapters.length).fill(0).map(() => ({
        confidence: null,
        reason: "manual_or_import",
        source: "manual",
      }));
      chapterMappingReady = false;
      chapterMappingApproved = false;
      chapterFlowStarted = false;
      currentChapterIndex = 0;
      renderChapterMappingEditor();
      updateChapterProgress();
      updateChapterActionButtons();
      setStatus("已进入章节模式：可导入章节映射，或点击“重新生成章节建议”（会调用 AI）。");
    } else {
      if (zhChapters.length) {
        chapterMap = zhChapters.map((_, i) => Math.min(i, Math.max(0, enChapters.length - 1)));
      }
      await recomputeMapAndRender();
    }
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "加载失败，请重试。", true);
  } finally {
    loadBtn.disabled = false;
    reapplyBtn.disabled = false;
    updateChapterActionButtons();
  }
});

reapplyBtn.addEventListener("click", async () => {
  if (!zhParagraphs.length) {
    setStatus("请先点击“开始对照阅读”加载文本。", true);
    return;
  }
  reapplyBtn.disabled = true;
  loadBtn.disabled = true;
  try {
    await recomputeMapAndRender();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "重算失败。", true);
  } finally {
    reapplyBtn.disabled = false;
    loadBtn.disabled = false;
  }
});

suggestChaptersBtn.addEventListener("click", async () => {
  if (!zhChapters.length || !enChapters.length) {
    setStatus("请先加载中英文内容。", true);
    return;
  }
  suggestChaptersBtn.disabled = true;
  applyChaptersBtn.disabled = true;
  loadBtn.disabled = true;
  try {
    await suggestChapterMappingByAI();
    renderChapterMappingEditor();
    updateChapterActionButtons();
    setStatus("章节建议已更新，请检查后确认。");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "章节建议生成失败。", true);
  } finally {
    suggestChaptersBtn.disabled = false;
    applyChaptersBtn.disabled = false;
    loadBtn.disabled = false;
  }
});

applyChaptersBtn.addEventListener("click", async () => {
  if (!chapterMappingReady) {
    setStatus("请先导入章节映射、手动调整章节对应，或点击“重新生成章节建议”。", true);
    return;
  }
  if (!isNonDecreasing(chapterMap)) {
    setStatus("章节对应必须保持顺序不逆序，请调整后再确认。", true);
    return;
  }
  chapterMappingApproved = true;
  chapterFlowStarted = true;
  currentChapterIndex = 0;
  chapterDraftResults = {};
  chapterConfirmedResults = {};
  paragraphReviewItems = [];
  syncMap = new Array(zhParagraphs.length).fill(0);
  await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
  syncEnglishToChinese(renderedSyncMap);
  renderChapterMappingEditor();
  updateChapterProgress();
  updateChapterActionButtons();
  setStatus("已进入逐章对齐模式。请点击“对齐当前章节”。");
});

alignCurrentChapterBtn.addEventListener("click", async () => {
  alignCurrentChapterBtn.disabled = true;
  try {
    await alignCurrentChapter();
    await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
    syncEnglishToChinese(renderedSyncMap);
    renderChapterMappingEditor();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "当前章节对齐失败。", true);
  } finally {
    updateChapterActionButtons();
  }
});

confirmCurrentChapterBtn.addEventListener("click", async () => {
  try {
    confirmCurrentChapter();
    await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
    syncEnglishToChinese(renderedSyncMap);
    renderChapterMappingEditor();
    updateChapterProgress();
    updateChapterActionButtons();
    setStatus(`已确认中${currentChapterIndex + 1}章。点击“继续下一章节”推进。`);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "确认章节失败。", true);
  }
});

skipCurrentChapterBtn.addEventListener("click", async () => {
  try {
    if (!chapterFlowStarted) {
      setStatus("请先进入逐章对齐模式。", true);
      return;
    }
    skipCurrentChapter();
    await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
    syncEnglishToChinese(renderedSyncMap);
    renderChapterMappingEditor();
    updateChapterProgress();
    updateChapterActionButtons();
    setStatus(`已跳过中${currentChapterIndex + 1}章，并按当前映射写入占位结果。`);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "跳过章节失败。", true);
  }
});

nextChapterBtn.addEventListener("click", async () => {
  try {
    if (!chapterFlowStarted) {
      setStatus("请先进入逐章对齐模式。", true);
      return;
    }
    if (!chapterConfirmedResults[currentChapterIndex]) {
      setStatus("请先确认当前章节再继续。", true);
      return;
    }
    if (currentChapterIndex >= zhChapters.length - 1) {
      setStatus("已是最后一章。");
      return;
    }
    currentChapterIndex += 1;
    const confirmed = chapterConfirmedResults[currentChapterIndex];
    paragraphReviewItems = confirmed && Array.isArray(confirmed.review_items) ? confirmed.review_items : [];
    renderParagraphReviewItems();
    await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
    syncEnglishToChinese(renderedSyncMap);
    renderChapterMappingEditor();
    updateChapterProgress();
    updateChapterActionButtons();
    if (chapterConfirmedResults[currentChapterIndex]) {
      setStatus(`已切换到中${currentChapterIndex + 1}章（该章已确认）。`);
    } else {
      setStatus(`已切换到中${currentChapterIndex + 1}章。请先点击“对齐当前章节”，再点击“确认当前章节”。`);
    }
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "进入下一章节失败。", true);
  }
});

prevChapterBtn.addEventListener("click", async () => {
  try {
    if (!chapterFlowStarted || currentChapterIndex <= 0) {
      return;
    }
    currentChapterIndex -= 1;
    const confirmed = chapterConfirmedResults[currentChapterIndex];
    paragraphReviewItems = confirmed && Array.isArray(confirmed.review_items) ? confirmed.review_items : [];
    renderParagraphReviewItems();
    await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
    syncEnglishToChinese(renderedSyncMap);
    renderChapterMappingEditor();
    updateChapterProgress();
    updateChapterActionButtons();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "切换上一章节失败。", true);
  }
});

exportProgressBtn.addEventListener("click", () => {
  if (!chapterFlowStarted) {
    setStatus("请先进入逐章对齐模式。", true);
    return;
  }
  downloadProgressSnapshot();
  setStatus(`已导出进度：当前已确认 ${getConfirmedChapterCount()}/${zhChapters.length} 章。`);
});

exportMappingBtn.addEventListener("click", () => {
  if (!zhChapters.length || !enChapters.length) {
    setStatus("请先加载中英文内容。", true);
    return;
  }
  if (!chapterMappingReady) {
    setStatus("当前还没有可导出的章节映射，请先导入、手动调整或生成建议。", true);
    return;
  }
  downloadChapterMappingSnapshot();
  setStatus("已导出章节映射。下次可先导入它，避免重复调用 AI 章节匹配。");
});

importMappingBtn.addEventListener("click", async () => {
  if (!zhChapters.length || !enChapters.length) {
    setStatus("请先加载中英文内容。", true);
    return;
  }
  const file = importMappingFile.files?.[0];
  if (!file) {
    setStatus("请先选择章节映射文件。", true);
    return;
  }
  try {
    const text = await file.text();
    const snapshot = JSON.parse(text);
    restoreChapterMappingSnapshot(snapshot);
    setStatus("章节映射已导入。现在可直接进入逐章对齐，无需先调用 AI 章节匹配。");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "导入章节映射失败。", true);
  }
});

exportParaMappingBtn.addEventListener("click", () => {
  if (!chapterFlowStarted) {
    setStatus("请先进入逐章对齐模式。", true);
    return;
  }
  if (!hasAnyParagraphMapping()) {
    setStatus("请先完成至少一章的段落对齐（或保留当前章草稿）。", true);
    return;
  }
  downloadParagraphMappingSnapshot();
  setStatus("已导出章节段落映射。");
});

importParaMappingBtn.addEventListener("click", async () => {
  if (!zhChapters.length || !enChapters.length) {
    setStatus("请先加载中英文内容。", true);
    return;
  }
  const file = importParaMappingFile.files?.[0];
  if (!file) {
    setStatus("请先选择章节段落映射文件。", true);
    return;
  }
  try {
    const text = await file.text();
    const snapshot = JSON.parse(text);
    restoreParagraphMappingSnapshot(snapshot);
    await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
    syncEnglishToChinese(renderedSyncMap);
    setStatus("已导入章节段落映射。");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "导入章节段落映射失败。", true);
  }
});

importProgressBtn.addEventListener("click", async () => {
  const file = importProgressFile.files?.[0];
  if (!file) {
    setStatus("请先选择进度文件。", true);
    return;
  }
  try {
    const text = await file.text();
    const snapshot = JSON.parse(text);
    restoreProgressSnapshot(snapshot);
    await renderReader({ mode: "chapter", chapterIndex: currentChapterIndex });
    syncEnglishToChinese(renderedSyncMap);
    setStatus("已导入进度。");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "导入进度失败。", true);
  }
});

clearAnchorsBtn.addEventListener("click", () => {
  anchors = [];
  pendingZhAnchor = null;
  renderAnchorList();
  updateAnchorVisuals();
  setStatus("已清空锚点标记。需要刷新映射时请用「重新整本对齐」。");
});

anchorModeInput.addEventListener("change", () => {
  if (!anchorModeInput.checked) {
    pendingZhAnchor = null;
  }
  updateAnchorVisuals();
});

zhScroll.onscroll = () => {
  if (!isSyncing) {
    requestSync();
  }
};
