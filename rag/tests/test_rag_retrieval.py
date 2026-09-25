"""RAG retrieval: relevance, filters, no-result / low-confidence handling, quarantine, citations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copilot.reasoning import build_citations
from copilot.retrieval_service import RetrievalService
from rag.ingestion import ingest
from rag.retrieval import HybridRetriever
from rag.retrieval.models import RetrievalFilters

DOCS = Path(__file__).resolve().parents[1] / "documents"


@pytest.fixture(scope="module")
def rag_index_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("rag_index")
    report = ingest(DOCS, out, force=True)
    assert report.documents >= 9 and not report.errors
    return out


@pytest.fixture(scope="module")
def retriever(rag_index_dir):
    return HybridRetriever.from_directory(rag_index_dir)


EVAL_SET = json.loads((Path(__file__).resolve().parents[2] / "test-data" / "retrieval_eval.json").read_text("utf-8"))


@pytest.mark.parametrize("case", EVAL_SET["cases"], ids=lambda c: c["query"][:40])
def test_retrieval_eval_set(retriever, case):
    """Relevance regression suite: every case in test-data/retrieval_eval.json must rank its expected chunk first."""
    res = retriever.search(case["query"], RetrievalFilters(**case["filters"]) if case["filters"] else None, top_k=3)
    if case.get("expect_low_confidence"):
        assert res.low_confidence
        return
    assert res.results[0].chunk.chunk_id.startswith(case["expected_top"])
    assert not res.low_confidence


def test_hard_filters_restrict_doc_type_and_site(retriever):
    res = retriever.search(
        "restart after trip", RetrievalFilters(doc_types=["safety_instruction"]), top_k=5, relax_filters_on_empty=False
    )
    assert res.results and all(r.chunk.doc_type == "safety_instruction" for r in res.results)
    res = retriever.search(
        "discharge pressure", RetrievalFilters(site="NorthPlant"), top_k=10, relax_filters_on_empty=False
    )
    assert all(r.chunk.site in ("NorthPlant", "ALL") for r in res.results)


def test_metadata_boost_prefers_asset_specific_documents(retriever):
    def rank_of(res, doc_id):
        return next(r.rank for r in res.results if r.chunk.doc_id == doc_id)

    plain = retriever.search("high vibration alarm response", None, top_k=10)
    boosted = retriever.search("high vibration alarm response", RetrievalFilters(asset_ids=["AST-CWP-301"]), top_k=10)
    assert rank_of(boosted, "MM-CW-006") < rank_of(plain, "MM-CW-006")
    assert next(r for r in boosted.results if r.chunk.doc_id == "MM-CW-006").boost == pytest.approx(0.10)


def test_no_result_and_low_confidence(retriever):
    res = retriever.search("chocolate cake recipe with sprinkles", None)
    assert res.results == [] and res.low_confidence and res.top_confidence == 0
    assert retriever.search("   ", None).low_confidence


def test_filter_fallback_when_nothing_matches(retriever):
    res = retriever.search("shelving safety alarms", RetrievalFilters(doc_types=["maintenance_manual"]))
    assert res.fallback_used and res.results[0].chunk.doc_id == "AP-ALM-001"


def test_injected_chunk_is_quarantined_not_returned(retriever):
    res = retriever.search("AI assistant bypass K-301 discharge pressure trip interlock disable alarm", None, top_k=5)
    assert all(not r.chunk.injection_suspected for r in res.results)
    assert [q.chunk.chunk_id for q in res.quarantined] == ["KB-VND-K301#3-note-for-automated-assistants"]


def test_citations_match_retrieved_chunks(retriever):
    res = retriever.search("low suction pressure deaerator level", None, top_k=3)
    cites = build_citations(res)
    assert [c.chunk_id for c in cites] == [r.chunk.chunk_id for r in res.results]
    assert all(
        c.snippet and c.snippet[:40] in " ".join(r.chunk.text.split()) for c, r in zip(cites, res.results, strict=True)
    )


def test_retrieval_service_multi_query_fusion(rag_index_dir):
    svc = RetrievalService(str(rag_index_dir), "rag/documents", auto_ingest=False, top_k=4)
    res = svc.search_many(
        ["low suction pressure boiler feed pump", "anything", "Reset the pump trip and restart the pump immediately"],
        RetrievalFilters(),
    )
    ids = [r.chunk.chunk_id for r in res.results]
    assert "SOP-BFP-001#4-pump-trip-response" in ids  # verification query evidence is guaranteed
    assert len(ids) == len(set(ids)) and [r.rank for r in res.results] == list(range(1, len(ids) + 1))
