"""On-disk retrieval index: chunks + BM25 statistics + dense vectors + manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from rag.retrieval.models import Chunk

from .bm25 import BM25Index
from .embeddings import Embedder, create_embedder, load_embedder

INDEX_VERSION = 1


@dataclass
class RetrievalIndex:
    chunks: list[Chunk]
    bm25: BM25Index
    vectors: np.ndarray
    embedder: Embedder
    manifest: dict[str, Any]

    @classmethod
    def build(
        cls, chunks: list[Chunk], embedder_name: str, corpus_hash: str, documents: list[dict[str, Any]]
    ) -> RetrievalIndex:
        texts = [c.embedding_text() for c in chunks]
        bm25 = BM25Index().fit(texts)
        embedder = create_embedder(embedder_name)
        embedder.fit(texts)
        vectors = embedder.embed(texts) if texts else np.zeros((0, 1), dtype=np.float32)
        manifest = {
            "index_version": INDEX_VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "embedder": embedder.name,
            "corpus_hash": corpus_hash,
            "chunk_count": len(chunks),
            "document_count": len(documents),
            "documents": documents,
            "vector_dims": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
        }
        return cls(chunks, bm25, vectors, embedder, manifest)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "chunks.jsonl").open("w", encoding="utf-8") as fh:
            for c in self.chunks:
                fh.write(c.model_dump_json() + "\n")
        (directory / "bm25.json").write_text(json.dumps(self.bm25.to_dict()))
        np.save(directory / "vectors.npy", self.vectors)
        self.embedder.save(directory)
        (directory / "manifest.json").write_text(json.dumps(self.manifest, indent=2))

    @classmethod
    def load(cls, directory: Path) -> RetrievalIndex:
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No retrieval index at {directory}; run `python -m rag.ingestion` first")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("index_version") != INDEX_VERSION:
            raise ValueError("Index version mismatch; rebuild with `python -m rag.ingestion --force`")
        chunks = [
            Chunk.model_validate_json(line)
            for line in (directory / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        bm25 = BM25Index.from_dict(json.loads((directory / "bm25.json").read_text()))
        vectors = np.load(directory / "vectors.npy")
        embedder = load_embedder(manifest["embedder"], directory)
        return cls(chunks, bm25, vectors, embedder, manifest)
