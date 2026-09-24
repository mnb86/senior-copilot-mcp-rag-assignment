"""Text extraction for the supported document formats (.md, .txt, .html, .pdf).

Each extractor returns document-level metadata and a list of heading-delimited sections.
Metadata sources: YAML front matter (md), ``KEY: value`` header block (txt), ``<meta>`` tags (html),
sidecar ``<file>.meta.json`` (pdf, or any format as an override).
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from rag.models import ExtractedDocument, Section

SUPPORTED_SUFFIXES = (".md", ".markdown", ".txt", ".html", ".htm", ".pdf")
LIST_FIELDS = ("asset_types", "asset_ids", "alarm_names")
NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\s+([A-Z][^.]{2,80})$")


class ExtractionError(Exception):
    pass


def _normalise_meta(meta: dict[str, Any], path: Path) -> dict[str, Any]:
    out = {str(k).strip().lower(): v for k, v in meta.items()}
    for f in LIST_FIELDS:
        v = out.get(f)
        if v is None:
            out[f] = []
        elif isinstance(v, str):
            out[f] = [x.strip() for x in v.split(",") if x.strip()]
        else:
            out[f] = [str(x) for x in v]
    for k in ("revision", "effective_date"):
        if k in out and out[k] is not None:
            out[k] = str(out[k])
    out.setdefault("doc_id", path.stem.split("-")[0].upper())
    out.setdefault("title", path.stem.replace("-", " ").title())
    out.setdefault("doc_type", "general")
    out.setdefault("site", "ALL")
    out.setdefault("trust_level", "controlled")
    return out


def _split_markdown(body: str) -> list[Section]:
    sections: list[Section] = []
    heading = "Introduction"
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            if "".join(buf).strip():
                sections.append(Section(heading=heading, text="\n".join(buf).strip()))
            buf = []
            heading = m.group(2).strip()
            if len(m.group(1)) == 1:  # document title line
                heading = "Overview"
            continue
        buf.append(line)
    if "".join(buf).strip():
        sections.append(Section(heading=heading, text="\n".join(buf).strip()))
    return sections


def _split_numbered(text: str) -> list[Section]:
    sections: list[Section] = []
    heading = "Introduction"
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        m = NUMBERED_HEADING.match(line)
        if m and len(line) < 90:
            if "".join(buf).strip():
                sections.append(Section(heading=heading, text=_reflow(buf)))
            buf = []
            heading = f"{m.group(1)} {m.group(2)}"
            continue
        buf.append(raw)
    if "".join(buf).strip():
        sections.append(Section(heading=heading, text=_reflow(buf)))
    return sections


def _reflow(lines: list[str]) -> str:
    """Join hard-wrapped lines into paragraphs (blank line = paragraph break)."""
    paras, cur = [], []
    for ln in lines:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


def extract_markdown(path: Path) -> tuple[dict[str, Any], list[Section]]:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        loaded = yaml.safe_load(fm)
        if not isinstance(loaded, dict):
            raise ExtractionError(f"{path.name}: front matter must be a mapping")
        meta = loaded
    else:
        body = text
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if m:
        meta.setdefault("title", m.group(1).strip())
    return meta, _split_markdown(body)


def extract_text(path: Path) -> tuple[dict[str, Any], list[Section]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, Any] = {}
    i = 0
    while i < len(lines) and re.match(r"^[A-Z_]{2,30}:\s", lines[i]):
        k, _, v = lines[i].partition(":")
        meta[k.strip().lower()] = v.strip()
        i += 1
    return meta, _split_numbered("\n".join(lines[i:]))


class _HtmlExtractor(HTMLParser):
    HEADINGS = {"h1", "h2", "h3", "h4"}
    SKIP = {"script", "style", "noscript", "template"}
    BLOCK = {"p", "li", "tr", "div", "br", "td", "th", "ul", "ol", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, Any] = {}
        self.sections: list[Section] = []
        self._heading: str | None = None
        self._in_heading: str | None = None
        self._heading_buf: list[str] = []
        self._buf: list[str] = []
        self._skip = 0
        self._title_buf: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "meta" and (name := a.get("name")) and a.get("content") is not None:
            self.meta[name] = a["content"]
        elif tag == "title":
            self._in_title = True
        elif tag in self.HEADINGS:
            self._flush()
            self._in_heading = tag
            self._heading_buf = []
        elif tag in self.BLOCK:
            self._buf.append("\n")
        if tag == "li":
            self._buf.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == self._in_heading:
            text = " ".join("".join(self._heading_buf).split())
            self._heading = "Overview" if tag == "h1" else text
            if tag == "h1":
                self.meta.setdefault("title", text)
            self._in_heading = None
        elif tag in self.BLOCK:
            self._buf.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        data = data.replace("\n", " ")  # source line wraps are not structure; block tags are
        if self._in_title:
            self._title_buf.append(data)
        elif self._in_heading:
            self._heading_buf.append(data)
        else:
            self._buf.append(data)

    def _flush(self) -> None:
        text = "\n".join(" ".join(ln.split()) for ln in "".join(self._buf).splitlines())
        text = re.sub(r"\n{2,}", "\n", text).strip()
        if text:
            self.sections.append(Section(heading=self._heading or "Introduction", text=text))
        self._buf = []

    def close(self) -> None:
        super().close()
        self._flush()
        if self._title_buf:
            self.meta.setdefault("title", " ".join("".join(self._title_buf).split()))


def extract_html(path: Path) -> tuple[dict[str, Any], list[Section]]:
    p = _HtmlExtractor()
    p.feed(path.read_text(encoding="utf-8"))
    p.close()
    return p.meta, p.sections


def extract_pdf(path: Path) -> tuple[dict[str, Any], list[Section]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise ExtractionError("pypdf is required for PDF extraction") from exc
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    meta: dict[str, Any] = {}
    if reader.metadata and reader.metadata.title:
        meta["title"] = str(reader.metadata.title)
    # drop the title block (first lines before first numbered heading)
    return meta, [s for s in _split_numbered(text) if s.heading != "Introduction"] or _split_numbered(text)


EXTRACTORS = {
    ".md": extract_markdown,
    ".markdown": extract_markdown,
    ".txt": extract_text,
    ".html": extract_html,
    ".htm": extract_html,
    ".pdf": extract_pdf,
}


def extract(path: Path, root: Path | None = None) -> ExtractedDocument:
    suffix = path.suffix.lower()
    if suffix not in EXTRACTORS:
        raise ExtractionError(f"Unsupported document type: {path.name}")
    raw = path.read_bytes()
    meta, sections = EXTRACTORS[suffix](path)
    sidecar = path.with_name(path.name + ".meta.json")
    if sidecar.exists():
        meta = {**meta, **json.loads(sidecar.read_text(encoding="utf-8"))}
    meta = _normalise_meta(meta, path)
    if not sections:
        raise ExtractionError(f"{path.name}: no extractable text")
    rel = str(path.relative_to(root)) if root else path.name
    return ExtractedDocument(
        doc_id=str(meta["doc_id"]),
        title=str(meta["title"]),
        doc_type=str(meta["doc_type"]),
        source_path=rel,
        content_hash=hashlib.sha256(raw).hexdigest(),
        metadata=meta,
        sections=sections,
    )
