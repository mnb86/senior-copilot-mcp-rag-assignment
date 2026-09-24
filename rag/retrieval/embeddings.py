"""Embedding providers.

Default: ``lsa`` - TF-IDF (unigram + bigram) projected with truncated SVD (Latent Semantic Analysis).
It is fully local, deterministic, dependency-light (numpy only) and captures co-occurrence semantics
(e.g. "cavitation" ~ "low suction pressure") that pure keyword matching misses.

Optional: ``fastembed`` (ONNX sentence embeddings, BAAI/bge-small-en-v1.5) when the package and model
are available. The provider is selected with ``EMBEDDING_PROVIDER``.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Protocol

import numpy as np

from .text import tokenize


class Embedder(Protocol):
    name: str

    def fit(self, texts: list[str]) -> None: ...
    def embed(self, texts: list[str]) -> np.ndarray: ...
    def save(self, directory: Path) -> None: ...


def _features(text: str) -> list[str]:
    toks = tokenize(text)
    return toks + [f"{a}_{b}" for a, b in pairwise(toks)]


class LsaEmbedder:
    name = "lsa"

    def __init__(self, dims: int = 96, min_df: int = 1) -> None:
        self.dims = dims
        self.min_df = min_df
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0)
        self.components: np.ndarray = np.zeros((0, 0))  # (vocab, k)
        self.singular: np.ndarray = np.zeros(0)

    def _tfidf(self, texts: list[str]) -> np.ndarray:
        m = np.zeros((len(texts), len(self.vocab)), dtype=np.float64)
        for i, t in enumerate(texts):
            for term, c in Counter(_features(t)).items():
                j = self.vocab.get(term)
                if j is not None:
                    m[i, j] = 1 + math.log(c)
        m *= self.idf
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return m / norms

    def fit(self, texts: list[str]) -> None:
        df: Counter[str] = Counter()
        for t in texts:
            df.update(set(_features(t)))
        terms = sorted(t for t, c in df.items() if c >= self.min_df)
        self.vocab = {t: i for i, t in enumerate(terms)}
        n = len(texts)
        self.idf = np.array([math.log((1 + n) / (1 + df[t])) + 1 for t in terms])
        x = self._tfidf(texts)
        k = max(1, min(self.dims, min(x.shape) - 1))
        _, s, vt = np.linalg.svd(x, full_matrices=False)
        self.components = vt[:k].T
        self.singular = s[:k]

    def embed(self, texts: list[str]) -> np.ndarray:
        x = self._tfidf(texts) @ self.components
        norms = np.linalg.norm(x, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return np.asarray(x / norms, dtype=np.float32)

    def save(self, directory: Path) -> None:
        (directory / "lsa_vocab.json").write_text(json.dumps(self.vocab))
        np.savez_compressed(
            directory / "lsa_model.npz",
            idf=self.idf,
            components=self.components,
            singular=self.singular,
            dims=np.array([self.dims]),
        )

    @classmethod
    def load(cls, directory: Path) -> LsaEmbedder:
        e = cls()
        e.vocab = json.loads((directory / "lsa_vocab.json").read_text())
        data = np.load(directory / "lsa_model.npz")
        e.idf, e.components, e.singular = data["idf"], data["components"], data["singular"]
        e.dims = int(data["dims"][0])
        return e


class FastEmbedEmbedder:  # pragma: no cover - optional heavy dependency
    name = "fastembed"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self.model_name = model
        self._model = TextEmbedding(model)

    def fit(self, texts: list[str]) -> None:
        return None

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(list(self._model.embed(texts)), dtype=np.float32)

    def save(self, directory: Path) -> None:
        (directory / "fastembed.json").write_text(json.dumps({"model": self.model_name}))

    @classmethod
    def load(cls, directory: Path) -> FastEmbedEmbedder:
        return cls(json.loads((directory / "fastembed.json").read_text())["model"])


def create_embedder(name: str) -> Embedder:
    if name == "lsa":
        return LsaEmbedder()
    if name == "fastembed":
        return FastEmbedEmbedder()
    raise ValueError(f"Unknown embedding provider '{name}' (expected 'lsa' or 'fastembed')")


def load_embedder(name: str, directory: Path) -> Embedder:
    if name == "lsa":
        return LsaEmbedder.load(directory)
    if name == "fastembed":
        return FastEmbedEmbedder.load(directory)
    raise ValueError(f"Unknown embedding provider '{name}'")
