"""CLI: ``python -m rag.ingestion [--docs DIR] [--index DIR] [--embedder lsa|fastembed] [--force]``."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .pipeline import ingest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the RAG retrieval index")
    ap.add_argument("--docs", default=os.getenv("DOCUMENT_PATH", "rag/documents"))
    ap.add_argument("--index", default=os.getenv("RAG_INDEX_PATH", ".rag_index"))
    ap.add_argument("--embedder", default=os.getenv("EMBEDDING_PROVIDER", "lsa"))
    ap.add_argument("--force", action="store_true", help="rebuild even if the corpus is unchanged")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = ingest(args.docs, args.index, embedder=args.embedder, force=args.force)
    print(json.dumps(report.to_dict(), indent=2))
    return 1 if report.errors and not report.documents else 0


if __name__ == "__main__":
    sys.exit(main())
