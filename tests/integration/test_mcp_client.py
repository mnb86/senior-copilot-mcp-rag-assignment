"""MCP client over real streamable HTTP: connectivity, discovery, invocation, invalid args, missing tools,
partial failure, auth and unreachable server."""

from __future__ import annotations

import pytest

from copilot.config import Settings
from copilot.mcp_client import McpClientError, McpHttpGateway, parse_tool_error

pytestmark = pytest.mark.integration


def gateway(stack: dict[str, str], **over: str) -> McpHttpGateway:
    cfg = {
        "MCP_SERVER_URL": stack["mcp_url"],
        "MCP_SERVER_TOKEN": stack["mcp_token"],
        "MCP_TIMEOUT_SECONDS": "20",
        **over,
    }
    return McpHttpGateway(Settings(**cfg))


async def test_connect_discover_and_invoke(live_stack):
    gw = gateway(live_stack)
    async with gw.session() as s:
        tools = await s.list_tools()
        assert len(tools) == 13 and all(t.read_only for t in tools)
        out = await s.call_tool("search_assets", {"query": "Boiler Feed Pump 101"}, {"trace_id": "trace-client-1"})
        assert out.ok and out.output_schema_valid is True
        assert out.data["results"][0]["asset_id"] == "AST-BFP-101"
        assert out.data["trace"]["trace_id"] == "trace-client-1"  # _meta trace propagated to the server


async def test_multi_step_chain_over_http(live_stack):
    async with gateway(live_stack).session() as s:
        found = await s.call_tool("search_assets", {"query": "Recycle Gas Compressor K-301"}, {})
        asset_id = found.data["results"][0]["asset_id"]
        alarms = await s.call_tool("get_alarms", {"asset_id": asset_id, "status": "active"}, {})
        alarm_id = alarms.data["alarms"][0]["alarm_id"]
        recs = await s.call_tool("get_operator_recommendations", {"alarm_id": alarm_id}, {})
        assert recs.ok and recs.data["alarm_id"] == alarm_id


async def test_client_side_schema_validation(live_stack):
    async with gateway(live_stack).session() as s:
        with pytest.raises(McpClientError) as ei:
            await s.call_tool("get_alarms", {"asset_id": "AST-BFP-101", "page_size": "lots"}, {})
        assert ei.value.code == "INVALID_ARGUMENT" and ei.value.details[0]["path"] == "page_size"


async def test_missing_tool(live_stack):
    async with gateway(live_stack).session() as s:
        with pytest.raises(McpClientError) as ei:
            await s.call_tool("delete_all_alarms", {}, {})
        assert ei.value.code == "TOOL_NOT_FOUND" and "search_assets" in ei.value.details["available"]


async def test_tool_error_result_is_parsed_as_partial_failure(live_stack):
    async with gateway(live_stack).session() as s:
        out = await s.call_tool("get_asset_metadata", {"asset_id": "AST-DOES-NOT-EXIST"}, {})
        assert not out.ok and out.error["code"] == "NOT_FOUND" and out.error["http_status"] == 404
        still_ok = await s.call_tool("search_assets", {"query": "pump"}, {})
        assert still_ok.ok  # the session survives a failed tool call


async def test_wrong_token_and_unreachable_server(live_stack):
    with pytest.raises(McpClientError) as ei:
        async with gateway(live_stack, MCP_SERVER_TOKEN="wrong").session():
            pass
    assert ei.value.code == "MCP_UNAVAILABLE" and "401" in ei.value.message
    with pytest.raises(McpClientError) as ei:
        async with gateway(live_stack, MCP_SERVER_URL="http://127.0.0.1:9/mcp", MCP_TIMEOUT_SECONDS="2").session():
            pass
    assert ei.value.code == "MCP_UNAVAILABLE"


async def test_tool_discovery_is_cached(live_stack):
    gw = gateway(live_stack)
    first = await gw.discover()
    assert gw._tool_cache is not None
    second = await gw.discover()
    assert [t.name for t in first] == [t.name for t in second]


def test_parse_tool_error_variants():
    assert (
        parse_tool_error('Error executing tool x: {"error": {"code": "NOT_FOUND", "message": "m"}}')["code"]
        == "NOT_FOUND"
    )
    assert parse_tool_error("Error executing tool x: 1 validation error for xArguments")["code"] == "INVALID_ARGUMENT"
    assert parse_tool_error("Unknown tool: nope")["code"] == "TOOL_NOT_FOUND"
    assert parse_tool_error("boom")["code"] == "TOOL_ERROR"
