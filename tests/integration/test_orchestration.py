"""Orchestration: multi-step MCP chains, output passing, RAG in the same workflow, partial failures,
unavailable tools/servers, conflicting evidence and context retention."""

from __future__ import annotations

import contextlib

import pytest

from conftest import InProcessGateway, make_mcp
from copilot.config import Settings
from copilot.domain import ChatRequest
from copilot.mcp_client import McpClientError
from copilot.orchestrator import Copilot
from copilot.retrieval_service import RetrievalService

ACCEPTANCE = (
    "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify "
    "likely contributing factors, retrieve the relevant operating procedure, and provide recommended "
    "actions with source evidence."
)
SETTINGS = Settings(COPILOT_REFERENCE_TIME="2026-07-01T00:00:00Z")


@pytest.fixture(scope="module")
def retrieval(rag_index_dir):
    return RetrievalService(str(rag_index_dir), "rag/documents", auto_ingest=False)


def copilot(app, retrieval, enabled_tools: str = "") -> tuple[Copilot, InProcessGateway]:
    gw = InProcessGateway(make_mcp(app, enabled_tools))
    return Copilot(SETTINGS, gw, retrieval), gw


def steps(resp):
    return {r.step_id: r for r in resp.tool_trace if r.iteration is None}


async def test_acceptance_chain_passes_outputs_between_tools(sim_app_faulty, retrieval):
    cp, gw = copilot(sim_app_faulty, retrieval)
    r = await cp.handle(ChatRequest(message=ACCEPTANCE))
    s = steps(r)
    assert r.intent.name == "investigate"
    assert s["resolve_asset"].wave == 1 and s["asset_metadata"].wave == 2 and s["priority"].wave == 3
    assert s["retrieve_documents"].kind == "rag" and s["retrieve_documents"].wave == 4
    calls = {name: args for name, args, _ in gw.session_obj.calls}
    assert calls["get_asset_metadata"]["asset_id"] == "AST-BFP-101"  # output of search_assets passed on
    assert calls["summarize_alarms"]["severity"] == ["high", "critical"]
    primary = calls["score_alarm_priority"]["alarm_id"]
    assert calls["get_operator_recommendations"]["alarm_id"] == primary  # output of get_alarms passed on
    assert all(meta["trace_id"] == r.trace_id for _, _, meta in gw.session_obj.calls)
    # retrieval was fed with MCP outputs
    assert r.retrieval and r.retrieval.filters["asset_types"] == ["pump"]
    assert "AST-DEA-101" in r.retrieval.filters["asset_ids"]
    assert s["correlation"].retries == 1 and any("recovered after 1 retry" in w for w in r.warnings)


async def test_acceptance_answer_is_grounded_with_causes_citations_and_conflict(sim_app, retrieval):
    cp, _ = copilot(sim_app, retrieval)
    r = await cp.handle(ChatRequest(message=ACCEPTANCE))
    assert r.answer.confidence == "high" and r.answer.grounded
    assert r.likely_causes[0].cause.startswith("Deaerator 101: Deaerator Low Level")
    doc_ids = {c.doc_id for c in r.citations}
    assert {"SOP-BFP-001", "SOP-DEA-002"} <= doc_ids
    statuses = {x.action.split()[0]: x.status for x in r.recommendations if x.source == "api"}
    assert statuses["Reset"] == "conflict" and statuses["Check"] == "consistent"
    assert "[S" in r.answer.markdown and "Do not follow as written" in r.answer.markdown
    assert r.alarm_summary and r.alarm_summary.asset["asset_id"] == "AST-BFP-101"
    assert r.alarm_summary.top_alarm_groups[0]["alarm_name"] == "Low Suction Pressure"


async def test_context_retention_follow_up(sim_app, retrieval):
    cp, gw = copilot(sim_app, retrieval)
    first = await cp.handle(ChatRequest(message=ACCEPTANCE, conversation_id="conv1"))
    follow = await cp.handle(
        ChatRequest(
            message="Are the API recommendations consistent with the maintenance manual?", conversation_id="conv1"
        )
    )
    assert follow.intent.name == "recommendation_check"
    detail_call = [a for n, a, _ in gw.session_obj.calls if n == "get_alarm_details"][-1]
    assert detail_call["alarm_id"] == first.alarm_summary.primary_alarm.alarm_id
    assert any(x.status == "conflict" for x in follow.recommendations)
    assert "Consistency check" in follow.answer.markdown


async def test_partial_failure_recommendations_unavailable(sim_app, retrieval):
    cp, _ = copilot(sim_app, retrieval)
    r = await cp.handle(ChatRequest(message="Investigate alarms for Cooling Water Pump 301"))
    s = steps(r)
    assert s["recommendations"].status == "error" and s["recommendations"].error["code"] == "UPSTREAM_UNAVAILABLE"
    assert s["summary"].status == "ok" and r.answer.confidence == "medium"
    assert any("UPSTREAM_UNAVAILABLE" in w for w in r.warnings)
    assert any(x.source == "document" for x in r.recommendations)  # degraded: procedure guidance only
    assert r.citations[0].doc_id == "MM-CW-006"


async def test_unavailable_tool_is_skipped_gracefully(sim_app, retrieval):
    enabled = (
        "search_assets,get_asset_metadata,get_alarms,summarize_alarms,score_alarm_priority,"
        "get_operator_recommendations,get_alarm_trends"
    )
    cp, _ = copilot(sim_app, retrieval, enabled)
    r = await cp.handle(ChatRequest(message="Investigate Boiler Feed Pump 101"))
    corr = steps(r)["correlation"]
    assert corr.status == "skipped" and corr.error["code"] == "TOOL_NOT_FOUND"
    assert "correlate_alarms" not in r.discovered_tools
    assert steps(r)["recommendations"].status == "ok" and r.citations


async def test_mcp_server_unavailable_falls_back_to_documents(retrieval):
    class DownGateway:
        server_name = "alarm-management"

        @contextlib.asynccontextmanager
        async def session(self):
            raise McpClientError("MCP_UNAVAILABLE", "MCP server unreachable: ConnectError")
            yield  # pragma: no cover

    cp = Copilot(SETTINGS, DownGateway(), retrieval)
    r = await cp.handle(ChatRequest(message="Why are compressor discharge pressure alarms repeatedly occurring?"))
    assert r.errors and "MCP server unavailable" in r.errors[0]
    assert all(t.status != "ok" for t in r.tool_trace if t.kind == "mcp")
    assert steps(r)["retrieve_documents"].status == "ok" and r.citations


async def test_unknown_asset_asks_for_clarification(sim_app, retrieval):
    cp, _ = copilot(sim_app, retrieval)
    r = await cp.handle(ChatRequest(message="Investigate Boiler Feed Pump 999"))
    assert r.answer.confidence == "low" and "could not resolve the asset" in r.answer.markdown
    assert steps(r)["asset_metadata"].status == "skipped"


async def test_site_priority_foreach_and_generic_equipment(sim_app, retrieval):
    cp, _ = copilot(sim_app, retrieval)
    r = await cp.handle(ChatRequest(message="Which alarm has the highest priority in EastRefinery, and why?"))
    scans = [t for t in r.tool_trace if t.step_id == "priority_scan"]
    assert len(scans) >= 3 and {t.iteration for t in scans} == set(range(len(scans)))
    best = max((t.response["structuredContent"] for t in scans), key=lambda d: d["priority_score"])
    assert r.alarm_summary.primary_alarm.alarm_id == best["alarm_id"]
    r2 = await cp.handle(ChatRequest(message="Why are compressor discharge pressure alarms repeatedly occurring?"))
    assert r2.alarm_summary.asset["asset_id"] == "AST-K-301"  # focus asset chosen by matching alarm activity
    assert any("E-301" in c.cause for c in r2.likely_causes)
    assert r2.retrieval.quarantined  # injected vendor note retrieved but quarantined


async def test_kpi_and_general_questions(sim_app, retrieval):
    cp, _ = copilot(sim_app, retrieval)
    r = await cp.handle(ChatRequest(message="What is the alarm flood percentage in Unit 2 last month?"))
    assert r.intent.name == "alarm_kpi" and "alarm_flood_index" in r.alarm_summary.kpis
    g = await cp.handle(ChatRequest(message="What does the alarm philosophy say about shelving?"))
    assert not [t for t in g.tool_trace if t.kind == "mcp"] and g.citations[0].doc_id == "AP-ALM-001"
    assert "What the documents say" in g.answer.markdown


async def test_llm_answer_is_validated_and_guarded(sim_app, retrieval):
    class UnsafeLLM:
        name = "fake"

        async def complete(self, system: str, user: str, *, max_tokens: int = 1200) -> str:
            if "classify" in system:
                return "{}"
            return "Bypass the trip interlock to keep the pump running [S1] [S99]."

    gw = InProcessGateway(make_mcp(sim_app))
    cp = Copilot(SETTINGS, gw, retrieval, llm=UnsafeLLM())
    r = await cp.handle(ChatRequest(message="Investigate Boiler Feed Pump 101"))
    assert r.answer.generator == "template" and r.answer.safety_flags
    assert any("unsafe advice" in w for w in r.warnings)
