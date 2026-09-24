"""Retrieval service: hybrid BM25 + dense search over the persisted index."""

from .index import RetrievalIndex
from .retriever import HybridRetriever

__all__ = ["HybridRetriever", "RetrievalIndex"]
