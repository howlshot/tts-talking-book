"""Source text in, a tree of divisions out.

Navigation follows NLS QA201801: headings come from the body text, not the
table of contents, and textual divisions inside a chapter ("Section 2.") are
navigable even when the table of contents never lists them.
"""
from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass
class Division:
    heading: str
    cls: str  # navPoint class from NLS Spec 1203 Appendix A, Table 1
    paragraphs: list[str] = field(default_factory=list)
    children: list["Division"] = field(default_factory=list)


@dataclass
class Book:
    title: str
    author: str
    divisions: list[Division]
    language: str = "en"
    source_date: str = ""


BLOCK = re.compile(r"<(h[1-6]|p)\b[^>]*>(.*?)</\1>", re.S | re.I)
INLINE_SECTION = re.compile(r"^(Section\.?\s*\d+)\s*\.?\s+(.*)$", re.S)


def clean(fragment: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)  # tag removal can leave "Section 1 ."


def _spine_documents(epub: zipfile.ZipFile) -> list[str]:
    container = ET.fromstring(epub.read("META-INF/container.xml"))
    opf_path = next(el.get("full-path") for el in container.iter() if el.tag.endswith("rootfile"))
    opf = ET.fromstring(epub.read(opf_path))
    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    items = {el.get("id"): el.get("href") for el in opf.iter() if el.tag.endswith("item")}
    return [base + items[ref.get("idref")] for ref in opf.iter() if ref.tag.endswith("itemref")]


def read_epub(path: str | Path, start: str | None = None, stop: str | None = None) -> list[tuple[str, str]]:
    """(tag, text) blocks in reading order. start/stop trim front and back matter by text."""
    blocks: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as epub:
        for doc in _spine_documents(epub):
            markup = epub.read(doc).decode("utf-8", errors="replace")
            blocks += [(tag.lower(), clean(body)) for tag, body in BLOCK.findall(markup)]
    blocks = [b for b in blocks if b[1]]
    if start:
        blocks = blocks[next(i for i, b in enumerate(blocks) if start.lower() in b[1].lower()) :]
    if stop:
        blocks = blocks[: next((i for i, b in enumerate(blocks) if stop.lower() in b[1].lower()), len(blocks))]
    return blocks


def build_divisions(blocks: list[tuple[str, str]], preliminary_heading: str = "Preamble") -> tuple[str, list[Division]]:
    """h1 is the title; text before the first h2 is front matter; h2s are chapters;
    paragraphs that open with "Section N." start nested sections."""
    title = next((text for tag, text in blocks if tag == "h1"), "")
    divisions: list[Division] = []
    front = Division(preliminary_heading, "prelimitem")
    current: Division | None = None
    for tag, text in blocks:
        if tag == "h1":
            continue
        if tag in ("h2", "h3"):
            current = Division(text.rstrip("."), "chapter")
            divisions.append(current)
            continue
        if current is None:
            front.paragraphs.append(text)
            continue
        m = INLINE_SECTION.match(text)
        if m:
            current.children.append(Division(" ".join(m.group(1).replace(".", " ").split()), "section", [m.group(2)]))
        elif current.children:
            current.children[-1].paragraphs.append(text)
        else:
            current.paragraphs.append(text)
    return title, ([front] if front.paragraphs else []) + divisions


def walk(divisions: list[Division], depth: int = 1):
    for d in divisions:
        yield d, depth
        yield from walk(d.children, depth + 1)
