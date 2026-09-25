"""MCP server: registration, discovery, schemas, validation, error mapping, pagination, retries, trace, auth."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from alarm_mcp.app import create_asgi_app
from alarm_mcp.config import ServerSettings
from alarm_mcp.server import trace_from_context
from conftest import make_mcp

EXPECTED_TOOLS = {
    "search_assets",
    "get_asset_metadata",
    "get_alarms",
    "get_alarm_details",
    "summarize_alarms",
    "get_alarm_trends",
    "correlate_alarms",
    "score_alarm_priority",
    "get_operator_recommendations",
    "analyze_alarm_flood",
    "find_rationalization_candidates",
    "calculate_kpi",
    "list_kpi_definitions",
}
W = {"start_time": "2026-04-02T00:00:00Z", "end_time": "2026-07-01T00:00:00Z"}


def err_payload(exc: Exception) -> dict:
    text = str(exc)
    return json.loads(text[text.index("{") :])["error"]


async def call(mcp, name, args):
    _, structured = await mcp.call_tool(name, args)
    return structured


async def test_tool_registration_and_discovery(sim_app):
    tools = await make_mcp(sim_app).list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t.description and len(t.description) > 30
        assert t.inputSchema["type"] == "object" and t.outputSchema and "trace" in t.outputSchema["properties"]
        assert t.annotations.readOnlyHint is True and t.annotations.destructiveHint is False


async def test_typed_input_schemas(sim_app):
    tools = {t.name: t for t in await make_mcp(sim_app).list_tools()}
    ga = tools["get_alarms"].inputSchema["properties"]
    assert ga["page_size"]["maximum"] == 200 and ga["status"]["anyOf"][0]["enum"] == ["active", "cleared", "shelved"]
    corr = tools["correlate_alarms"].inputSchema
    assert corr["required"] == ["asset_ids"] and corr["properties"]["asset_ids"]["maxItems"] == 20
    assert "pattern" in tools["get_asset_metadata"].inputSchema["properties"]["asset_id"]


async def test_tool_allow_list(sim_app):
    tools = await make_mcp(sim_app, enabled_tools="search_assets,get_alarms").list_tools()
    assert {t.name for t in tools} == {"search_assets", "get_alarms"}


async def test_search_then_metadata_chain_with_trace(sim_app):
    mcp = make_mcp(sim_app)
    found = await call(mcp, "search_assets", {"query": "Boiler Feed Pump 101"})
    asset_id = found["results"][0]["asset_id"]
    meta = await call(mcp, "get_asset_metadata", {"asset_id": asset_id})
    assert meta["asset"]["asset_id"] == "AST-BFP-101"
    tr = meta["trace"]
    assert tr["tool"] == "get_asset_metadata" and tr["trace_id"].startswith("trace-")
    assert tr["api_calls"][0]["path"] == "/assets/AST-BFP-101/metadata" and tr["api_calls"][0]["status"] == 200
    assert "Authorization" not in json.dumps(meta) and "test-api-token" not in json.dumps(meta)


@pytest.mark.parametrize(
    "name,args,fragment",
    [
        ("get_asset_metadata", {"asset_id": "../../etc/passwd"}, "pattern"),
        ("get_alarms", {"asset_id": "AST-BFP-101", "page_size": 5000}, "less than or equal"),
        ("get_alarms", {"asset_id": "AST-BFP-101", "status": "exploded"}, "Input should be"),
        ("search_assets", {"query": ""}, "at least 1"),
        ("correlate_alarms", {"asset_ids": []}, "at least 1"),
    ],
)
async def test_invalid_inputs_are_rejected_by_schema(sim_app, name, args, fragment):
    with pytest.raises(ToolError) as ei:
        await make_mcp(sim_app).call_tool(name, args)
    assert fragment in str(ei.value)


async def test_semantic_validation_errors_are_structured(sim_app):
    mcp = make_mcp(sim_app)
    with pytest.raises(ToolError) as ei:
        await mcp.call_tool("get_alarms", {})
    assert err_payload(ei.value)["code"] == "INVALID_ARGUMENT"
    with pytest.raises(ToolError) as ei:
        await mcp.call_tool(
            "summarize_alarms",
            {"asset_ids": ["AST-BFP-101"], "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-06-01T00:00:00Z"},
        )
    assert "end_time must be after start_time" in err_payload(ei.value)["message"]


async def test_api_errors_are_mapped(sim_app):
    with pytest.raises(ToolError) as ei:
        await make_mcp(sim_app).call_tool("get_asset_metadata", {"asset_id": "AST-NOPE"})
    e = err_payload(ei.value)
    assert e["code"] == "NOT_FOUND" and e["http_status"] == 404 and e["upstream_code"] == "ASSET_NOT_FOUND"
    assert e["retryable"] is False and e["attempts"] == 1


async def test_retry_is_visible_in_trace(sim_app_faulty):
    res = await call(make_mcp(sim_app_faulty), "correlate_alarms", {"asset_ids": ["AST-BFP-101"], **W})
    assert res["trace"]["retries"] == 1
    assert [c["status"] for c in res["trace"]["api_calls"]] == [503, 200]
    assert res["pairs"][0]["source"]["alarm_name"] == "Deaerator Low Level"


async def test_persistent_upstream_failure_after_retries(sim_app):
    mcp = make_mcp(sim_app)
    alarms = await call(mcp, "get_alarms", {"asset_id": "AST-CWP-301", "page_size": 1})
    with pytest.raises(ToolError) as ei:
        await mcp.call_tool("get_operator_recommendations", {"alarm_id": alarms["alarms"][0]["alarm_id"]})
    e = err_payload(ei.value)
    assert e["code"] == "UPSTREAM_UNAVAILABLE" and e["attempts"] == 3 and e["retryable"] is True


async def test_pagination_fetch_all_pages(sim_app):
    res = await call(
        make_mcp(sim_app),
        "get_alarms",
        {"asset_id": "AST-BFP-101", "page_size": 10, "fetch_all_pages": True, "max_pages": 4},
    )
    assert len(res["alarms"]) == 40 and res["pagination"]["pages_fetched"] == 4 and res["pagination"]["truncated"]
    assert len({c["params"]["page"] for c in res["trace"]["api_calls"]}) == 4


async def test_advanced_tools(sim_app):
    mcp = make_mcp(sim_app)
    active = await call(mcp, "get_alarms", {"site": "EastRefinery", "status": "active"})
    aid = active["alarms"][0]["alarm_id"]
    prio = await call(mcp, "score_alarm_priority", {"alarm_id": aid})
    assert prio["priority_band"] in {"P1", "P2", "P3", "P4"}
    recs = await call(mcp, "get_operator_recommendations", {"alarm_id": aid})
    assert recs["recommendations"][0]["rank"] == 1
    kpi = await call(mcp, "calculate_kpi", {"calculation_type": "alarm_flood_index", "unit": "Unit 2", **W})
    assert kpi["calculation_id"].startswith("CALC-") and len(kpi["trace"]["api_calls"]) == 2
    flood = await call(mcp, "analyze_alarm_flood", {"unit": "Unit 2", **W})
    assert flood["flood_window_count"] >= 1
    trends = await call(mcp, "get_alarm_trends", {"asset_ids": ["AST-K-301"], **W, "bucket": "weekly"})
    assert trends["trend"]["direction"] in {"increasing", "decreasing", "stable"}
    rat = await call(mcp, "find_rationalization_candidates", {"unit": "Unit 4", **W})
    assert rat["candidate_count"] > 0
    defs = await call(mcp, "list_kpi_definitions", {})
    assert defs["kpis"]


def test_trace_context_from_meta_is_sanitised():
    class Meta:
        model_extra = {"trace_id": "trace-1<script>", "conversation_id": "c1", "client_id": "copilot"}

    class RC:
        meta = Meta()
        request = None

    class Ctx:
        request_context = RC()

    tc = trace_from_context(Ctx())
    assert tc.trace_id == "trace-1script" and tc.conversation_id == "c1" and tc.client_id == "copilot"
    assert trace_from_context(None).trace_id.startswith("trace-")


async def test_http_app_requires_bearer_token_and_exposes_health(sim_app):
    settings = ServerSettings(MCP_SERVER_TOKEN="tok")
    app = create_asgi_app(settings, make_mcp(sim_app))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp") as c:
        assert (await c.post("/mcp", json={})).status_code == 401
        assert (await c.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})).status_code == 401
        h = await c.get("/healthz")
        assert h.status_code == 200 and h.json()["tools"] == 13
