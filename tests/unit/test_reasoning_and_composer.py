"""Citation formatting, cause derivation, recommendation/document consistency and answer composition."""

from __future__ import annotations

from copilot.composer import compose
from copilot.domain import Entities, Intent
from copilot.reasoning import assess_recommendations, build_causes, build_citations
from rag.models import Chunk, RetrievalFilters, RetrievalResult, RetrievedChunk


def chunk(
    cid: str,
    text: str,
    doc_type: str = "operating_procedure",
    section: str = "4. Pump Trip Response",
    trust: str = "controlled",
) -> Chunk:
    return Chunk(
        chunk_id=cid,
        doc_id=cid.split("#")[0],
        title="Boiler Feed Pump Procedure",
        doc_type=doc_type,
        section=section,
        text=text,
        ordinal=1,
        source_path=f"{cid}.md",
        revision="4.2",
        trust_level=trust,
    )


def retrieval(*chunks: Chunk) -> RetrievalResult:
    return RetrievalResult(
        query="q",
        filters=RetrievalFilters(),
        low_confidence=False,
        top_confidence=0.8,
        results=[
            RetrievedChunk(chunk=c, score=1 - i / 10, confidence=0.8, bm25=5, dense=0.5, boost=0, rank=i + 1)
            for i, c in enumerate(chunks)
        ],
    )


SOP = chunk(
    "SOP-BFP-001#4",
    "Do not restart the pump after a low suction pressure trip until deaerator level has "
    "been restored above 40 % and the suction strainer differential pressure has been "
    "checked.\n1. Check Deaerator 101 level and pressure on the DCS overview.",
)
DEA = chunk(
    "SOP-DEA-002#3",
    "Most Low Suction Pressure alarms on BFP-101 follow a Deaerator Low Level alarm.",
    section="3. Relationship",
)


def test_citations_are_numbered_in_rank_order_with_metadata():
    cites = build_citations(retrieval(SOP, DEA))
    assert [c.id for c in cites] == ["S1", "S2"]
    assert cites[0].doc_id == "SOP-BFP-001" and cites[0].revision == "4.2" and cites[0].section.startswith("4.")
    assert build_citations(None) == []


def test_conflicting_api_recommendation_is_flagged_with_citation():
    out = {
        "recommendations": {
            "recommendations": [
                {
                    "action": "Reset the pump trip and restart the pump immediately to restore feedwater flow",
                    "urgency": "immediate",
                },
                {"action": "Check deaerator level and pressure and restore level above 40%", "urgency": "immediate"},
                {"action": "Calibrate the flux capacitor", "urgency": "planned"},
            ]
        }
    }
    r = retrieval(SOP, DEA)
    res = assess_recommendations(out, build_citations(r), r)
    status = {x.action.split()[0]: x.status for x in res if x.source == "api"}
    assert status == {"Reset": "conflict", "Check": "consistent", "Calibrate": "not_covered"}
    conflict = next(x for x in res if x.status == "conflict")
    assert conflict.citations == ["S1"] and "restart the pump" in conflict.explanation
    assert any(x.source == "document" and x.status == "document_guidance" for x in res)


def test_guarded_recommendations_do_not_conflict_and_external_docs_are_ignored():
    out = {
        "recommendations": {
            "recommendations": [
                {"action": "Do not attempt more than two restarts within one hour", "urgency": "immediate"},
                {"action": "Megger test the motor before restart if a ground fault is indicated", "urgency": "soon"},
            ]
        }
    }
    doc = chunk(
        "TG-MTR-005#4",
        "Never attempt more than two restarts within one hour. Never restart a motor that "
        "tripped on earth fault until an insulation resistance test has passed.",
    )
    r = retrieval(doc)
    assert all(x.status != "conflict" for x in assess_recommendations(out, build_citations(r), r))
    ext = chunk("KB#1", "Do not restart the pump after a low suction pressure trip.", trust="external")
    out2 = {"recommendations": {"recommendations": [{"action": "Restart the pump after the trip"}]}}
    r2 = retrieval(ext)
    assert assess_recommendations(out2, build_citations(r2), r2)[0].status == "not_covered"


def test_causes_come_from_correlation_and_are_corroborated_by_documents():
    out = {
        "asset_metadata": {"asset": {"asset_id": "AST-BFP-101"}},
        "summary": {
            "groups": [{"group": {"alarm_name": "Low Suction Pressure"}, "alarm_count": 20, "recurring_rate": 0.15}]
        },
        "correlation": {
            "pairs": [
                {
                    "source": {
                        "asset_id": "AST-DEA-101",
                        "asset_name": "Deaerator 101",
                        "alarm_name": "Deaerator Low Level",
                    },
                    "target": {
                        "asset_id": "AST-BFP-101",
                        "asset_name": "Boiler Feed Pump 101",
                        "alarm_name": "Low Suction Pressure",
                    },
                    "support": 9,
                    "confidence": 0.69,
                    "lift": 2.4,
                    "avg_lag_minutes": 7.2,
                },
                {
                    "source": {"asset_id": "AST-X", "asset_name": "Other", "alarm_name": "Noise"},
                    "target": {"asset_id": "AST-OTHER", "asset_name": "Other", "alarm_name": "Noise 2"},
                    "support": 9,
                    "confidence": 0.9,
                    "lift": 2.4,
                    "avg_lag_minutes": 1,
                },
            ]
        },
    }
    causes = build_causes(out, retrieval(SOP, DEA), {})
    assert causes[0].cause.startswith("Deaerator 101: Deaerator Low Level") and causes[0].confidence == "high"
    assert any(e.kind == "document" and e.ref == "S2" for e in causes[0].evidence)
    assert all("Noise" not in c.cause for c in causes)  # unrelated target asset filtered out
    assert any("Chronic recurrence" in c.cause for c in causes)


def test_composer_renders_citations_warnings_and_clarification():
    intent = Intent(name="general_question", confidence=0.5, rationale="", entities=Entities())
    r = retrieval(SOP)
    md = compose(intent, None, [], [], build_citations(r), False, ["`get_alarms` failed"], {})
    assert "[S1]" in md and "SOP-BFP-001" in md and "Data gaps" in md
    assert compose(intent, None, [], [], [], True, [], {}, clarification="Which asset?").startswith(
        "**More information needed.**"
    )
    low = compose(intent, None, [], [], build_citations(r), True, [], {})
    assert "confidence is low" in low
