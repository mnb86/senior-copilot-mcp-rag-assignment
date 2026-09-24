"""Structure-aware chunking.

Strategy: split on document headings first (one section never mixes two procedures), then pack
paragraphs/sentences into chunks of at most ``max_chars`` with ``overlap_chars`` of trailing context
carried into the next chunk of the same section. Tables and lists stay attached to their heading.
"""

from __future__ import annotations

import re

from rag.models import Chunk, ExtractedDocument
from rag.security import redact_injection

DEFAULT_MAX_CHARS = 900
DEFAULT_OVERLAP_CHARS = 150


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "section"


def _units(text: str) -> list[str]:
    """Paragraphs, further split into sentences when a paragraph is too long."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= DEFAULT_MAX_CHARS:
            units.append(para)
        else:
            units.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+|\n(?=\d+\.|- |\|)", para) if s.strip())
    return units


def split_text(text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap_chars: int = DEFAULT_OVERLAP_CHARS) -> list[str]:
    if max_chars <= overlap_chars:
        raise ValueError("max_chars must be greater than overlap_chars")
    chunks: list[str] = []
    cur = ""
    for unit in _units(text):
        while len(unit) > max_chars:  # hard split of pathological long units
            head, unit = unit[:max_chars], unit[max_chars - overlap_chars :]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        candidate = f"{cur}\n\n{unit}" if cur else unit
        if len(candidate) <= max_chars:
            cur = candidate
        else:
            chunks.append(cur)
            tail = cur[-overlap_chars:]
            tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
            cur = f"{tail} ... {unit}" if overlap_chars else unit
            if len(cur) > max_chars:
                cur = unit
    if cur:
        chunks.append(cur)
    return chunks


def chunk_document(
    doc: ExtractedDocument, max_chars: int = DEFAULT_MAX_CHARS, overlap_chars: int = DEFAULT_OVERLAP_CHARS
) -> list[Chunk]:
    meta = doc.metadata
    chunks: list[Chunk] = []
    ordinal = 0
    for section in doc.sections:
        pieces = split_text(section.text, max_chars, overlap_chars)
        for i, piece in enumerate(pieces):
            clean, patterns = redact_injection(piece)
            ordinal += 1
            suffix = f"-{i + 1}" if len(pieces) > 1 else ""
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}#{_slug(section.heading)}{suffix}",
                    doc_id=doc.doc_id,
                    title=doc.title,
                    doc_type=doc.doc_type,
                    section=section.heading,
                    text=clean if patterns else piece,
                    ordinal=ordinal,
                    source_path=doc.source_path,
                    revision=meta.get("revision"),
                    effective_date=meta.get("effective_date"),
                    site=str(meta.get("site", "ALL")),
                    asset_types=list(meta.get("asset_types", [])),
                    asset_ids=list(meta.get("asset_ids", [])),
                    alarm_names=list(meta.get("alarm_names", [])),
                    trust_level=str(meta.get("trust_level", "controlled")),
                    injection_suspected=bool(patterns),
                    injection_patterns=patterns,
                )
            )
    return chunks
