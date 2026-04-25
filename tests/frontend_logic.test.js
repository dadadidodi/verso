const test = require("node:test");
const assert = require("node:assert/strict");

const Logic = require("../frontend_logic.js");

test("buildInitialMappings keeps existing mappings and fills missing chapters", () => {
  const chapters = [
    { zh_chapter_index: 0, mapped_en_chapter_index: 0 },
    { zh_chapter_index: 1, mapped_en_chapter_index: 1 },
    { zh_chapter_index: 2, mapped_en_chapter_index: 2 },
  ];
  const rawMappings = [
    { zh_chapter_index: 1, en_chapter_index: 4, source: "manual", confidence: null, reason: "", alternatives: [], confirmed: false },
  ];
  const mappings = Logic.buildInitialMappings(chapters, rawMappings, 6);
  assert.equal(mappings.length, 3);
  assert.equal(mappings[1].en_chapter_index, 4);
  assert.equal(mappings[0].en_chapter_index, 0);
  assert.equal(mappings[2].en_chapter_index, 2);
});

test("upsertMapping updates an existing row and marks it manual", () => {
  const mappings = [
    { zh_chapter_index: 0, en_chapter_index: 0, source: "heuristic", confidence: 0.8, reason: "dp", alternatives: [], confirmed: false },
  ];
  const next = Logic.upsertMapping(mappings, 0, 3);
  assert.equal(next.length, 1);
  assert.equal(next[0].en_chapter_index, 3);
  assert.equal(next[0].source, "manual");
  assert.equal(next[0].reason, "manual_override");
  assert.equal(next[0].confidence, null);
});

test("mostVisibleIndex uses the scroll probe and clamps output", () => {
  const offsets = [0, 120, 240, 360];
  assert.equal(Logic.mostVisibleIndex(offsets, 0, 400), 0);
  assert.equal(Logic.mostVisibleIndex(offsets, 130, 400), 1);
  assert.equal(Logic.mostVisibleIndex(offsets, 500, 400), 3);
});

test("buildReverseMap keeps the first chinese row for each english index", () => {
  const reverse = Logic.buildReverseMap([0, 0, 1, 2, 2]);
  assert.equal(reverse.get(0), 0);
  assert.equal(reverse.get(1), 2);
  assert.equal(reverse.get(2), 3);
});

test("nextChapterIndex stays inside bounds", () => {
  assert.equal(Logic.nextChapterIndex(0, -1, 5), 0);
  assert.equal(Logic.nextChapterIndex(2, 1, 5), 3);
  assert.equal(Logic.nextChapterIndex(4, 1, 5), 4);
});

test("anchorHint reflects read mode, empty align mode, and pending zh anchor", () => {
  assert.equal(Logic.anchorHint("read", false, null), "Read mode 中不编辑 anchor。");
  assert.equal(Logic.anchorHint("align", false, null), "开启后点选连续中文段，再在右侧原文框点选连续英文段。");
  assert.equal(Logic.anchorHint("align", true, null), "请选择中文起始段。");
  assert.equal(Logic.anchorHint("align", true, 2), "已选中文第 3 段，请再次点击中文段确定范围。");
});

test("syncTargetIndex resolves english target using reverse map", () => {
  const reverse = Logic.buildReverseMap([0, 0, 1, 2, 2]);
  const target = Logic.syncTargetIndex([0, 0, 1, 2, 2], [0, 120, 240, 360, 480], 250, 400, reverse);
  assert.equal(target.zhIndex, 2);
  assert.equal(target.enIndex, 1);
  assert.equal(target.enTarget, 2);
});

test("englishRangeForZh returns full range and falls back to sync map", () => {
  assert.deepEqual(Logic.englishRangeForZh([[0, 1], [2, 4]], 1, [0, 2]), { start: 2, end: 4 });
  assert.deepEqual(Logic.englishRangeForZh([], 0, [3]), { start: 3, end: 3 });
});

test("englishIndicesForZh expands multi-paragraph english blocks", () => {
  assert.deepEqual(Logic.englishIndicesForZh([[11, 12]], 0, []), [11, 12]);
  assert.deepEqual(Logic.englishIndicesForZh([], 0, [5]), [5]);
});

test("formatEnglishRangeLabel keeps single and range labels compact", () => {
  assert.equal(Logic.formatEnglishRangeLabel({ start: 11, end: 12 }), "EN 12-13");
  assert.equal(Logic.formatEnglishRangeLabel({ start: 4, end: 4 }), "EN 5");
});

test("englishContextWindow shows matched block with one neighbor on each side", () => {
  assert.deepEqual(Logic.englishContextWindow(20, { start: 11, end: 12 }), { start: 10, end: 13 });
  assert.deepEqual(Logic.englishContextWindow(5, { start: 0, end: 1 }), { start: 0, end: 2 });
  assert.deepEqual(Logic.englishContextWindow(20, { start: 18, end: 19 }), { start: 17, end: 19 });
});

test("alignment labels keep draft source compact", () => {
  assert.equal(Logic.alignmentSourceLabel("lm"), "LM");
  assert.equal(Logic.alignmentStateLabel("draft", "mixed"), "draft · mixed");
  assert.equal(Logic.alignmentStateLabel("confirmed", "lm"), "confirmed");
});

test("decisionSummary counts segment methods", () => {
  assert.equal(
    Logic.decisionSummary([
      { method: "llm" },
      { method: "heuristic" },
      { method: "heuristic" },
      { method: "hard_anchor" },
    ]),
    "4 segments: 1 LM, 2 heuristic, 1 anchor",
  );
});
