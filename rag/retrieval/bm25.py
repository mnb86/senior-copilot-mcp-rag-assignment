"""Okapi BM25 sparse retrieval (no external dependency)."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .text import tokenize


class BM25Index:
    def __init__(self, k1: float = 1.4, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_tf: list[dict[str, int]] = []
        self.doc_len: list[int] = []
        self.df: Counter[str] = Counter()
        self.avgdl = 0.0

    def fit(self, texts: list[str]) -> BM25Index:
        self.doc_tf, self.doc_len, self.df = [], [], Counter()
        for t in texts:
            toks = tokenize(t)
            tf = Counter(toks)
            self.doc_tf.append(dict(tf))
            self.doc_len.append(len(toks))
            self.df.update(tf.keys())
        self.avgdl = sum(self.doc_len) / max(1, len(self.doc_len))
        return self

    @property
    def n_docs(self) -> int:
        return len(self.doc_tf)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> tuple[list[float], list[float]]:
        """Return (bm25 score, query-term coverage in [0,1]) per document."""
        q_terms = list(dict.fromkeys(tokenize(query)))
        scores = [0.0] * self.n_docs
        coverage = [0.0] * self.n_docs
        if not q_terms:
            return scores, coverage
        idfs = {t: self.idf(t) for t in q_terms}
        total_idf = sum(idfs.values()) or 1.0
        for i, tf in enumerate(self.doc_tf):
            dl = self.doc_len[i] or 1
            s, cov = 0.0, 0.0
            for t in q_terms:
                f = tf.get(t)
                if not f:
                    continue
                s += idfs[t] * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                cov += idfs[t]
            scores[i] = s
            coverage[i] = cov / total_idf
        return scores, coverage

    def to_dict(self) -> dict[str, Any]:
        return {"k1": self.k1, "b": self.b, "doc_tf": self.doc_tf, "doc_len": self.doc_len, "df": dict(self.df)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BM25Index:
        idx = cls(d["k1"], d["b"])
        idx.doc_tf = d["doc_tf"]
        idx.doc_len = d["doc_len"]
        idx.df = Counter(d["df"])
        idx.avgdl = sum(idx.doc_len) / max(1, len(idx.doc_len))
        return idx
