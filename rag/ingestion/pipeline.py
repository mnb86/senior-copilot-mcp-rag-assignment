"""Ingestion pipeline: discover -> extract -> chunk -> scan -> index -> persist.

Re-running is idempotent: when the corpus hash (file paths + content hashes + chunking parameters)
matches the existing manifest, the index is left untouched unless ``force`` is set.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag.retrieval.index import RetrievalIndex
from rag.retrieval.models import Chunk

from .chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP_CHARS, chunk_document
from .extractors import SUPPORTED_SUFFIXES, ExtractionError, extract

log = logging.getLogger("rag.ingestion")


@dataclass
class IngestReport:
    documents: int = 0
    chunks: int = 0
    skipped_unchanged: bool = False
    errors: list[str] = field(default_factory=list)
    flagged_chunks: list[str] = field(default_factory=list)
    index_dir: str = ""
    corpus_hash: str = ""
    embedder: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def discover(documents_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in documents_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith(".")
    )


def corpus_hash(paths: list[Path], root: Path, params: dict[str, Any]) -> str:
    h = hashlib.sha256(json.dumps(params, sort_keys=True).encode())
    for p in paths:
        h.update(p.relative_to(root).as_posix().encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
        sidecar = p.with_name(p.name + ".meta.json")
        if sidecar.exists():
            h.update(sidecar.read_bytes())
    return h.hexdigest()


def ingest(
    documents_dir: str | Path,
    index_dir: str | Path,
    *,
    embedder: str = "lsa",
    force: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> IngestReport:
    docs_root, out = Path(documents_dir).resolve(), Path(index_dir)
    if not docs_root.is_dir():
        raise FileNotFoundError(f"Document directory not found: {docs_root}")
    paths = discover(docs_root)
    params = {"embedder": embedder, "max_chars": max_chars, "overlap_chars": overlap_chars, "v": 1}
    digest = corpus_hash(paths, docs_root, params)
    report = IngestReport(index_dir=str(out), corpus_hash=digest, embedder=embedder)

    manifest = out / "manifest.json"
    if not force and manifest.exists():
        try:
            if json.loads(manifest.read_text()).get("corpus_hash") == digest:
                report.skipped_unchanged = True
                existing = json.loads(manifest.read_text())
                report.documents, report.chunks = existing["document_count"], existing["chunk_count"]
                return report
        except (ValueError, KeyError):
            pass

    chunks: list[Chunk] = []
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_docs: set[str] = set()
    for path in paths:
        try:
            doc = extract(path, docs_root)
        except (ExtractionError, ValueError, OSError) as exc:
            report.errors.append(f"{path.name}: {exc}")
            log.warning("extraction failed: %s", exc)
            continue
        if doc.doc_id in seen_docs:
            report.errors.append(f"{path.name}: duplicate doc_id {doc.doc_id} skipped")
            continue
        seen_docs.add(doc.doc_id)
        doc_chunks = chunk_document(doc, max_chars, overlap_chars)
        for c in doc_chunks:
            if c.chunk_id in seen_ids:
                c.chunk_id = f"{c.chunk_id}-{c.ordinal}"
            seen_ids.add(c.chunk_id)
            if c.injection_suspected:
                report.flagged_chunks.append(c.chunk_id)
        chunks.extend(doc_chunks)
        documents.append(
            {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "source_path": doc.source_path,
                "content_hash": doc.content_hash,
                "revision": doc.metadata.get("revision"),
                "chunks": len(doc_chunks),
            }
        )

    index = RetrievalIndex.build(chunks, embedder, digest, documents)
    index.save(out)
    report.documents, report.chunks = len(documents), len(chunks)
    return report
