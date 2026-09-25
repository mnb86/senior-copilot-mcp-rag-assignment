"""Retrieval service used by the copilot (wraps the RAG index; multi-query fusion)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from rag.ingestion import ingest
from rag.retrieval import HybridRetriever
from rag.retrieval.models import RetrievalFilters, RetrievalResult, RetrievedChunk

log = logging.getLogger("copilot.retrieval")


class RetrievalService:
    def __init__(
        self,
        index_path: str,
        document_path: str,
        *,
        embedder: str = "lsa",
        auto_ingest: bool = True,
        top_k: int = 5,
        low_confidence_threshold: float = 0.30,
    ) -> None:
        self.index_path = Path(index_path)
        self.document_path = Path(document_path)
        self.embedder = embedder
        self.top_k = top_k
        self.threshold = low_confidence_threshold
        self._lock = threading.Lock()
        self._retriever: HybridRetriever | None = None
        self.load(auto_ingest=auto_ingest)

    @property
    def manifest(self) -> dict:
        return self._retriever.index.manifest if self._retriever else {}

    def load(self, auto_ingest: bool = True) -> None:
        if auto_ingest:
            report = ingest(self.document_path, self.index_path, embedder=self.embedder)
            log.info(
                "rag index ready: %s documents, %s chunks (unchanged=%s)",
                report.documents,
                report.chunks,
                report.skipped_unchanged,
            )
        with self._lock:
            self._retriever = HybridRetriever.from_directory(self.index_path, low_confidence_threshold=self.threshold)

    def reindex(self, force: bool = True) -> dict:
        report = ingest(self.document_path, self.index_path, embedder=self.embedder, force=force)
        with self._lock:
            self._retriever = HybridRetriever.from_directory(self.index_path, low_confidence_threshold=self.threshold)
        return report.to_dict()

    def search(self, query: str, filters: RetrievalFilters | None = None, top_k: int | None = None) -> RetrievalResult:
        assert self._retriever is not None
        return self._retriever.search(query, filters, top_k or self.top_k)

    def search_many(self, queries: list[str], filters: RetrievalFilters) -> RetrievalResult:
        """Run several queries (primary + derived) and fuse results by best score per chunk."""
        queries = [q for q in queries if q and q.strip()] or [""]
        best: dict[str, RetrievedChunk] = {}
        quarantined: dict[str, RetrievedChunk] = {}
        fallback = False
        total_ms = 0.0
        must_include: list[str] = []
        for i, q in enumerate(queries):
            r = self.search(q, filters, self.top_k)
            total_ms += r.duration_ms
            fallback = fallback or r.fallback_used
            if i >= 2 and r.results and not r.low_confidence:
                must_include.append(r.results[0].chunk.chunk_id)  # evidence for each derived/verification query
            weight = 1.0 if i < 2 else 0.9  # primary queries slightly preferred over derived ones
            for rc in r.results:
                scored = rc.model_copy(update={"score": round(rc.score * weight, 4)})
                if rc.chunk.chunk_id not in best or best[rc.chunk.chunk_id].score < scored.score:
                    best[rc.chunk.chunk_id] = scored
            for rc in r.quarantined:
                quarantined.setdefault(rc.chunk.chunk_id, rc)
        ordered = sorted(best.values(), key=lambda r: -r.score)
        ranked = ordered[: self.top_k + 2]
        for cid in dict.fromkeys(must_include):
            if all(r.chunk.chunk_id != cid for r in ranked) and len(ranked) < self.top_k + 6:
                ranked.append(best[cid])
        for i, rc in enumerate(ranked, start=1):
            rc.rank = i
        top_conf = max((r.confidence for r in ranked), default=0.0)
        return RetrievalResult(
            query=" | ".join(queries),
            filters=filters,
            results=ranked,
            quarantined=list(quarantined.values()),
            low_confidence=top_conf < self.threshold,
            top_confidence=top_conf,
            fallback_used=fallback,
            duration_ms=round(total_ms, 2),
        )
