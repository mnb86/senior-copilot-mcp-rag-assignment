"""End-to-end: HTTP request to the copilot backend -> real MCP server (streamable HTTP) -> Alarm API simulator,
combined with RAG retrieval -> grounded response with citations and an MCP execution trace."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from copilot.api import create_app
from copilot.config import Settings

pytestmark = pytest.mark.e2e

ACCEPTANCE = (
    "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify "
    "likely contributing factors, retrieve the relevant operating procedure, and provide recommended "
    "actions with source evidence."
)


@pytest.fixture(scope="module")
def backend(live_stack, tmp_path_factory):
    settings = Settings(
        MCP_SERVER_URL=live_stack["mcp_url"],
        MCP_SERVER_TOKEN=live_stack["mcp_token"],
        RAG_INDEX_PATH=str(tmp_path_factory.mktemp("e2e_index")),
        DOCUMENT_PATH="rag/documents",
        COPILOT_REFERENCE_TIME="2026-07-01T00:00:00Z",
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_health_and_tool_discovery(backend):
    h = backend.get("/api/health").json()
    assert h["status"] == "ok" and h["rag"]["documents"] == 10 and h["llm_provider"] == "offline"
    tools = backend.get("/api/tools").json()
    assert len(tools["tools"]) == 13 and tools["server"] == "alarm-management"


def test_acceptance_scenario_end_to_end(backend):
    r = backend.post("/api/chat", json={"message": ACCEPTANCE})
    assert r.status_code == 200
    body = r.json()
    trace = {t["step_id"]: t for t in body["tool_trace"] if t["iteration"] is None}
    # 1. asset resolution through MCP, 2. multi-step chaining through MCP
    assert trace["discover_tools"]["status"] == "ok"
    for step in (
        "resolve_asset",
        "asset_metadata",
        "alarms",
        "summary",
        "trend",
        "correlation",
        "priority",
        "recommendations",
    ):
        assert trace[step]["status"] == "ok", step
        assert trace[step]["api_calls"], step  # real upstream HTTP calls recorded
    assert trace["asset_metadata"]["arguments"]["asset_id"] == "AST-BFP-101"
    assert trace["correlation"]["retries"] == 1  # transient 503 retried inside the MCP server
    assert trace["resolve_asset"]["request"]["params"]["_meta"]["trace_id"] == body["trace_id"]
    # 3. RAG retrieval in the same workflow, 4. combined reasoning, 5. citations
    assert trace["retrieve_documents"]["status"] == "ok"
    assert {"SOP-BFP-001", "SOP-DEA-002"} <= {c["doc_id"] for c in body["citations"]}
    assert body["likely_causes"][0]["cause"].startswith("Deaerator 101")
    assert any(x["status"] == "conflict" for x in body["recommendations"])
    assert body["answer"]["confidence"] == "high" and "[S1]" in body["answer"]["markdown"]


def test_degraded_scenario_end_to_end(backend):
    body = backend.post("/api/chat", json={"message": "Investigate alarms for Cooling Water Pump 301"}).json()
    rec = next(t for t in body["tool_trace"] if t["step_id"] == "recommendations")
    assert rec["status"] == "error" and rec["error"]["code"] == "UPSTREAM_UNAVAILABLE" and rec["retries"] == 2
    assert body["answer"]["confidence"] == "medium" and body["citations"]


def test_conversation_history_and_input_validation(backend):
    first = backend.post("/api/chat", json={"message": "Investigate Boiler Feed Pump 102"}).json()
    hist = backend.get(f"/api/conversations/{first['conversation_id']}").json()
    assert hist["turns"][0]["intent"] == "investigate"
    assert backend.post("/api/chat", json={"message": ""}).status_code == 422
    assert backend.post("/api/chat", json={"message": "x", "conversation_id": "../etc"}).status_code == 422
    assert backend.post("/api/chat", content=b"x" * 20000).status_code == 413
    assert backend.post("/api/rag/reindex").status_code == 403
