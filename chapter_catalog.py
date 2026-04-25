from __future__ import annotations

import html
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterator, List, Optional, Tuple

from alignment_common import norm_space


NS_CONTAINER = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
NS_OPF = {"opf": "http://www.idpf.org/2007/opf"}
NS_NCX = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
PARSER_VERSION = "footnote_filter_v1"


@dataclass
class Chapter:
    title: str
    path: str


@dataclass
class ChapterSegment:
    title: str
    path: str
    start: int
    end: int


@dataclass
class ManifestItem:
    href: str
    media_type: str
    properties: str


def resolve_path(base_file: str, href: str) -> str:
    base_dir = PurePosixPath(base_file).parent
    target = base_dir.joinpath(href)
    parts: List[str] = []
    for seg in target.parts:
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def parse_xml(data: bytes) -> Optional[ET.Element]:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def extract_opf_path(zf: zipfile.ZipFile) -> str:
    root = parse_xml(zf.read("META-INF/container.xml"))
    if root is None:
        raise ValueError("container.xml 解析失败")
    node = root.find(".//c:rootfile", NS_CONTAINER)
    if node is None:
        raise ValueError("container.xml 缺少 rootfile")
    opf_path = node.attrib.get("full-path", "").strip()
    if not opf_path:
        raise ValueError("未找到 OPF full-path")
    return opf_path


def read_opf(zf: zipfile.ZipFile, opf_path: str) -> Tuple[Dict[str, ManifestItem], List[str]]:
    root = parse_xml(zf.read(opf_path))
    if root is None:
        raise ValueError("OPF 解析失败")

    manifest: Dict[str, ManifestItem] = {}
    for item in root.findall(".//opf:manifest/opf:item", NS_OPF):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if not item_id or not href:
            continue
        manifest[item_id] = ManifestItem(
            href=href,
            media_type=item.attrib.get("media-type", ""),
            properties=item.attrib.get("properties", ""),
        )

    spine: List[str] = []
    for itemref in root.findall(".//opf:spine/opf:itemref", NS_OPF):
        idref = itemref.attrib.get("idref")
        if idref:
            spine.append(idref)
    return manifest, spine


def extract_nav_map(zf: zipfile.ZipFile, opf_path: str, manifest: Dict[str, ManifestItem]) -> Dict[str, str]:
    nav_item = None
    for item in manifest.values():
        props = set(norm_space(item.properties).split(" ")) if item.properties else set()
        if "nav" in props:
            nav_item = item
            break
    if nav_item is None:
        return {}

    nav_path = resolve_path(opf_path, nav_item.href)
    try:
        raw = zf.read(nav_path)
    except KeyError:
        return {}

    text = raw.decode("utf-8", errors="ignore")
    anchors = re.findall(r"<a[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", text, flags=re.I | re.S)
    result: Dict[str, str] = {}
    for href, label_html in anchors:
        clean = norm_space(html.unescape(re.sub(r"<[^>]+>", " ", label_html)))
        if not clean:
            continue
        path = resolve_path(nav_path, href.split("#")[0])
        if path:
            result[path] = clean
    return result


def extract_ncx_map(zf: zipfile.ZipFile, opf_path: str, manifest: Dict[str, ManifestItem]) -> Dict[str, str]:
    ncx_item = None
    for item in manifest.values():
        if item.media_type == "application/x-dtbncx+xml":
            ncx_item = item
            break
    if ncx_item is None:
        return {}
    ncx_path = resolve_path(opf_path, ncx_item.href)
    try:
        raw = zf.read(ncx_path)
    except KeyError:
        return {}

    root = parse_xml(raw)
    if root is None:
        return {}

    result: Dict[str, str] = {}
    for point in root.findall(".//ncx:navPoint", NS_NCX):
        label = point.findtext("./ncx:navLabel/ncx:text", default="", namespaces=NS_NCX)
        content = point.find("./ncx:content", NS_NCX)
        src = "" if content is None else content.attrib.get("src", "")
        clean = norm_space(label)
        if not clean or not src:
            continue
        path = resolve_path(ncx_path, src.split("#")[0])
        if path:
            result[path] = clean
    return result


def extract_heading_fallback(zf: zipfile.ZipFile, path: str) -> str:
    try:
        raw = zf.read(path)
    except KeyError:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    m = re.search(r"<(h1|h2|h3|title)[^>]*>(.*?)</\1>", text, flags=re.I | re.S)
    if not m:
        return ""
    return norm_space(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))))


def strip_epub_notes(html_text: str) -> str:
    """Remove EPUB note bodies and inline note references from the reading text."""

    cleaned = re.sub(r"<(script|style|noscript|svg|math)[^>]*>.*?</\1>", " ", html_text, flags=re.I | re.S)
    cleaned = re.sub(
        r"<aside\b[^>]*(?:epub:type=['\"][^'\"]*footnote|class=['\"][^'\"]*(?:footnote|duokan-footnote)[^'\"]*)[^>]*>.*?</aside>",
        " ",
        cleaned,
        flags=re.I | re.S,
    )
    cleaned = re.sub(
        r"<(section|div)\b[^>]*(?:epub:type=['\"][^'\"]*footnote|class=['\"][^'\"]*(?:footnote|duokan-footnote)[^'\"]*)[^>]*>.*?</\1>",
        " ",
        cleaned,
        flags=re.I | re.S,
    )

    def strip_note_ref(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r"epub:type=['\"][^'\"]*noteref|zy-footnote=|href=['\"][^'\"]*(?:#footnote|notes?\.xhtml)", tag, re.I):
            return " "
        return tag

    cleaned = re.sub(r"<sup\b[^>]*>.*?</sup>", strip_note_ref, cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<a\b[^>]*epub:type=['\"][^'\"]*noteref[^>]*>.*?</a>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<img\b[^>]*(?:zy-footnote=|class=['\"][^'\"]*footnote)[^>]*>", " ", cleaned, flags=re.I | re.S)
    return cleaned


def extract_paragraphs_from_html_text(html_text: str) -> List[str]:
    cleaned = strip_epub_notes(html_text)
    blocks = re.findall(r"<(p|li|blockquote|h1|h2|h3|h4|h5|h6)[^>]*>(.*?)</\1>", cleaned, flags=re.I | re.S)
    paragraphs: List[str] = []
    for _, inner in blocks:
        text = norm_space(html.unescape(re.sub(r"<[^>]+>", " ", inner)))
        if len(text) >= 2:
            paragraphs.append(text)
    if paragraphs:
        return paragraphs

    fallback = norm_space(html.unescape(re.sub(r"<[^>]+>", " ", cleaned)))
    if not fallback:
        return []
    return [part for part in re.split(r"\n\s*\n", fallback) if norm_space(part)]


def extract_epub_document(epub_path: str) -> Tuple[List[str], List[ChapterSegment]]:
    with zipfile.ZipFile(epub_path, "r") as zf:
        return extract_epub_document_from_zip(zf)


def extract_epub_document_from_bytes(data: bytes) -> Tuple[List[str], List[ChapterSegment]]:
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        return extract_epub_document_from_zip(zf)


def iter_spine_html_parts(zf: zipfile.ZipFile) -> Iterator[Tuple[str, str, str]]:
    """按 spine 顺序产出每个 HTML 文档：(zip 内路径, 解码后的 HTML 文本, 章节标题)。"""
    opf_path = extract_opf_path(zf)
    manifest, spine = read_opf(zf, opf_path)
    if not spine:
        raise ValueError("spine 为空，无法提取正文")

    nav_map = extract_nav_map(zf, opf_path, manifest)
    ncx_map = extract_ncx_map(zf, opf_path, manifest)
    toc_map = nav_map if nav_map else ncx_map

    for i, spine_id in enumerate(spine, start=1):
        item = manifest.get(spine_id)
        if item is None:
            continue
        media = item.media_type.lower()
        href = item.href.lower()
        is_html_like = ("html" in media) or href.endswith(".html") or href.endswith(".xhtml")
        if not is_html_like:
            continue

        content_path = resolve_path(opf_path, item.href)
        try:
            raw = zf.read(content_path)
        except KeyError:
            continue
        html_text = raw.decode("utf-8", errors="ignore")
        title = toc_map.get(content_path) or extract_heading_fallback(zf, content_path) or f"Chapter {i}"
        yield content_path, html_text, title


def extract_epub_document_from_zip(zf: zipfile.ZipFile) -> Tuple[List[str], List[ChapterSegment]]:
    paragraphs: List[str] = []
    chapters: List[ChapterSegment] = []
    for content_path, html_text, title in iter_spine_html_parts(zf):
        chapter_paragraphs = extract_paragraphs_from_html_text(html_text)
        if not chapter_paragraphs:
            continue

        start = len(paragraphs)
        paragraphs.extend(chapter_paragraphs)
        end = len(paragraphs) - 1
        chapters.append(ChapterSegment(title=title, path=content_path, start=start, end=end))

    if not chapters and paragraphs:
        chapters.append(ChapterSegment(title="全文", path="", start=0, end=len(paragraphs) - 1))
    return paragraphs, chapters


def extract_chapters(epub_path: str) -> List[Chapter]:
    _, chapters = extract_epub_document(epub_path)
    return [Chapter(title=c.title, path=c.path) for c in chapters]
