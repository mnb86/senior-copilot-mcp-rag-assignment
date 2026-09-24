"""Hybrid retriever: BM25 + dense (LSA/embedding) scores, metadata filters and boosts,
prompt-injection quarantine and low-confidence detection."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from rag.models import Chunk, RetrievalFilters, RetrievalResult, RetrievedChunk

from .index import RetrievalIndex

DEFAULT_TOP_K = 5
LOW_CONFIDENCE_THRESHOLD = 0.30


def _norm_site(v: str | None) -> str:
    return (v or "").strip().lower()


def passes_filters(chunk: Chunk, f: RetrievalFilters) -> bool:
    """Hard filters: doc type, site (ALL matches any), asset type ('all' matches any)."""
    if f.doc_types and chunk.doc_type not in f.doc_types:
        return False
    if f.site and _norm_site(chunk.site) not in (_norm_site(f.site), "all"):
        return False
    if f.asset_types:
        types = {t.lower() for t in chunk.asset_types}
        if types and "all" not in types and not types & {t.lower() for t in f.asset_types}:
            return False
    return True


def metadata_boost(chunk: Chunk, f: RetrievalFilters) -> float:
    boost = 0.0
    if f.asset_ids and set(chunk.asset_ids) & set(f.asset_ids):
        boost += 0.10
    if f.alarm_names:
        names = {n.lower() for n in chunk.alarm_names}
        wanted = {n.lower() for n in f.alarm_names}
        if names & wanted:
            boost += 0.08
        section = chunk.section.lower()
        if any(n and n in section for n in wanted):
            boost += 0.15  # the section is *about* this alarm (e.g. "3. Low Suction Pressure Alarm")
    if chunk.trust_level == "external":
        boost -= 0.10
    return boost


class HybridRetriever:
    def __init__(
        self, index: RetrievalIndex, alpha: float = 0.5, low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD
    ) -> None:
        self.index = index
        self.alpha = alpha
        self.low_confidence_threshold = low_confidence_threshold

    @classmethod
    def from_directory(cls, directory: str | Path, **kw: float) -> HybridRetriever:
        return cls(RetrievalIndex.load(Path(directory)), **kw)

    def search(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
        top_k: int = DEFAULT_TOP_K,
        relax_filters_on_empty: bool = True,
    ) -> RetrievalResult:
        started = time.perf_counter()
        filters = filters or RetrievalFilters()
        res = self._search(query, filters, top_k)
        if (
            relax_filters_on_empty
            and (not res.results or res.low_confidence)
            and (filters.doc_types or filters.asset_types or filters.site)
        ):
            relaxed = RetrievalFilters(asset_ids=filters.asset_ids, alarm_names=filters.alarm_names)
            alt = self._search(query, relaxed, top_k)
            if alt.top_confidence > res.top_confidence:
                res = alt
                res.fallback_used = True
                res.filters = filters
        res.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return res

    def _search(self, query: str, f: RetrievalFilters, top_k: int) -> RetrievalResult:
        idx = self.index
        if not query.strip() or not idx.chunks:
            return RetrievalResult(query=query, filters=f, results=[], low_confidence=True, top_confidence=0.0)
        bm25, coverage = idx.bm25.scores(query)
        qv = idx.embedder.embed([query])[0]
        dense = (idx.vectors @ qv) if idx.vectors.size else np.zeros(len(idx.chunks))
        candidates = [i for i, c in enumerate(idx.chunks) if passes_filters(c, f)]
        if not candidates:
            return RetrievalResult(query=query, filters=f, results=[], low_confidence=True, top_confidence=0.0)
        max_bm25 = max((bm25[i] for i in candidates), default=0.0) or 1.0
        scored: list[tuple[float, float, int, float]] = []
        for i in candidates:
            d = max(0.0, float(dense[i]))
            b = bm25[i] / max_bm25
            boost = metadata_boost(idx.chunks[i], f)
            score = self.alpha * b + (1 - self.alpha) * d + boost
            confidence = max(0.0, min(1.0, 0.5 * coverage[i] + 0.5 * d + max(0.0, boost) / 2))
            if bm25[i] == 0 and d < 0.15:
                continue  # no lexical or semantic evidence at all
            scored.append((score, confidence, i, boost))
        scored.sort(key=lambda s: -s[0])
        results: list[RetrievedChunk] = []
        quarantined: list[RetrievedChunk] = []
        for score, conf, i, boost in scored:
            rc = RetrievedChunk(
                chunk=idx.chunks[i],
                score=round(score, 4),
                confidence=round(conf, 4),
                bm25=round(bm25[i], 4),
                dense=round(float(dense[i]), 4),
                boost=round(boost, 3),
                rank=len(results) + 1,
            )
            if idx.chunks[i].injection_suspected:
                if len(quarantined) < top_k:
                    quarantined.append(rc)
                continue
            results.append(rc)
            if len(results) >= top_k:
                break
        top_conf = results[0].confidence if results else 0.0
        return RetrievalResult(
            query=query,
            filters=f,
            results=results,
            quarantined=quarantined,
            low_confidence=top_conf < self.low_confidence_threshold,
            top_confidence=top_conf,
        )
