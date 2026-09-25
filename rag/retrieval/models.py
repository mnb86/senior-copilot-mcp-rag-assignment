"""Shared RAG data models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Section(BaseModel):
    heading: str
    text: str


class ExtractedDocument(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    source_path: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[Section]


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    doc_type: str
    section: str
    text: str
    ordinal: int
    source_path: str
    revision: str | None = None
    effective_date: str | None = None
    site: str = "ALL"
    asset_types: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    alarm_names: list[str] = Field(default_factory=list)
    trust_level: str = "controlled"  # controlled | external
    injection_suspected: bool = False
    injection_patterns: list[str] = Field(default_factory=list)

    def embedding_text(self) -> str:
        """Contextual header + body: improves retrieval of short sections."""
        return f"{self.title}. {self.section}. {self.text}"


class RetrievalFilters(BaseModel):
    doc_types: list[str] | None = None
    site: str | None = None
    asset_types: list[str] | None = None
    asset_ids: list[str] | None = None  # soft filter: boosts matching chunks
    alarm_names: list[str] | None = None  # soft filter: boosts matching chunks


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    confidence: float
    bm25: float
    dense: float
    boost: float
    rank: int


class RetrievalResult(BaseModel):
    query: str
    filters: RetrievalFilters
    results: list[RetrievedChunk]
    quarantined: list[RetrievedChunk] = Field(default_factory=list)
    low_confidence: bool
    top_confidence: float
    fallback_used: bool = False
    duration_ms: float = 0.0
