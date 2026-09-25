"""One-command smoke test of a running stack: every Alarm API endpoint, every MCP tool on both servers, and the
copilot API, printed as one pass/fail table.

    python scripts/run_local.py        # terminal 1: start the stack
    python scripts/smoke_test.py       # terminal 2: test everything

Defaults match scripts/run_local.py; override with ALARM_API_BASE_URL, ALARM_API_TOKEN, MCP_SERVER_URL,
MCP_SERVER_TOKEN, DOCS_MCP_SERVER_URL, DOCS_MCP_SERVER_TOKEN and COPILOT_URL. Exits 1 if any check fails.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

API = os.getenv("ALARM_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.getenv("ALARM_API_TOKEN", "demo-token")
MCP_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:9000/mcp")
MCP_TOKEN = os.getenv("MCP_SERVER_TOKEN", "dev-mcp-token")
DOCS_URL = os.getenv("DOCS_MCP_SERVER_URL", "http://127.0.0.1:9100/mcp")
DOCS_TOKEN = os.getenv("DOCS_MCP_SERVER_TOKEN", "dev-docs-mcp-token")
COPILOT = os.getenv("COPILOT_URL", "http://127.0.0.1:8080").rstrip("/")

ACCEPTANCE = (
    "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely "
    "contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source "
    "evidence."
)

results: list[tuple[str, str, bool, str, float]] = []  # (area, check, ok, detail, ms)


async def check(area: str, name: str, fn: Callable[[], Awaitable[str]]) -> None:
    started = time.perf_counter()
    try:
        detail, ok = await fn(), True
    except Exception as exc:  # noqa: BLE001 - every failure becomes a table row
        detail, ok = f"{type(exc).__name__}: {exc}"[:110], False
    results.append((area, name, ok, detail, (time.perf_counter() - started) * 1000))


# ---------------------------------------------------------------------------- Alarm Management API
async def alarm_api(http: httpx.AsyncClient) -> None:
    end = datetime.now(UTC).replace(microsecond=0)
    window = {
        "start_time": (end - timedelta(days=90)).isoformat().replace("+00:00", "Z"),
        "end_time": end.isoformat().replace("+00:00", "Z"),
    }
    ids: dict[str, str] = {}

    async def call(method: str, path: str, body: Any = None, params: Any = None) -> Any:
        r = await http.request(
            method,
            f"{API}{path}",
            json=body,
            params=params,
            headers={"Authorization": f"Bearer {API_TOKEN}", "trace_id": "smoke-test"},
        )
        r.raise_for_status()
        return r.json()

    async def health() -> str:
        return (await call("GET", "/health"))["status"]

    async def unauthorized() -> str:
        r = await http.get(f"{API}/assets/search", params={"query": "pump"})
        assert r.status_code == 401, f"expected 401, got {r.status_code}"
        return "401 without token"

    async def search() -> str:
        body = await call("GET", "/assets/search", params={"query": "Boiler Feed Pump 101", "limit": 5})
        ids["asset"] = body["results"][0]["asset_id"]
        return ids["asset"]

    async def alarms() -> str:
        body = await call("GET", "/alarms", params={"asset_id": ids["asset"], "page": 1, "page_size": 50})
        ids["alarm"] = body["data"][0]["alarm_id"]
        return f"{body['pagination']['total']} alarms"

    async def calc() -> str:
        filters = {"unit": "Unit 3", **window}
        gen = await call(
            "POST", "/calculation-code/generate", {"calculation_type": "alarm_flood_index", "filters": filters}
        )
        out = await call(
            "POST", "/calculation-code/execute", {"calculation_id": gen["calculation_id"], "filters": filters}
        )
        return f"{out['calculation_type']} executed"

    scoped = lambda extra: {"asset_ids": [ids["asset"]], "time_range": window, **extra}  # noqa: E731
    steps: list[tuple[str, Callable[[], Awaitable[str]]]] = [
        ("GET /health", health),
        ("auth required", unauthorized),
        ("GET /assets/search", search),
        ("GET /assets/{id}/metadata", lambda: _ok(call("GET", f"/assets/{ids['asset']}/metadata"), "asset_name")),
        ("GET /alarms", alarms),
        ("GET /alarms/{id}", lambda: _ok(call("GET", f"/alarms/{ids['alarm']}"), "alarm_name")),
        (
            "POST /alarms/summary",
            lambda: _ok(call("POST", "/alarms/summary", scoped({"group_by": ["alarm_name"], "kpis": ["alarm_count"]}))),
        ),
        (
            "POST /alarms/trends",
            lambda: _ok(call("POST", "/alarms/trends", scoped({"bucket": "weekly", "metrics": ["alarm_count"]}))),
        ),
        (
            "POST /alarms/correlation",
            lambda: _ok(call("POST", "/alarms/correlation", scoped({"correlation_method": "cooccurrence"})), "pairs"),
        ),
        (
            "POST /alarms/flood-analysis",
            lambda: _ok(call("POST", "/alarms/flood-analysis", {"unit": "Unit 2", "time_range": window})),
        ),
        (
            "POST /alarms/rationalization-candidates",
            lambda: _ok(call("POST", "/alarms/rationalization-candidates", {"unit": "Unit 4", "time_range": window})),
        ),
        (
            "POST /alarms/priority-score",
            lambda: _ok(call("POST", "/alarms/priority-score", {"alarm_id": ids["alarm"]})),
        ),
        (
            "POST /recommendations/operator-actions",
            lambda: _ok(
                call("POST", "/recommendations/operator-actions", {"alarm_id": ids["alarm"], "include_related": True})
            ),
        ),
        ("POST /calculation-code/generate + execute", calc),
        ("GET /analytics/kpi-definitions", lambda: _ok(call("GET", "/analytics/kpi-definitions"), "kpis")),
    ]
    for name, fn in steps:
        await check("Alarm API", name, fn)


async def _ok(coro: Awaitable[Any], key: str | None = None) -> str:
    body = await coro
    if key is None:
        return "ok"
    value = body[key]
    return f"{key}: {len(value)}" if isinstance(value, list) else f"{key}: {value}"


# ---------------------------------------------------------------------------- MCP servers
def _resolve(value: Any, ctx: dict[str, Any]) -> Any:
    """Replace "$name" placeholders (also inside lists) with ids captured from earlier tool results."""
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    if isinstance(value, str) and value.startswith("$"):
        return ctx[value[1:]]
    return value


async def mcp_server(
    area: str, url: str, token: str, plan: Callable[[dict[str, Any]], list[tuple[str, dict[str, Any]]]]
) -> None:
    try:
        async with (
            streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            results.append((area, "tools/list (discovery)", True, f"{len(tools)} tools", 0.0))
            ctx: dict[str, Any] = {}
            for name, args in plan(ctx):
                resolved = {k: _resolve(v, ctx) for k, v in args.items()}

                async def invoke(name: str = name, resolved: dict[str, Any] = resolved) -> str:
                    res = await session.call_tool(name, resolved, meta={"trace_id": "smoke-test"})
                    if res.isError:
                        raise RuntimeError(res.content[0].text[:100] if res.content else "tool error")
                    data = res.structuredContent or {}
                    if name == "search_assets":
                        ctx["asset"] = data["results"][0]["asset_id"]
                    if name == "get_alarms":
                        ctx["alarm"] = data["alarms"][0]["alarm_id"]
                    if name == "search_documents":
                        ctx["chunk"] = data["results"][0]["chunk_id"]
                    retries = data.get("trace", {}).get("retries")
                    return "ok" + (f" ({retries} retr{'y' if retries == 1 else 'ies'})" if retries else "")

                await check(area, name, invoke)
    except Exception as exc:  # noqa: BLE001
        results.append((area, "connect", False, f"{type(exc).__name__}: {exc}"[:110], 0.0))


def alarm_plan(_: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("search_assets", {"query": "Boiler Feed Pump 101", "limit": 3}),
        ("get_asset_metadata", {"asset_id": "$asset"}),
        ("get_alarms", {"asset_id": "$asset", "page_size": 20}),
        ("get_alarm_details", {"alarm_id": "$alarm"}),
        ("summarize_alarms", {"asset_ids": ["$asset"], "lookback_days": 90}),
        ("get_alarm_trends", {"asset_ids": ["$asset"], "lookback_days": 90, "bucket": "weekly"}),
        ("correlate_alarms", {"asset_ids": ["$asset"], "lookback_days": 90}),
        ("score_alarm_priority", {"alarm_id": "$alarm"}),
        ("get_operator_recommendations", {"alarm_id": "$alarm"}),
        ("analyze_alarm_flood", {"unit": "Unit 2", "lookback_days": 90}),
        ("find_rationalization_candidates", {"unit": "Unit 4", "lookback_days": 90}),
        ("calculate_kpi", {"calculation_type": "nuisance_alarm_score", "unit": "Unit 4"}),
        ("list_kpi_definitions", {}),
    ]


def docs_plan(_: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("search_documents", {"query": "restart pump after low suction pressure trip", "top_k": 3}),
        ("get_document_section", {"chunk_id": "$chunk"}),
        ("list_documents", {}),
    ]


# ---------------------------------------------------------------------------- copilot API
async def copilot(http: httpx.AsyncClient) -> None:
    async def health() -> str:
        r = await http.get(f"{COPILOT}/api/health")
        r.raise_for_status()
        return f"llm={r.json()['llm_provider']}"

    async def tools() -> str:
        r = await http.get(f"{COPILOT}/api/tools")
        r.raise_for_status()
        return f"{len(r.json()['tools'])} tools discovered via MCP"

    async def chat(message: str, expect: str) -> str:
        r = await http.post(f"{COPILOT}/api/chat", json={"message": message}, timeout=90)
        r.raise_for_status()
        body = r.json()
        conf = body["answer"]["confidence"]
        assert conf in expect.split("|"), f"confidence {conf}, expected {expect}"
        return f"confidence {conf}, {len(body['citations'])} citations, {len(body['tool_trace'])} trace steps"

    await check("Copilot API", "GET /api/health", health)
    await check("Copilot API", "GET /api/tools", tools)
    await check("Copilot API", "POST /api/chat (acceptance scenario)", lambda: chat(ACCEPTANCE, "high|medium"))
    await check(
        "Copilot API",
        "POST /api/chat (degraded scenario)",
        lambda: chat("Investigate alarms for Cooling Water Pump 301", "medium|low"),
    )


async def main() -> int:
    async with httpx.AsyncClient(timeout=30) as http:
        await alarm_api(http)
        await mcp_server("MCP alarm-management", MCP_URL, MCP_TOKEN, alarm_plan)
        await mcp_server("MCP document-knowledge", DOCS_URL, DOCS_TOKEN, docs_plan)
        await copilot(http)

    width = max(len(r[1]) for r in results)
    area = ""
    for a, name, ok, detail, ms in results:
        if a != area:
            print(f"\n{a}")
            area = a
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {ms:7.0f} ms  {detail}")
    failed = sum(1 for r in results if not r[2])
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
