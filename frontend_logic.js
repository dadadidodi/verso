(function initFrontendLogic(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.DuReadingFrontendLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function frontendLogicFactory() {
  function buildInitialMappings(chapters, rawMappings, enChapterCount) {
    return chapters.map((chapter, index) => {
      const existing = rawMappings.find((item) => item.zh_chapter_index === chapter.zh_chapter_index);
      if (existing) {
        return existing;
      }
      return {
        zh_chapter_index: chapter.zh_chapter_index,
        en_chapter_index:
          chapter.mapped_en_chapter_index ?? Math.min(index, Math.max(0, enChapterCount - 1)),
        source: "manual",
        confidence: null,
        reason: "",
        alternatives: [],
        confirmed: false,
      };
    });
  }

  function upsertMapping(mappings, chapterIndex, enIndex) {
    let found = false;
    const next = mappings.map((item) => {
      if (item.zh_chapter_index !== chapterIndex) {
        return item;
      }
      found = true;
      return {
        ...item,
        en_chapter_index: enIndex,
        source: "manual",
        reason: "manual_override",
        confidence: null,
      };
    });
    if (!found) {
      next.push({
        zh_chapter_index: chapterIndex,
        en_chapter_index: enIndex,
        source: "manual",
        confidence: null,
        reason: "manual_override",
        alternatives: [],
        confirmed: false,
      });
    }
    return next;
  }

  function mostVisibleIndex(offsets, scrollTop, clientHeight) {
    if (!offsets.length) {
      return 0;
    }
    const probe = scrollTop + clientHeight * 0.25;
    let answer = 0;
    for (let index = 0; index < offsets.length; index += 1) {
      if (offsets[index] <= probe) {
        answer = index;
      } else {
        break;
      }
    }
    return Math.max(0, Math.min(offsets.length - 1, answer));
  }

  function buildReverseMap(syncMap) {
    const reverse = new Map();
    syncMap.forEach((enIdx, zhIdx) => {
      if (!reverse.has(enIdx)) {
        reverse.set(enIdx, zhIdx);
      }
    });
    return reverse;
  }

  function nextChapterIndex(currentIndex, delta, total) {
    if (total <= 0) {
      return 0;
    }
    return Math.max(0, Math.min(total - 1, currentIndex + delta));
  }

  function anchorHint(mode, anchorModeEnabled, pendingZhAnchor) {
    if (mode !== "align") {
      return "Read mode 中不编辑 anchor。";
    }
    if (!anchorModeEnabled) {
      return "开启后点选连续中文段，再在右侧原文框点选连续英文段。";
    }
    if (pendingZhAnchor === null || pendingZhAnchor === undefined) {
      return "请选择中文起始段。";
    }
    return `已选中文第 ${pendingZhAnchor + 1} 段，请再次点击中文段确定范围。`;
  }

  function syncTargetIndex(syncMap, zhOffsets, scrollTop, clientHeight, reverseMap) {
    const zhIndex = mostVisibleIndex(zhOffsets, scrollTop, clientHeight);
    const enIndex = Number(syncMap[zhIndex] ?? 0);
    const resolved = reverseMap && reverseMap.has(enIndex) ? reverseMap.get(enIndex) : enIndex;
    return {
      zhIndex,
      enIndex,
      enTarget: resolved,
    };
  }

  function englishRangeForZh(enRangesByZh, zhIndex, fallbackSyncMap) {
    const raw = Array.isArray(enRangesByZh) ? enRangesByZh[zhIndex] : null;
    if (Array.isArray(raw) && raw.length >= 2) {
      const start = Number(raw[0] ?? 0);
      const end = Number(raw[1] ?? start);
      return {
        start: Math.max(0, Math.min(start, end)),
        end: Math.max(start, end),
      };
    }
    const fallback = Number((fallbackSyncMap || [])[zhIndex] ?? 0);
    return { start: fallback, end: fallback };
  }

  function englishIndicesForZh(enRangesByZh, zhIndex, fallbackSyncMap) {
    const range = englishRangeForZh(enRangesByZh, zhIndex, fallbackSyncMap);
    const out = [];
    for (let index = range.start; index <= range.end; index += 1) {
      out.push(index);
    }
    return out;
  }

  function formatEnglishRangeLabel(range) {
    const start = Number(range?.start ?? 0) + 1;
    const end = Number(range?.end ?? start - 1) + 1;
    return start === end ? `EN ${start}` : `EN ${start}-${end}`;
  }

  function englishContextWindow(enLength, range, before = 1, after = 1) {
    if (!range || enLength <= 0) {
      return { start: 0, end: -1 };
    }
    const rangeStart = Math.max(0, Math.min(enLength - 1, Number(range.start ?? 0)));
    const rangeEnd = Math.max(rangeStart, Math.min(enLength - 1, Number(range.end ?? rangeStart)));
    const start = Math.max(0, rangeStart - Math.max(0, Number(before) || 0));
    const end = Math.min(enLength - 1, rangeEnd + Math.max(0, Number(after) || 0));
    return { start, end };
  }

  function alignmentSourceLabel(source) {
    const normalized = String(source || "").toLowerCase();
    if (normalized === "lm" || normalized === "llm") {
      return "LM";
    }
    if (normalized === "heuristic") {
      return "heuristic";
    }
    if (normalized === "mixed") {
      return "mixed";
    }
    if (normalized === "fallback") {
      return "fallback";
    }
    if (normalized === "skipped") {
      return "skipped";
    }
    return normalized || "unknown";
  }

  function alignmentStateLabel(state, source) {
    if (state === "draft") {
      return `draft · ${alignmentSourceLabel(source)}`;
    }
    return state || "missing";
  }

  function decisionSummary(decisionLog) {
    const decisions = Array.isArray(decisionLog) ? decisionLog : [];
    const counts = decisions.reduce((acc, item) => {
      const method = item && item.method ? String(item.method) : "unknown";
      acc[method] = (acc[method] || 0) + 1;
      return acc;
    }, {});
    const parts = [];
    if (counts.llm) {
      parts.push(`${counts.llm} LM`);
    }
    if (counts.heuristic) {
      parts.push(`${counts.heuristic} heuristic`);
    }
    if (counts.hard_anchor) {
      parts.push(`${counts.hard_anchor} anchor`);
    }
    if (counts.empty_gap) {
      parts.push(`${counts.empty_gap} empty`);
    }
    return `${decisions.length} segments${parts.length ? `: ${parts.join(", ")}` : ""}`;
  }

  return {
    buildInitialMappings,
    upsertMapping,
    mostVisibleIndex,
    buildReverseMap,
    nextChapterIndex,
    anchorHint,
    syncTargetIndex,
    englishRangeForZh,
    englishIndicesForZh,
    formatEnglishRangeLabel,
    englishContextWindow,
    alignmentSourceLabel,
    alignmentStateLabel,
    decisionSummary,
  };
});
