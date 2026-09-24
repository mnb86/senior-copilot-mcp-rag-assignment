"""Tokenisation shared by BM25 and the LSA embedder."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    """
a an and are as at be been but by can could did do does for from had has have how i if in into is it its
may me must my no not of on or our should so such than that the their them then there these they this to
too under up was we were what when where which while who why will with would you your yes also any all
please show tell give find list about over last days day week weeks month months
""".split()  # noqa: SIM905 - readable word list
)

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


_DOUBLE = re.compile(r"([bdgmnprt])\1$")


def stem(token: str) -> str:
    """Very light suffix stripping (plural / -ing / -ed) - enough for a technical corpus."""
    if len(token) > 5 and token.endswith("ing"):
        return _DOUBLE.sub(r"\1", token[:-3])
    if len(token) > 4 and token.endswith("ed"):
        return _DOUBLE.sub(r"\1", token[:-2])
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        parts = [tok] + (tok.split("-") if "-" in tok else [])
        for p in parts:
            if p and p not in STOPWORDS and len(p) > 1:
                out.append(stem(p))
    return out
