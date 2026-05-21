const els = {
  refreshLibraryBtn: document.getElementById("refresh-library-btn"),
  libraryToggleBtn: document.getElementById("library-toggle-btn"),
  exportProjectBtn: document.getElementById("export-project-btn"),
  deleteProjectBtn: document.getElementById("delete-project-btn"),
  bookLanguage: document.getElementById("book-language"),
  bookFile: document.getElementById("book-file"),
  uploadBookBtn: document.getElementById("upload-book-btn"),
  zhBookSelect: document.getElementById("zh-book-select"),
  enBookSelect: document.getElementById("en-book-select"),
  createProjectBtn: document.getElementById("create-project-btn"),
  bookList: document.getElementById("book-list"),
  projectList: document.getElementById("project-list"),
  statusText: document.getElementById("status-text"),
  projectTitle: document.getElementById("project-title"),
  projectSummary: document.getElementById("project-summary"),
  modeReadBtn: document.getElementById("mode-read-btn"),
  modeAlignBtn: document.getElementById("mode-align-btn"),
  chapterList: document.getElementById("chapter-list"),
  prevChapterBtn: document.getElementById("prev-chapter-btn"),
  nextChapterBtn: document.getElementById("next-chapter-btn"),
  prefetchBtn: document.getElementById("prefetch-btn"),
  alignRemainingBtn: document.getElementById("align-remaining-btn"),
  jobList: document.getElementById("job-list"),
  mappingPanel: document.getElementById("mapping-panel"),
  suggestMappingBtn: document.getElementById("suggest-mapping-btn"),
  saveMappingBtn: document.getElementById("save-mapping-btn"),
  confirmMappingBtn: document.getElementById("confirm-mapping-btn"),
  mappingProgressWrap: document.getElementById("mapping-progress-wrap"),
  mappingProgressBar: document.getElementById("mapping-progress-bar"),
  mappingProgressText: document.getElementById("mapping-progress-text"),
  mappingToggleBtn: document.getElementById("mapping-toggle-btn"),
  mappingHeader: document.getElementById("mapping-header"),
  mappingCollapsedSummary: document.getElementById("mapping-collapsed-summary"),
  mappingCollapsedHint: document.getElementById("mapping-collapsed-hint"),
  mappingCollapsedMeta: document.getElementById("mapping-collapsed-meta"),
  mappingCollapsedExpandBtn: document.getElementById("mapping-collapsed-expand-btn"),
  mappingContent: document.getElementById("mapping-content"),
  mappingTable: document.getElementById("mapping-table"),
  alignPanel: document.getElementById("align-panel"),
  alignMeta: document.getElementById("align-meta"),
  alignProgressWrap: document.getElementById("align-progress-wrap"),
  alignProgressBar: document.getElementById("align-progress-bar"),
  alignProgressText: document.getElementById("align-progress-text"),
  llmPolicySelect: document.getElementById("llm-policy-select"),
  alignChapterBtn: document.getElementById("align-chapter-btn"),
  confirmChapterBtn: document.getElementById("confirm-chapter-btn"),
  skipChapterBtn: document.getElementById("skip-chapter-btn"),
  regenerateChapterBtn: document.getElementById("regenerate-chapter-btn"),
  anchorFloat: document.getElementById("anchor-float"),
  anchorFloatToggle: document.getElementById("anchor-float-toggle"),
  anchorFloatBody: document.getElementById("anchor-float-body"),
  anchorMode: document.getElementById("anchor-mode"),
  anchorHint: document.getElementById("anchor-hint"),
  createAnchorBtn: document.getElementById("create-anchor-btn"),
  resetAnchorBtn: document.getElementById("reset-anchor-btn"),
  anchorList: document.getElementById("anchor-list"),
  reportMismatchBtn: document.getElementById("report-mismatch-btn"),
  reviewList: document.getElementById("review-list"),
  readerTitle: document.getElementById("reader-title"),
  readerMeta: document.getElementById("reader-meta"),
  lookupPanel: document.getElementById("lookup-panel"),
  lookupColumn: document.querySelector(".lookup-column"),
  lookupLabel: document.getElementById("lookup-label"),
  lookupContent: document.getElementById("lookup-content"),
  lookupCloseBtn: document.getElementById("lookup-close-btn"),
  zhScroll: document.getElementById("zh-scroll"),
  enScroll: document.getElementById("en-scroll"),
};

const Logic = window.VersoFrontendLogic || {};

const state = {
  books: [],
  projects: [],
  currentProjectId: null,
  currentProject: null,
  chapters: [],
  mappings: [],
  jobs: [],
  mode: "read",
  currentChapterIndex: 0,
  currentReader: null,
  currentAlignment: null,
  currentAnchors: [],
  enChapterOptions: [],
  activeZhIndex: null,
  activeEnRange: null,
  isLibraryOpen: false,
  pendingZhAnchor: null,
  anchorDraft: {
    zhStart: null,
    zhEnd: null,
    enStart: null,
    enEnd: null,
  },
  isSyncing: false,
  zhOffsets: [],
  enOffsets: [],
  localSyncMap: [],
  enRangesByZh: [],
  enReverseMap: new Map(),
  mappingProgressTimer: null,
  alignProgressTimer: null,
  jobPollTimer: null,
  mappingCollapsed: false,
  anchorFloatCollapsed: false,
  alignBusy: false,
  lookupOpen: false,
};

function isMappingConfirmed() {
  return Boolean(state.chapters.length) && state.chapters.every((chapter) => chapter.mapping_confirmed);
}

function renderMappingCollapsedMeta() {
  if (!els.mappingCollapsedMeta) {
    return;
  }
  const total = state.chapters.length;
  const confirmed = state.chapters.filter((chapter) => chapter.mapping_confirmed).length;
  const mapped = state.chapters.filter((chapter) => chapter.mapped_en_chapter_index !== null && chapter.mapped_en_chapter_index !== undefined).length;
  els.mappingCollapsedMeta.innerHTML = [
    `<span class="tag state-confirmed">已确认 ${confirmed}/${total || 0}</span>`,
    `<span class="tag state-draft">已配对 ${mapped}/${total || 0}</span>`,
  ].join("");
}

function updateMappingPanelUI() {
  const canCollapse = isMappingConfirmed();
  if (!canCollapse) {
    state.mappingCollapsed = false;
  }
  els.mappingPanel.classList.toggle("is-collapsed", state.mappingCollapsed);
  if (els.mappingHeader) {
    els.mappingHeader.classList.toggle("hidden", state.mappingCollapsed);
  }
  if (els.mappingContent) {
    els.mappingContent.classList.toggle("hidden", state.mappingCollapsed);
  }
  if (els.mappingCollapsedSummary) {
    els.mappingCollapsedSummary.classList.toggle("hidden", !state.mappingCollapsed);
  }
  if (els.mappingCollapsedHint) {
    els.mappingCollapsedHint.textContent = canCollapse
      ? "当前章节配对已锁定，可随时展开查看和微调。"
      : "章节配对锁定后才可收起。";
  }
  if (els.mappingToggleBtn) {
    els.mappingToggleBtn.disabled = !canCollapse;
    els.mappingToggleBtn.textContent = state.mappingCollapsed ? "展开配对" : "收起配对";
    els.mappingToggleBtn.title = canCollapse ? "收起或展开已锁定的章节配对" : "章节配对锁定后才可收起";
  }
  renderMappingCollapsedMeta();
}

function setStatus(message, isError = false) {
  els.statusText.textContent = message;
  els.statusText.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function setBusyStatus(message) {
  setStatus(message);
  els.statusText.classList.add("is-busy");
}

function clearBusyStatus() {
  els.statusText.classList.remove("is-busy");
}

async function api(path, options = {}) {
  const opts = { ...options };
  opts.headers = opts.headers || {};
  if (opts.body && !(opts.body instanceof FormData) && !opts.headers["Content-Type"]) {
    opts.headers["Content-Type"] = "application/json";
  }
  if (opts.body && opts.headers["Content-Type"] === "application/json" && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
  }
  const response = await fetch(path, opts);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function fmtTag(stateName) {
  const safeClass = String(stateName || "missing").split(/\s|·/)[0] || "missing";
  return `<span class="tag state-${escapeHtml(safeClass)}">${escapeHtml(stateName)}</span>`;
}

function languageLabel(language) {
  return language === "zh" ? "中文" : language === "en" ? "英文" : String(language || "未知语言").toUpperCase();
}

function projectStatusLabel(status) {
  const labels = {
    draft: "制作中",
    mapped: "已配章节",
    aligned: "已对齐",
  };
  return labels[status] || status || "未知状态";
}

function alignmentStateText(stateName) {
  const labels = {
    confirmed: "已确认",
    draft: "待确认",
    missing: "未对齐",
    skipped: "已跳过",
    approximate: "近似对应",
  };
  return labels[stateName] || stateName || "未对齐";
}

function mappingSourceLabel(source) {
  const labels = {
    manual: "手动选择",
    lm: "AI 建议",
    llm: "AI 建议",
    heuristic: "自动规则",
    fallback: "规则兜底",
    dp: "自动规则",
  };
  return labels[String(source || "").toLowerCase()] || source || "手动选择";
}

function policyLabel(policy) {
  if (policy === "off") {
    return "不使用 AI";
  }
  if (policy === "force") {
    return "强制 AI";
  }
  return "自动 AI";
}

function jobStatusLabel(status) {
  const labels = {
    pending: "等待中",
    running: "进行中",
    completed: "已完成",
    failed: "失败",
  };
  return labels[status] || status || "未知";
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function downloadJson(filename, obj) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function updateLibraryUI() {
  document.body.classList.toggle("library-open", state.isLibraryOpen);
  if (els.libraryToggleBtn) {
    els.libraryToggleBtn.dataset.full = state.isLibraryOpen ? "隐藏书库" : "书库与项目";
    els.libraryToggleBtn.dataset.short = state.isLibraryOpen ? "隐藏" : "书库";
  }
  updateResponsiveButtonLabels();
}

function updateResponsiveButtonLabels() {
  const compact = window.matchMedia("(max-width: 700px)").matches;
  document.querySelectorAll(".hero-actions button[data-short]").forEach((button) => {
    button.textContent = compact ? button.dataset.short : button.dataset.full;
  });
}

function bookLabel(book) {
  const format = (book.source_format || "epub").toUpperCase();
  return `#${book.id} · ${book.title} · ${languageLabel(book.language)} · ${format} · ${book.chapter_count}章 / ${book.paragraph_count}段`;
}

function renderBookOptions() {
  const zhBooks = state.books.filter((book) => book.language === "zh");
  const enBooks = state.books.filter((book) => book.language === "en");
  els.zhBookSelect.innerHTML = zhBooks.length
    ? zhBooks.map((book) => `<option value="${book.id}">${escapeHtml(bookLabel(book))}</option>`).join("")
    : `<option value="">暂无中文书</option>`;
  els.enBookSelect.innerHTML = enBooks.length
    ? enBooks.map((book) => `<option value="${book.id}">${escapeHtml(bookLabel(book))}</option>`).join("")
    : `<option value="">暂无英文书</option>`;
}

function renderBookList() {
  if (!state.books.length) {
    els.bookList.innerHTML = `<div class="list-card"><div class="meta-line">书库为空，请先上传 EPUB。</div></div>`;
    return;
  }
  els.bookList.innerHTML = state.books
    .map(
      (book) => `
        <div class="list-card">
          <h4>${escapeHtml(book.title)}</h4>
          <div class="meta-line">${escapeHtml(book.source_filename)}</div>
          <div class="meta-line">${languageLabel(book.language)} · ${(book.source_format || "epub").toUpperCase()} · ${book.chapter_count}章 · ${book.paragraph_count}段 · ${book.char_total} 字符</div>
          <div class="card-actions">
            <button class="secondary-btn danger-btn tiny-btn" type="button" data-book-delete-id="${book.id}">删除书籍</button>
          </div>
        </div>
      `
    )
    .join("");
}

function renderProjectList() {
  if (!state.projects.length) {
    els.projectList.innerHTML = `<div class="list-card"><div class="meta-line">还没有项目。创建一个中英配对项目开始。</div></div>`;
    return;
  }
  els.projectList.innerHTML = state.projects
    .map((project) => {
      const active = Number(project.id) === Number(state.currentProjectId) ? "active" : "";
      return `
        <button class="list-card ${active}" data-project-id="${project.id}" type="button">
          <h4>#${project.id} · ${escapeHtml(project.zh_title)} ↔ ${escapeHtml(project.en_title)}</h4>
          <div class="meta-line">${escapeHtml(projectStatusLabel(project.status))} · 章节配对 ${project.mapping_count} · 已确认 ${project.confirmed_count}</div>
        </button>
      `;
    })
    .join("");
}

function renderJobs() {
  if (!state.jobs.length) {
    els.jobList.innerHTML = `<div class="job-row"><span class="muted">暂无后台任务。</span></div>`;
    updateJobPolling();
    return;
  }
  const activeJobIndexes = new Set(
    state.jobs
      .map((job, index) => ["pending", "running"].includes(job.status) ? index : null)
      .filter((index) => index !== null),
  );
  const wideVisibleJobIndexes = new Set([0, 1, ...activeJobIndexes]);
  const hiddenWideCount = state.jobs.filter((_, index) => !wideVisibleJobIndexes.has(index)).length;
  els.jobList.innerHTML = state.jobs
    .map(
      (job, index) => {
        const result = job.result || {};
        const done = Number(result.done_count ?? (result.aligned_chapters || []).length ?? 0);
        const total = Number(result.total_count ?? 0);
        const current = result.current_chapter === null || result.current_chapter === undefined
          ? ""
          : ` · 中${Number(result.current_chapter) + 1}`;
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        const progress = total > 0 ? `${done}/${total}${current}` : "无进度";
        const policy = job.payload?.llm_policy || result.llm_policy || "auto";
        const typeLabel = {
          align_remaining: "对齐剩余章节",
          prefetch: "预对齐章节",
        }[job.type] || job.type;
        const wideVisibilityClass = wideVisibleJobIndexes.has(index) ? "" : " is-job-extra";
        return `
          <div class="job-row${wideVisibilityClass}">
            <div>
              <strong>${escapeHtml(typeLabel)}</strong>
              <div class="meta-line">${escapeHtml(progress)} · ${escapeHtml(policyLabel(policy))}</div>
              ${total > 0 ? `<div class="mini-progress"><span style="width:${Math.max(0, Math.min(100, pct))}%"></span></div>` : ""}
            </div>
            <span class="tag state-${escapeHtml(job.status)}">${escapeHtml(jobStatusLabel(job.status))}</span>
          </div>
        `;
      }
    )
    .join("") + (hiddenWideCount > 0
      ? `<div class="job-summary-row">另有 ${hiddenWideCount} 个较早任务</div>`
      : "");
  updateJobPolling();
}

function hasActiveJobs() {
  return state.jobs.some((job) => ["pending", "running"].includes(job.status));
}

async function refreshJobsOnly() {
  if (!state.currentProjectId) {
    return;
  }
  const jobsPayload = await api(`/api/projects/${state.currentProjectId}/jobs`);
  state.jobs = jobsPayload.jobs || [];
  renderJobs();
}

function updateJobPolling() {
  const shouldPoll = Boolean(state.currentProjectId) && hasActiveJobs();
  if (shouldPoll && !state.jobPollTimer) {
    state.jobPollTimer = window.setInterval(() => {
      refreshJobsOnly().catch((error) => {
        setStatus(error instanceof Error ? error.message : "刷新后台任务失败。", true);
      });
    }, 2000);
  }
  if (!shouldPoll && state.jobPollTimer) {
    window.clearInterval(state.jobPollTimer);
    state.jobPollTimer = null;
  }
}

function renderProjectSummary() {
  const hasProject = Boolean(state.currentProject);
  els.exportProjectBtn.disabled = !hasProject;
  els.deleteProjectBtn.disabled = !hasProject;
  els.prefetchBtn.disabled = !hasProject;
  els.alignRemainingBtn.disabled = !hasProject;
  if (!hasProject) {
    els.projectTitle.textContent = "尚未选择项目";
    els.projectSummary.textContent = "从左侧选择项目，进入阅读或对齐工作区。";
    return;
  }
  const stats = state.currentProject.stats;
  const project = state.currentProject.project;
  els.projectTitle.textContent = `项目 #${project.id} · ${project.zh_title} ↔ ${project.en_title}`;
  els.projectSummary.textContent =
    `${projectStatusLabel(project.status)} · 中文 ${stats.zh_chapter_count} 章 / ${stats.zh_paragraph_count} 段 · 英文 ${stats.en_chapter_count} 章 / ${stats.en_paragraph_count} 段 · 已确认 ${stats.confirmed_alignment_count} 章。`;
}

function renderChapterList() {
  if (!state.chapters.length) {
    els.chapterList.innerHTML = `<div class="chapter-card"><div class="meta-line">项目尚未加载章节。</div></div>`;
    return;
  }
  els.chapterList.innerHTML = state.chapters
    .map((chapter) => {
      const active = chapter.zh_chapter_index === state.currentChapterIndex ? "active" : "";
      const mapped = chapter.mapped_en_chapter_index === null || chapter.mapped_en_chapter_index === undefined
        ? "未映射"
        : `英${chapter.mapped_en_chapter_index + 1} ${chapter.mapped_en_title || ""}`;
      const alignmentLabel = Logic.alignmentStateLabel
        ? Logic.alignmentStateLabel(chapter.alignment_state, chapter.alignment_source)
        : alignmentStateText(chapter.alignment_state);
      return `
        <button class="chapter-card ${active}" type="button" data-chapter-index="${chapter.zh_chapter_index}">
          <h4>中${chapter.zh_chapter_index + 1}. ${escapeHtml(chapter.zh_title || "未命名章节")}</h4>
          <div class="meta-line">${escapeHtml(mapped)}</div>
          <div class="meta-line">
            ${fmtTag(alignmentLabel)}
            <span class="tag state-${chapter.mapping_confirmed ? "confirmed" : "draft"}">${chapter.mapping_confirmed ? "章节配对已锁定" : "章节配对草稿"}</span>
          </div>
        </button>
      `;
    })
    .join("");
}

function renderMappingTable() {
  const chapters = state.chapters;
  if (!chapters.length) {
    els.mappingTable.innerHTML = `<div class="mapping-row"><div class="mapping-meta">先选择项目。</div></div>`;
    return;
  }
  const enOptions = state.enChapterOptions
    .map((chapter) => {
      const title = chapter.title || "未命名章节";
      return `<option value="${chapter.en_chapter_index}">${escapeHtml(`英${chapter.en_chapter_index + 1} · ${title}`)}</option>`;
    })
    .join("");
  els.mappingTable.innerHTML = chapters
    .map((chapter) => {
      const mapping = state.mappings.find((item) => item.zh_chapter_index === chapter.zh_chapter_index);
      const current = mapping ? Number(mapping.en_chapter_index) : 0;
      const confidence = mapping?.confidence;
      return `
        <div class="mapping-row">
          <div>
            <strong>中${chapter.zh_chapter_index + 1}. ${escapeHtml(chapter.zh_title || "未命名章节")}</strong>
            <div class="mapping-meta">来源：${escapeHtml(mappingSourceLabel(mapping?.source || "manual"))} · 置信度：${confidence === null || confidence === undefined ? "无" : Number(confidence).toFixed(3)}</div>
            <div class="mapping-meta">${escapeHtml(mapping?.reason || "")}</div>
          </div>
          <div class="mapping-right">
            <select data-map-index="${chapter.zh_chapter_index}">${enOptions}</select>
          </div>
        </div>
      `;
    })
    .join("");
  els.mappingTable.querySelectorAll("select[data-map-index]").forEach((select) => {
    const chapterIndex = Number(select.dataset.mapIndex);
    const mapping = state.mappings.find((item) => item.zh_chapter_index === chapterIndex);
    select.value = String(mapping ? mapping.en_chapter_index : 0);
    select.addEventListener("change", () => {
      upsertLocalMapping(chapterIndex, Number(select.value));
    });
  });
}

function upsertLocalMapping(chapterIndex, enIndex) {
  state.mappings = Logic.upsertMapping
    ? Logic.upsertMapping(state.mappings, chapterIndex, enIndex)
    : state.mappings;
  state.chapters = state.chapters.map((chapter) => (
    chapter.zh_chapter_index === chapterIndex
      ? { ...chapter, mapped_en_chapter_index: enIndex, mapping_confirmed: false, mapping_source: "manual" }
      : chapter
  ));
  renderMappingTable();
  renderChapterList();
  updateMappingPanelUI();
}

function renderAnchors() {
  if (!state.currentAnchors.length) {
    els.anchorList.innerHTML = `<div class="anchor-row"><span class="muted">当前章节还没有人工固定的段落对应。</span></div>`;
    return;
  }
  els.anchorList.innerHTML = state.currentAnchors
    .map(
      (anchor) => `
        <div class="anchor-row">
          <div>
            <strong>中${formatRangeLabel(Number(anchor.zh_start ?? anchor.zh_paragraph_index), Number(anchor.zh_end ?? anchor.zh_paragraph_index))} ↔ 英${formatRangeLabel(Number(anchor.en_start ?? anchor.en_paragraph_index), Number(anchor.en_end ?? anchor.en_paragraph_index))}</strong>
            <div class="meta-line">${anchor.kind === "hard" ? "人工固定" : escapeHtml(anchor.kind)} · ${anchor.confirmed ? "已生效" : "草稿"}${anchor.note ? ` · ${escapeHtml(anchor.note)}` : ""}</div>
          </div>
          <button type="button" data-anchor-id="${anchor.id}" class="secondary-btn">删除固定对应</button>
        </div>
      `
    )
    .join("");
}

function renderReviews() {
  const items = state.currentAlignment?.review_items || [];
  if (!items.length) {
    els.reviewList.innerHTML = `<div class="review-row"><span class="muted">当前章节没有低置信块。</span></div>`;
    return;
  }
  els.reviewList.innerHTML = items
    .map(
      (item) => `
        <div class="review-row">
          <div>
            <strong>中[${item.zh_start}-${item.zh_end}] → 英[${item.en_start}-${item.en_end}]</strong>
            <div class="meta-line">置信度 ${Number(item.confidence).toFixed(3)} · ${escapeHtml(item.reason || "需要人工检查")}</div>
          </div>
        </div>
      `
    )
    .join("");
}

function startMappingProgress() {
  if (!els.mappingProgressWrap || !els.mappingProgressBar || !els.mappingProgressText) {
    return;
  }
  if (state.mappingProgressTimer) {
    window.clearInterval(state.mappingProgressTimer);
  }
  let progress = 6;
  els.mappingProgressWrap.classList.remove("hidden");
  els.mappingProgressBar.style.width = `${progress}%`;
  els.mappingProgressText.textContent = "正在生成章节配对建议...";
  state.mappingProgressTimer = window.setInterval(() => {
    progress = Math.min(92, progress + (progress < 50 ? 10 : 4));
    els.mappingProgressBar.style.width = `${progress}%`;
  }, 280);
}

function finishMappingProgress(message) {
  if (!els.mappingProgressWrap || !els.mappingProgressBar || !els.mappingProgressText) {
    return;
  }
  if (state.mappingProgressTimer) {
    window.clearInterval(state.mappingProgressTimer);
    state.mappingProgressTimer = null;
  }
  els.mappingProgressBar.style.width = "100%";
  els.mappingProgressText.textContent = message;
  window.setTimeout(() => {
    els.mappingProgressWrap.classList.add("hidden");
    els.mappingProgressBar.style.width = "0%";
  }, 700);
}

function setAlignBusy(isBusy) {
  state.alignBusy = isBusy;
  if (els.alignChapterBtn) {
    els.alignChapterBtn.disabled = isBusy;
  }
  if (els.regenerateChapterBtn) {
    els.regenerateChapterBtn.disabled = isBusy;
  }
  if (els.confirmChapterBtn) {
    els.confirmChapterBtn.disabled = isBusy;
  }
  if (els.skipChapterBtn) {
    els.skipChapterBtn.disabled = isBusy;
  }
}

function startAlignProgress(force = false) {
  if (!els.alignProgressWrap || !els.alignProgressBar || !els.alignProgressText) {
    return;
  }
  if (state.alignProgressTimer) {
    window.clearInterval(state.alignProgressTimer);
  }
  let progress = 8;
  els.alignProgressWrap.classList.remove("hidden");
  els.alignProgressBar.style.width = `${progress}%`;
  els.alignProgressText.textContent = force
    ? "正在重新计算并对齐本章段落..."
    : "正在对齐本章段落...";
  state.alignProgressTimer = window.setInterval(() => {
    progress = Math.min(94, progress + (progress < 48 ? 11 : 5));
    els.alignProgressBar.style.width = `${progress}%`;
  }, 260);
}

function finishAlignProgress(message) {
  if (!els.alignProgressWrap || !els.alignProgressBar || !els.alignProgressText) {
    return;
  }
  if (state.alignProgressTimer) {
    window.clearInterval(state.alignProgressTimer);
    state.alignProgressTimer = null;
  }
  els.alignProgressBar.style.width = "100%";
  els.alignProgressText.textContent = message;
  window.setTimeout(() => {
    els.alignProgressWrap.classList.add("hidden");
    els.alignProgressBar.style.width = "0%";
  }, 700);
}

function updateModeUI() {
  const align = state.mode === "align";
  document.body.classList.toggle("mode-read", state.mode === "read");
  document.body.classList.toggle("mode-align", align);
  els.modeReadBtn.classList.toggle("active", state.mode === "read");
  els.modeAlignBtn.classList.toggle("active", align);
  els.mappingPanel.classList.toggle("hidden", !align);
  els.alignPanel.classList.toggle("hidden", !align);
  updateAnchorFloatUI();
  updateMappingPanelUI();
  els.anchorMode.checked = false;
  state.pendingZhAnchor = null;
  state.anchorDraft = { zhStart: null, zhEnd: null, enStart: null, enEnd: null };
  updateAnchorHint();
}

function setLookupOpen(open) {
  state.lookupOpen = Boolean(open);
  if (els.lookupPanel) {
    els.lookupPanel.classList.toggle("is-open", state.lookupOpen);
  }
  if (els.lookupColumn) {
    els.lookupColumn.classList.toggle("is-open", state.lookupOpen);
  }
  const lookupDockMode = state.mode === "read" || state.mode === "align";
  document.body.classList.toggle("reader-lookup-open", state.lookupOpen && lookupDockMode);
}

function isMobileReaderLayout() {
  return window.matchMedia("(max-width: 1100px)").matches;
}

function updateAnchorFloatUI() {
  if (!els.anchorFloat) {
    return;
  }
  const visible = state.mode === "align";
  els.anchorFloat.classList.toggle("hidden", !visible);
  els.anchorFloat.classList.toggle("is-collapsed", state.anchorFloatCollapsed);
  if (els.anchorFloatBody) {
    els.anchorFloatBody.classList.toggle("hidden", state.anchorFloatCollapsed);
  }
  if (els.anchorFloatToggle) {
    els.anchorFloatToggle.textContent = state.anchorFloatCollapsed ? "展开" : "收起";
    els.anchorFloatToggle.setAttribute("aria-expanded", state.anchorFloatCollapsed ? "false" : "true");
  }
}

function updateAnchorHint() {
  const draft = state.anchorDraft;
  const hasZh = draft.zhStart !== null && draft.zhEnd !== null;
  const hasEn = draft.enStart !== null && draft.enEnd !== null;
  if (state.mode !== "align") {
    els.anchorHint.textContent = "阅读模式不编辑固定对应。";
  } else if (!els.anchorMode.checked) {
    els.anchorHint.textContent = "开启后点选连续中文段，再在右侧原文框点选对应英文段。";
  } else if (!hasZh) {
    els.anchorHint.textContent = draft.zhStart === null
      ? "请选择中文起始段。"
      : `已选中文第 ${draft.zhStart + 1} 段，请再次点击中文段确定范围。`;
  } else if (!hasEn) {
    els.anchorHint.textContent = draft.enStart === null
      ? `已选中文 ${formatRangeLabel(draft.zhStart, draft.zhEnd)}，请在右侧原文框选择英文起始段。`
      : `已选英文第 ${draft.enStart + 1} 段，请再次点击英文段确定范围。`;
  } else {
    els.anchorHint.textContent = `待保存固定对应：中 ${formatRangeLabel(draft.zhStart, draft.zhEnd)} ↔ 英 ${formatRangeLabel(draft.enStart, draft.enEnd)}`;
  }
  if (els.createAnchorBtn) {
    els.createAnchorBtn.disabled = !(state.mode === "align" && els.anchorMode.checked && hasZh && hasEn);
  }
  if (els.resetAnchorBtn) {
    els.resetAnchorBtn.disabled = !(state.mode === "align" && els.anchorMode.checked && (
      draft.zhStart !== null || draft.enStart !== null
    ));
  }
}

function formatRangeLabel(start, end) {
  if (start === null || end === null) {
    return "未选择";
  }
  return start === end ? `${start + 1}` : `${start + 1}-${end + 1}`;
}

function normalizeAnchorRange(start, end) {
  if (start === null || end === null) {
    return null;
  }
  const a = Number(start);
  const b = Number(end);
  return { start: Math.min(a, b), end: Math.max(a, b) };
}

function resetAnchorDraft() {
  state.pendingZhAnchor = null;
  state.anchorDraft = { zhStart: null, zhEnd: null, enStart: null, enEnd: null };
  updateAnchorHint();
  renderReader();
}

function paragraphClass(side, localIndex) {
  const classes = ["para"];
  const draft = state.anchorDraft;
  const zhPending = normalizeAnchorRange(
    draft.zhStart,
    draft.zhEnd === null ? draft.zhStart : draft.zhEnd,
  );
  const enPending = normalizeAnchorRange(
    draft.enStart,
    draft.enEnd === null ? draft.enStart : draft.enEnd,
  );
  if (state.mode === "align" && side === "zh" && zhPending && localIndex >= zhPending.start && localIndex <= zhPending.end) {
    classes.push("pending");
  }
  if (state.mode === "align" && side === "en" && enPending && localIndex >= enPending.start && localIndex <= enPending.end) {
    classes.push("pending");
  }
  const anchored = state.currentAnchors.some((anchor) => (
    anchor.kind === "hard" && anchor.confirmed && (
      side === "zh"
        ? localIndex >= Number(anchor.zh_start ?? anchor.zh_paragraph_index) && localIndex <= Number(anchor.zh_end ?? anchor.zh_paragraph_index)
        : localIndex >= Number(anchor.en_start ?? anchor.en_paragraph_index) && localIndex <= Number(anchor.en_end ?? anchor.en_paragraph_index)
    )
  ));
  if (anchored) {
    classes.push("anchor");
  }
  return classes.join(" ");
}

function englishRangeLabel(range) {
  if (!range) {
    return "英文";
  }
  return Logic.formatEnglishRangeLabel ? Logic.formatEnglishRangeLabel(range) : `英文 ${range.start + 1}`;
}

function renderLookupPanel() {
  if (!els.lookupPanel || !els.lookupContent || !els.lookupLabel) {
    return;
  }
  const reader = state.currentReader;
  if (!reader) {
    els.lookupPanel.classList.add("hidden");
    setLookupOpen(false);
    return;
  }
  els.lookupPanel.classList.remove("hidden");
  els.lookupContent.style.paddingTop = "0px";
  if (state.activeZhIndex === null || !state.activeEnRange) {
    els.lookupLabel.textContent = "英文";
    els.lookupContent.innerHTML = `<p class="muted">点击中文段落查看对应英文原文。</p>`;
    if (els.reportMismatchBtn) {
      els.reportMismatchBtn.classList.add("hidden");
    }
    setLookupOpen(false);
    return;
  }
  if (els.reportMismatchBtn) {
    els.reportMismatchBtn.classList.toggle("hidden", state.mode !== "read");
  }
  const range = state.activeEnRange;
  els.lookupLabel.textContent = englishRangeLabel(range);
  const context = Logic.englishContextWindow
    ? Logic.englishContextWindow(reader.en_paragraphs.length, range)
    : { start: range.start, end: range.end };
  const lines = [];
  for (let enIndex = context.start; enIndex <= context.end; enIndex += 1) {
    const text = reader.en_paragraphs[enIndex];
    if (text) {
      const active = enIndex >= range.start && enIndex <= range.end ? " active" : "";
      const classes = `${paragraphClass("en", enIndex)} lookup-para${active}`;
      lines.push(`
        <p class="${classes}" data-side="en" data-index="${enIndex}">
          <span class="lookup-index">英文 ${enIndex + 1}</span>
          ${escapeHtml(text)}
        </p>
      `);
    }
  }
  els.lookupContent.innerHTML = lines.join("") || `<p class="muted">当前中文段暂无英文对应。</p>`;
  setLookupOpen(true);
  window.requestAnimationFrame(() => alignLookupToChinese());
}

function alignLookupToChinese() {
  if ((state.mode === "read" || state.mode === "align") && isMobileReaderLayout()) {
    return;
  }
  if (state.activeZhIndex === null || !els.lookupPanel || !els.lookupContent) {
    return;
  }
  const zhEl = els.zhScroll.querySelector(`.para[data-index="${state.activeZhIndex}"]`);
  const activeEnEl = els.lookupContent.querySelector(".lookup-para.active");
  if (!zhEl || !activeEnEl) {
    return;
  }
  const zhRect = zhEl.getBoundingClientRect();
  const zhScrollRect = els.zhScroll.getBoundingClientRect();
  const panelRect = els.lookupPanel.getBoundingClientRect();
  const relativeTop = zhRect.top - zhScrollRect.top;
  const desiredTop = Math.max(12, Math.min(panelRect.height - 80, relativeTop));
  const offset = activeEnEl.offsetTop;
  const padding = Math.max(0, desiredTop - offset);
  els.lookupContent.style.paddingTop = `${padding}px`;
  window.requestAnimationFrame(() => {
    const target = activeEnEl.offsetTop - desiredTop;
    els.lookupPanel.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
  });
}

function renderReader() {
  const reader = state.currentReader;
  if (!reader) {
    els.readerTitle.textContent = "阅读区";
    els.readerMeta.textContent = "当前项目还没有可加载的章节内容。";
    els.zhScroll.innerHTML = `<p class="para">暂无中文内容。</p>`;
    if (els.enScroll) {
      els.enScroll.innerHTML = `<p class="para">暂无英文内容。</p>`;
    }
    state.zhOffsets = [];
    state.enOffsets = [];
    state.localSyncMap = [];
    state.enRangesByZh = [];
    state.enReverseMap = new Map();
    state.activeZhIndex = null;
    state.activeEnRange = null;
    setLookupOpen(false);
    renderLookupPanel();
    return;
  }
  els.readerTitle.textContent = `中${reader.chapter_index + 1}《${reader.zh_title || "未命名章节"}》 ↔ 英${reader.mapped_en_chapter_index + 1}《${reader.en_title || "未命名章节"}》`;
  els.readerMeta.textContent = `对应状态：${alignmentStateText(reader.sync_source)} · 中文 ${reader.zh_paragraphs.length} 段 · 英文 ${reader.en_paragraphs.length} 段`;
  state.localSyncMap = Array.isArray(reader.local_sync_map) ? reader.local_sync_map : [];
  state.enRangesByZh = Array.isArray(reader.en_ranges_by_zh) ? reader.en_ranges_by_zh : [];
  state.enReverseMap = Logic.buildReverseMap
    ? Logic.buildReverseMap(state.localSyncMap)
    : new Map();
  els.zhScroll.innerHTML = reader.zh_paragraphs
    .map((text, index) => `<p class="${paragraphClass("zh", index)}" data-side="zh" data-index="${index}">${escapeHtml(text)}</p>`)
    .join("");
  if (els.enScroll) {
    els.enScroll.innerHTML = reader.en_paragraphs
      .map((text, index) => `<p class="${paragraphClass("en", index)}" data-side="en" data-index="${index}">${escapeHtml(text)}</p>`)
      .join("");
  }
  if (state.activeZhIndex !== null) {
    const anchorRangeOverride = state.mode === "align" && els.anchorMode.checked && state.anchorDraft.zhStart !== null && state.anchorDraft.zhEnd !== null
      ? state.activeEnRange
      : null;
    setActivePair(state.activeZhIndex, { scrollEnglish: false, rangeOverride: anchorRangeOverride });
  } else {
    renderLookupPanel();
  }
  window.requestAnimationFrame(() => {
    state.zhOffsets = Array.from(els.zhScroll.querySelectorAll(".para")).map((el) => el.offsetTop);
    state.enOffsets = els.enScroll
      ? Array.from(els.enScroll.querySelectorAll(".para")).map((el) => el.offsetTop)
      : [];
  });
}

function clearActiveParagraphs() {
  els.zhScroll.querySelectorAll(".para.active").forEach((el) => el.classList.remove("active"));
  els.enScroll?.querySelectorAll(".para.active").forEach((el) => el.classList.remove("active"));
}

function englishRangeForZhSpan(zhStart, zhEnd) {
  const ranges = [];
  for (let zhIndex = zhStart; zhIndex <= zhEnd; zhIndex += 1) {
    const range = Logic.englishRangeForZh
      ? Logic.englishRangeForZh(state.enRangesByZh, zhIndex, state.localSyncMap)
      : { start: Number(state.localSyncMap[zhIndex] ?? 0), end: Number(state.localSyncMap[zhIndex] ?? 0) };
    ranges.push(range);
  }
  if (!ranges.length) {
    return null;
  }
  return {
    start: Math.min(...ranges.map((range) => Number(range.start || 0))),
    end: Math.max(...ranges.map((range) => Number(range.end ?? range.start ?? 0))),
  };
}

function setActivePair(zhIndex, options = {}) {
  clearActiveParagraphs();
  state.activeZhIndex = zhIndex;
  const zhEl = els.zhScroll.querySelector(`.para[data-index="${zhIndex}"]`);
  zhEl?.classList.add("active");
  const range = options.rangeOverride || (Logic.englishRangeForZh
    ? Logic.englishRangeForZh(state.enRangesByZh, zhIndex, state.localSyncMap)
    : { start: Number(state.localSyncMap[zhIndex] ?? 0), end: Number(state.localSyncMap[zhIndex] ?? 0) });
  state.activeEnRange = range;
  if (els.enScroll) {
    for (let enIndex = range.start; enIndex <= range.end; enIndex += 1) {
      const enEl = els.enScroll.querySelector(`.para[data-index="${enIndex}"]`);
      enEl?.classList.add("active");
    }
  }
  renderLookupPanel();
  if (els.enScroll && options.scrollEnglish !== false) {
    const top = state.enOffsets[range.start] || 0;
    els.enScroll.scrollTo({ top: Math.max(0, top - els.enScroll.clientHeight * 0.18), behavior: "smooth" });
  }
}

function syncReader() {
  if (!state.currentReader || state.isSyncing) {
    return;
  }
  const target = Logic.syncTargetIndex
    ? Logic.syncTargetIndex(
      state.localSyncMap,
      state.zhOffsets,
      els.zhScroll.scrollTop,
      els.zhScroll.clientHeight,
      state.enReverseMap,
    )
    : { zhIndex: 0, enIndex: 0, enTarget: 0 };
  const zhIndex = target.zhIndex;
  state.isSyncing = true;
  setActivePair(zhIndex);
  window.setTimeout(() => {
    state.isSyncing = false;
  }, 180);
}

async function refreshLibrary() {
  const [bookPayload, projectPayload] = await Promise.all([
    api("/api/books"),
    api("/api/projects"),
  ]);
  state.books = bookPayload.books || [];
  state.projects = projectPayload.projects || [];
  renderBookOptions();
  renderBookList();
  renderProjectList();
  if (state.currentProjectId) {
    const stillExists = state.projects.some((project) => Number(project.id) === Number(state.currentProjectId));
    if (!stillExists) {
      state.currentProjectId = null;
      state.currentProject = null;
      state.chapters = [];
      renderProjectSummary();
      renderChapterList();
      renderReader();
      renderJobs();
    }
  }
}

async function loadProject(projectId) {
  state.currentProjectId = Number(projectId);
  state.activeZhIndex = null;
  state.activeEnRange = null;
  setLookupOpen(false);
  const [overview, mappingPayload, jobsPayload] = await Promise.all([
    api(`/api/projects/${projectId}`),
    api(`/api/projects/${projectId}/chapter-mapping`),
    api(`/api/projects/${projectId}/jobs`),
  ]);
  state.currentProject = overview;
  state.chapters = overview.chapters || [];
  state.enChapterOptions = overview.en_chapters || [];
  const rawMappings = mappingPayload.mappings || [];
  state.mappings = Logic.buildInitialMappings
    ? Logic.buildInitialMappings(state.chapters, rawMappings, state.currentProject.stats.en_chapter_count)
    : rawMappings;
  state.jobs = jobsPayload.jobs || [];
  state.currentChapterIndex = Math.min(state.currentChapterIndex, Math.max(0, state.chapters.length - 1));
  state.mappingCollapsed = isMappingConfirmed();
  renderProjectSummary();
  renderProjectList();
  renderChapterList();
  renderMappingTable();
  renderJobs();
  updateMappingPanelUI();
  await loadCurrentChapter();
}

async function loadCurrentChapter() {
  if (!state.currentProjectId || !state.chapters.length) {
    state.currentReader = null;
    state.currentAlignment = null;
    state.currentAnchors = [];
    renderReader();
    renderAnchors();
    renderReviews();
    return;
  }
  const chapter = state.chapters[state.currentChapterIndex];
  if (!chapter) {
    return;
  }
  state.activeZhIndex = null;
  state.activeEnRange = null;
  setLookupOpen(false);
  try {
    if (state.mode === "read") {
      state.currentReader = await api(`/api/projects/${state.currentProjectId}/reader/chapters/${state.currentChapterIndex}`);
      state.currentAlignment = null;
      state.currentAnchors = [];
    } else {
      const payload = await api(`/api/projects/${state.currentProjectId}/chapters/${state.currentChapterIndex}/alignment`);
      state.currentReader = {
        chapter_index: payload.chapter_index,
        mapped_en_chapter_index: payload.mapped_en_chapter_index,
        zh_title: payload.zh_title,
        en_title: payload.en_title,
        zh_range: payload.zh_range,
        en_range: payload.en_range,
        zh_paragraphs: payload.zh_paragraphs,
        en_paragraphs: payload.en_paragraphs,
        local_sync_map: payload.alignment?.local_sync_map || payload.local_sync_map,
        en_ranges_by_zh: payload.alignment?.en_ranges_by_zh || payload.en_ranges_by_zh || [],
        sync_source: payload.alignment?.state || payload.sync_source,
      };
      state.currentAlignment = payload.alignment;
      state.currentAnchors = payload.anchors || [];
      const metrics = state.currentAlignment?.metrics;
      if (metrics) {
        const source = Logic.alignmentSourceLabel
          ? Logic.alignmentSourceLabel(metrics.alignment_source)
          : (metrics.alignment_source || "unknown");
        const summary = Logic.decisionSummary
          ? Logic.decisionSummary(metrics.decision_log || [])
          : "";
        els.alignMeta.textContent =
          `当前章：${alignmentStateText(state.currentAlignment?.state)} · 来源：${source} · AI 调用 ${metrics.llm_calls || 0} 次 · 规则段 ${metrics.heuristic_segments || 0}${summary ? ` · ${summary}` : ""}`;
      } else {
        els.alignMeta.textContent = "当前章尚未对齐。";
      }
    }
    renderReader();
    renderAnchors();
    renderReviews();
    setStatus(`已加载中${state.currentChapterIndex + 1}章。`);
  } catch (error) {
    state.currentReader = null;
    state.currentAlignment = null;
    state.currentAnchors = [];
    renderReader();
    renderAnchors();
    renderReviews();
    setStatus(error instanceof Error ? error.message : "章节加载失败。", true);
  }
}

async function uploadBook() {
  const file = els.bookFile.files?.[0];
  if (!file) {
    setStatus("请先选择 EPUB 文件。", true);
    return;
  }
  if (!file.name.toLowerCase().endsWith(".epub")) {
    setStatus("书库只接受 EPUB。PDF 离线转换准确率偏低；如需救急，可先用 python3 -m tools.pdf_to_epub_ocr 转成 EPUB 后人工检查。", true);
    return;
  }
  setBusyStatus(`正在上传并解析 ${file.name}...`);
  els.uploadBookBtn.disabled = true;
  const form = new FormData();
  form.append("language", els.bookLanguage.value);
  form.append("file", file);
  try {
    const payload = await api("/api/books", { method: "POST", body: form });
    els.bookFile.value = "";
    await refreshLibrary();
    setStatus(`《${payload.book.title}》已导入书库：${payload.book.chapter_count}章 / ${payload.book.paragraph_count}段。`);
  } finally {
    els.uploadBookBtn.disabled = false;
    clearBusyStatus();
  }
}

async function createProject() {
  const zhBookId = Number(els.zhBookSelect.value);
  const enBookId = Number(els.enBookSelect.value);
  if (!zhBookId || !enBookId) {
    setStatus("请先选择一本文字中文书和一本英文书。", true);
    return;
  }
  const payload = await api("/api/projects", {
    method: "POST",
    body: { zh_book_id: zhBookId, en_book_id: enBookId },
  });
  state.mode = "align";
  updateModeUI();
  await refreshLibrary();
  await loadProject(payload.project.id);
  setStatus("项目已创建。建议先进入校对模式，生成章节配对。");
}

async function deleteCurrentProject() {
  if (!state.currentProjectId || !state.currentProject) {
    return;
  }
  const project = state.currentProject.project;
  const confirmed = window.confirm(`确定删除项目 #${project.id} 吗？\n这会删除该项目的章节配对、段落对齐和人工固定对应，但不会删除书库里的书籍源文件。`);
  if (!confirmed) {
    return;
  }
  await api(`/api/projects/${state.currentProjectId}`, { method: "DELETE" });
  const deletedId = state.currentProjectId;
  state.currentProjectId = null;
  state.currentProject = null;
  state.chapters = [];
  state.mappings = [];
  state.jobs = [];
  state.currentReader = null;
  state.currentAlignment = null;
  state.currentAnchors = [];
  state.enChapterOptions = [];
  state.pendingZhAnchor = null;
  await refreshLibrary();
  renderProjectSummary();
  renderChapterList();
  renderMappingTable();
  renderJobs();
  renderReader();
  renderAnchors();
  renderReviews();
  updateModeUI();
  setStatus(`项目 #${deletedId} 已删除，书库中的书籍已保留。`);
}

async function deleteBook(bookId) {
  const book = state.books.find((item) => Number(item.id) === Number(bookId));
  if (!book) {
    return;
  }
  const relatedProjects = state.projects.filter(
    (project) => Number(project.zh_book_id) === Number(bookId) || Number(project.en_book_id) === Number(bookId)
  );
  const projectWarning = relatedProjects.length
    ? `\n\n这本书正在被 ${relatedProjects.length} 个项目使用；删除书籍会同时删除这些项目的章节配对、段落对齐和人工固定对应。`
    : "";
  const confirmed = window.confirm(`确定从书库删除《${book.title}》吗？\n源文件和解析缓存都会删除。${projectWarning}`);
  if (!confirmed) {
    return;
  }
  const payload = await api(`/api/books/${bookId}`, { method: "DELETE" });
  const deletedProjects = new Set((payload.deleted_project_ids || []).map((id) => Number(id)));
  if (deletedProjects.has(Number(state.currentProjectId))) {
    state.currentProjectId = null;
    state.currentProject = null;
    state.chapters = [];
    state.mappings = [];
    state.jobs = [];
    state.currentReader = null;
    state.currentAlignment = null;
    state.currentAnchors = [];
    state.enChapterOptions = [];
    state.pendingZhAnchor = null;
    state.activeZhIndex = null;
    state.activeEnRange = null;
    setLookupOpen(false);
  }
  await refreshLibrary();
  renderProjectSummary();
  renderChapterList();
  renderMappingTable();
  renderJobs();
  renderReader();
  renderAnchors();
  renderReviews();
  updateModeUI();
  const suffix = deletedProjects.size ? `，同时删除 ${deletedProjects.size} 个关联项目。` : "。";
  setStatus(`书籍《${book.title}》已从书库删除${suffix}`);
}

async function suggestMapping() {
  if (!state.currentProjectId) {
    return;
  }
  state.mappingCollapsed = false;
  startMappingProgress();
  els.suggestMappingBtn.disabled = true;
  try {
    const payload = await api(`/api/projects/${state.currentProjectId}/chapter-mapping/suggest?allow_llm=true`, {
      method: "POST",
    });
    state.mappings = payload.mappings || [];
    await loadProject(state.currentProjectId);
    if (payload.strategy === "fallback") {
      finishMappingProgress("AI 不可用，已改用规则生成章节配对。");
      setStatus(`章节配对已生成，但当前使用规则兜底：${payload.fallback_reason || "原因未知"}`, true);
    } else {
      finishMappingProgress("AI 章节配对建议已完成。");
      setStatus("章节配对建议已生成。");
    }
  } catch (error) {
    finishMappingProgress("章节配对建议生成失败。");
    throw error;
  } finally {
    els.suggestMappingBtn.disabled = false;
  }
}

async function saveMapping() {
  if (!state.currentProjectId) {
    return;
  }
  state.mappingCollapsed = false;
  await api(`/api/projects/${state.currentProjectId}/chapter-mapping`, {
    method: "PUT",
    body: {
      mappings: state.mappings.map((item) => ({
        zh_chapter_index: item.zh_chapter_index,
        en_chapter_index: item.en_chapter_index,
        source: item.source || "manual",
        confidence: item.confidence,
        reason: item.reason || "",
        alternatives: item.alternatives || [],
        confirmed: false,
      })),
    },
  });
  await loadProject(state.currentProjectId);
  setStatus("章节配对草稿已保存。");
}

async function confirmMapping() {
  if (!state.currentProjectId) {
    return;
  }
  await api(`/api/projects/${state.currentProjectId}/chapter-mapping/confirm`, { method: "POST" });
  await loadProject(state.currentProjectId);
  setStatus("章节配对已锁定。");
}

async function alignCurrentChapter(force = false) {
  if (!state.currentProjectId) {
    return;
  }
  startAlignProgress(force);
  setAlignBusy(true);
  try {
    const selectedPolicy = els.llmPolicySelect?.value || "auto";
    const llmPolicy = force ? "force" : selectedPolicy;
    const payload = await api(`/api/projects/${state.currentProjectId}/chapters/${state.currentChapterIndex}/${force ? "regenerate" : "align"}`, {
      method: "POST",
      body: { force, use_anchors: true, allow_llm: llmPolicy !== "off", llm_policy: llmPolicy },
    });
    state.currentAlignment = payload;
    await loadProject(state.currentProjectId);
    finishAlignProgress(force ? "本章已重新对齐。" : "本章段落已对齐。");
    setStatus(force ? "本章已重新对齐。" : "本章段落已对齐。");
  } catch (error) {
    finishAlignProgress(force ? "重新对齐失败。" : "段落对齐失败。");
    throw error;
  } finally {
    setAlignBusy(false);
  }
}

async function confirmCurrentChapter() {
  if (!state.currentProjectId) {
    return;
  }
  await api(`/api/projects/${state.currentProjectId}/chapters/${state.currentChapterIndex}/confirm`, { method: "POST" });
  await loadProject(state.currentProjectId);
  setStatus("本章对齐结果已确认。");
}

async function skipCurrentChapter() {
  if (!state.currentProjectId) {
    return;
  }
  await api(`/api/projects/${state.currentProjectId}/chapters/${state.currentChapterIndex}/skip`, { method: "POST" });
  await loadProject(state.currentProjectId);
  setStatus("本章已标记为跳过，并写入近似对应。");
}

async function createAnchorFromDraft() {
  const draft = state.anchorDraft;
  const zhRange = normalizeAnchorRange(draft.zhStart, draft.zhEnd);
  const enRange = normalizeAnchorRange(draft.enStart, draft.enEnd);
  if (!state.currentProjectId || !zhRange || !enRange) {
    return;
  }
  await api(`/api/projects/${state.currentProjectId}/anchors`, {
    method: "POST",
    body: {
      zh_chapter_index: state.currentChapterIndex,
      zh_start: zhRange.start,
      zh_end: zhRange.end,
      en_start: enRange.start,
      en_end: enRange.end,
      kind: "hard",
      confirmed: true,
    },
  });
  state.pendingZhAnchor = null;
  state.anchorDraft = { zhStart: null, zhEnd: null, enStart: null, enEnd: null };
  await loadCurrentChapter();
  setStatus(`已保存固定对应：中 ${formatRangeLabel(zhRange.start, zhRange.end)} ↔ 英 ${formatRangeLabel(enRange.start, enRange.end)}。`);
}

async function reportMismatch() {
  if (!state.currentProjectId || !state.currentReader || state.activeZhIndex === null || !state.activeEnRange) {
    return;
  }
  const range = state.activeEnRange;
  await api(`/api/projects/${state.currentProjectId}/mismatch-reports`, {
    method: "POST",
    body: {
      chapter_index: state.currentChapterIndex,
      zh_start: state.activeZhIndex,
      zh_end: state.activeZhIndex,
      en_start: range.start,
      en_end: range.end,
      cache_key: state.currentAlignment?.cache_key || "",
      note: "reported_from_reader",
    },
  });
  setStatus(`已标记对应有误：中 ${state.activeZhIndex + 1} ↔ 英 ${formatRangeLabel(range.start, range.end)}。`);
}

async function deleteAnchor(anchorId) {
  if (!state.currentProjectId) {
    return;
  }
  await api(`/api/projects/${state.currentProjectId}/anchors/${anchorId}?zh_chapter_index=${state.currentChapterIndex}`, {
    method: "DELETE",
  });
  await loadCurrentChapter();
  setStatus("已删除固定对应。");
}

async function prefetchChapters(alignRemaining = false) {
  if (!state.currentProjectId) {
    return;
  }
  const path = alignRemaining ? "align-remaining" : "prefetch";
  const llmPolicy = els.llmPolicySelect?.value || "auto";
  await api(`/api/projects/${state.currentProjectId}/jobs/${path}`, {
    method: "POST",
    body: {
      chapter_index: state.currentChapterIndex + 1,
      count: 2,
      allow_llm: llmPolicy !== "off",
      llm_policy: llmPolicy,
    },
  });
  const jobsPayload = await api(`/api/projects/${state.currentProjectId}/jobs`);
  state.jobs = jobsPayload.jobs || [];
  renderJobs();
  setStatus(alignRemaining ? "已开始在后台对齐剩余章节。" : "已开始预对齐后续 2 章。");
}

async function exportCurrentProject() {
  if (!state.currentProjectId) {
    return;
  }
  const payload = await api(`/api/projects/${state.currentProjectId}/export`);
  downloadJson(`verso_project_${state.currentProjectId}.json`, payload);
  setStatus("项目快照已导出。");
}

function moveChapter(delta) {
  if (!state.chapters.length) {
    return;
  }
  const nextIndex = Logic.nextChapterIndex
    ? Logic.nextChapterIndex(state.currentChapterIndex, delta, state.chapters.length)
    : state.currentChapterIndex;
  if (nextIndex === state.currentChapterIndex) {
    return;
  }
  state.currentChapterIndex = nextIndex;
  state.activeZhIndex = null;
  state.activeEnRange = null;
  setLookupOpen(false);
  renderChapterList();
  loadCurrentChapter();
}

els.refreshLibraryBtn.addEventListener("click", async () => {
  try {
    await refreshLibrary();
    setStatus("书库与项目列表已刷新。");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "刷新失败。", true);
  }
});

els.libraryToggleBtn.addEventListener("click", () => {
  state.isLibraryOpen = !state.isLibraryOpen;
  updateLibraryUI();
});

els.exportProjectBtn.addEventListener("click", () => {
  exportCurrentProject().catch((error) => setStatus(error instanceof Error ? error.message : "导出失败。", true));
});

els.deleteProjectBtn.addEventListener("click", () => {
  deleteCurrentProject().catch((error) => setStatus(error instanceof Error ? error.message : "删除项目失败。", true));
});

els.uploadBookBtn.addEventListener("click", () => {
  uploadBook().catch((error) => setStatus(error instanceof Error ? error.message : "上传失败。", true));
});

els.createProjectBtn.addEventListener("click", () => {
  createProject().catch((error) => setStatus(error instanceof Error ? error.message : "创建项目失败。", true));
});

els.projectList.addEventListener("click", (event) => {
  const target = event.target.closest("[data-project-id]");
  if (!target) {
    return;
  }
  loadProject(Number(target.dataset.projectId)).catch((error) => {
    setStatus(error instanceof Error ? error.message : "加载项目失败。", true);
  });
});

els.bookList.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-book-delete-id]");
  if (!btn) {
    return;
  }
  deleteBook(Number(btn.dataset.bookDeleteId)).catch((error) => {
    setStatus(error instanceof Error ? error.message : "删除书籍失败。", true);
  });
});

els.chapterList.addEventListener("click", (event) => {
  const target = event.target.closest("[data-chapter-index]");
  if (!target) {
    return;
  }
  state.currentChapterIndex = Number(target.dataset.chapterIndex);
  renderChapterList();
  loadCurrentChapter();
});

els.modeReadBtn.addEventListener("click", () => {
  state.mode = "read";
  updateModeUI();
  loadCurrentChapter();
});

els.modeAlignBtn.addEventListener("click", () => {
  state.mode = "align";
  updateModeUI();
  loadCurrentChapter();
});

els.prevChapterBtn.addEventListener("click", () => moveChapter(-1));
els.nextChapterBtn.addEventListener("click", () => moveChapter(1));
els.prefetchBtn.addEventListener("click", () => {
  prefetchChapters(false).catch((error) => setStatus(error instanceof Error ? error.message : "预对齐失败。", true));
});
els.alignRemainingBtn.addEventListener("click", () => {
  prefetchChapters(true).catch((error) => setStatus(error instanceof Error ? error.message : "对齐剩余章节失败。", true));
});
els.suggestMappingBtn.addEventListener("click", () => {
  suggestMapping().catch((error) => setStatus(error instanceof Error ? error.message : "生成章节配对失败。", true));
});
els.saveMappingBtn.addEventListener("click", () => {
  saveMapping().catch((error) => setStatus(error instanceof Error ? error.message : "保存章节配对失败。", true));
});
els.confirmMappingBtn.addEventListener("click", () => {
  confirmMapping().catch((error) => setStatus(error instanceof Error ? error.message : "锁定章节配对失败。", true));
});
els.mappingToggleBtn.addEventListener("click", () => {
  if (!isMappingConfirmed()) {
    return;
  }
  state.mappingCollapsed = !state.mappingCollapsed;
  updateMappingPanelUI();
});
els.mappingCollapsedExpandBtn.addEventListener("click", () => {
  state.mappingCollapsed = false;
  updateMappingPanelUI();
});
els.alignChapterBtn.addEventListener("click", () => {
  alignCurrentChapter(false).catch((error) => setStatus(error instanceof Error ? error.message : "本章段落对齐失败。", true));
});
els.confirmChapterBtn.addEventListener("click", () => {
  confirmCurrentChapter().catch((error) => setStatus(error instanceof Error ? error.message : "确认本章结果失败。", true));
});
els.skipChapterBtn.addEventListener("click", () => {
  skipCurrentChapter().catch((error) => setStatus(error instanceof Error ? error.message : "标记本章跳过失败。", true));
});
els.regenerateChapterBtn.addEventListener("click", () => {
  alignCurrentChapter(true).catch((error) => setStatus(error instanceof Error ? error.message : "重新对齐本章失败。", true));
});
els.anchorMode.addEventListener("change", () => {
  resetAnchorDraft();
});

els.anchorFloatToggle?.addEventListener("click", (event) => {
  event.stopPropagation();
  state.anchorFloatCollapsed = !state.anchorFloatCollapsed;
  updateAnchorFloatUI();
});

els.anchorFloat?.addEventListener("click", () => {
  if (!state.anchorFloatCollapsed) {
    return;
  }
  state.anchorFloatCollapsed = false;
  updateAnchorFloatUI();
});

els.createAnchorBtn?.addEventListener("click", () => {
  createAnchorFromDraft().catch((error) => {
    setStatus(error instanceof Error ? error.message : "保存固定对应失败。", true);
  });
});

els.resetAnchorBtn?.addEventListener("click", () => {
  resetAnchorDraft();
});

els.reportMismatchBtn?.addEventListener("click", () => {
  reportMismatch().catch((error) => {
    setStatus(error instanceof Error ? error.message : "标记对应错误失败。", true);
  });
});

els.lookupCloseBtn?.addEventListener("click", () => {
  setLookupOpen(false);
});

els.anchorList.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-anchor-id]");
  if (!btn) {
    return;
  }
  deleteAnchor(Number(btn.dataset.anchorId)).catch((error) => {
    setStatus(error instanceof Error ? error.message : "删除固定对应失败。", true);
  });
});

els.zhScroll.addEventListener("scroll", () => {
  if (!state.isSyncing) {
    window.requestAnimationFrame(syncReader);
  }
});

function handleParagraphClick(event, side) {
  const para = event.target.closest(".para[data-index]");
  if (para && side === "zh" && (!els.anchorMode.checked || state.mode !== "align")) {
    setActivePair(Number(para.dataset.index));
    return;
  }
  if (!para || state.mode !== "align" || !els.anchorMode.checked) {
    return;
  }
  const localIndex = Number(para.dataset.index);
  if (side === "zh") {
    if (state.anchorDraft.zhStart === null || state.anchorDraft.zhEnd !== null) {
      state.anchorDraft = { zhStart: localIndex, zhEnd: null, enStart: null, enEnd: null };
      state.pendingZhAnchor = localIndex;
      state.activeZhIndex = null;
      state.activeEnRange = null;
    } else {
      state.anchorDraft.zhEnd = localIndex;
      const normalized = normalizeAnchorRange(state.anchorDraft.zhStart, state.anchorDraft.zhEnd);
      state.anchorDraft.zhStart = normalized.start;
      state.anchorDraft.zhEnd = normalized.end;
      state.pendingZhAnchor = normalized.start;
      state.activeZhIndex = normalized.start;
      state.activeEnRange = englishRangeForZhSpan(normalized.start, normalized.end);
    }
    updateAnchorHint();
    renderReader();
    return;
  }
  if (state.anchorDraft.zhStart === null || state.anchorDraft.zhEnd === null) {
    setStatus("请先点击左侧中文段落两次，确定固定对应的中文范围。", true);
    return;
  }
  if (state.anchorDraft.enStart === null || state.anchorDraft.enEnd !== null) {
    state.anchorDraft.enStart = localIndex;
    state.anchorDraft.enEnd = null;
  } else {
    state.anchorDraft.enEnd = localIndex;
    const normalized = normalizeAnchorRange(state.anchorDraft.enStart, state.anchorDraft.enEnd);
    state.anchorDraft.enStart = normalized.start;
    state.anchorDraft.enEnd = normalized.end;
  }
  updateAnchorHint();
  renderReader();
}

els.zhScroll.addEventListener("click", (event) => handleParagraphClick(event, "zh"));
els.enScroll?.addEventListener("click", (event) => handleParagraphClick(event, "en"));
els.lookupContent?.addEventListener("click", (event) => handleParagraphClick(event, "en"));
window.addEventListener("resize", updateResponsiveButtonLabels);

refreshLibrary().then(() => {
  renderProjectSummary();
  renderChapterList();
  renderJobs();
  renderReader();
  renderAnchors();
  renderReviews();
  updateModeUI();
  updateLibraryUI();
}).catch((error) => {
  setStatus(error instanceof Error ? error.message : "初始化失败。", true);
});
