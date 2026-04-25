from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chapter_catalog import extract_epub_document_from_bytes, extract_paragraphs_from_html_text  # noqa: E402


def test_extract_paragraphs_excludes_epub_footnotes_and_noterefs() -> None:
    html = """
    <section>
      <aside epub:type="footnote" id="footnote-5-9">
        <ol class="duokan-footnote-content">
          <li class="duokan-footnote-item">Sir Humphry Davy（1778—1829），英国科学家。</li>
        </ol>
      </aside>
      <p>“韩弗利·戴维爵士
        <sup><a epub:type="noteref" href="#footnote-5-9">
          <img alt="Sir Humphry Davy（1778—1829），英国科学家。" zy-footnote="Sir Humphry Davy（1778—1829），英国科学家。"/>
        </a></sup>吗？”布鲁克边喝汤边说。</p>
    </section>
    """

    paragraphs = extract_paragraphs_from_html_text(html)

    assert paragraphs == ["“韩弗利·戴维爵士 吗？”布鲁克边喝汤边说。"]
    assert not any("1778" in paragraph for paragraph in paragraphs)
    assert not any("英国科学家" in paragraph for paragraph in paragraphs)


def test_middlemarch_second_chapter_does_not_extract_literary_notes_as_body() -> None:
    paragraphs, chapters = extract_epub_document_from_bytes((REPO_ROOT / "data" / "CnMiddlemarch.epub").read_bytes())
    second_chapter = next(chapter for chapter in chapters if chapter.title == "第二章")
    chapter_paragraphs = paragraphs[second_chapter.start : second_chapter.end + 1]

    assert any("韩弗利·戴维爵士" in paragraph and "卡特莱特" in paragraph for paragraph in chapter_paragraphs)
    assert not any(paragraph.startswith("Sir Humphry Davy（1778—1829）") for paragraph in chapter_paragraphs)
    assert not any(paragraph.startswith("John Cartwright（1740—1824）") for paragraph in chapter_paragraphs)
    assert not any(paragraph.startswith("William Wordsworth（1770—1850）") for paragraph in chapter_paragraphs)
