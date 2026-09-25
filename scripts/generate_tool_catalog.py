"""Generate docs/mcp-tool-catalog.md from the live MCP server definitions + real example calls.

Covers both servers: ``alarm-management`` (mcp-servers/alarm-management) and the secondary
``document-knowledge`` server (mcp-servers/optional-secondary-server).

Run: make catalog
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import httpx

from alarm_mcp.config import ServerSettings
from alarm_mcp.server import ID_PATTERN, create_server
from alarm_simulator.app import SimSettings, create_app
from alarm_simulator.store import parse_time
from connectors import AlarmApiClient, AlarmApiSettings
from document_mcp.config import DocServerSettings
from document_mcp.server import create_server as create_doc_server
from rag.ingestion import ingest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "mcp-tool-catalog.md"
W = {"start_time": "2026-04-02T00:00:00Z", "end_time": "2026-07-01T00:00:00Z"}

API_OP = {
    "search_assets": "`GET /assets/search?query&limit&site&unit`",
    "get_asset_metadata": "`GET /assets/{asset_id}/metadata`",
    "get_alarms": "`GET /alarms` (filters, `page`/`page_size`, `sort_by`/`sort_order`; follows `pagination.has_next`)",
    "get_alarm_details": "`GET /alarms/{alarm_id}`",
    "summarize_alarms": "`POST /alarms/summary`",
    "get_alarm_trends": "`POST /alarms/trends`",
    "correlate_alarms": "`POST /alarms/correlation` (method `cooccurrence`)",
    "score_alarm_priority": "`POST /alarms/priority-score`",
    "get_operator_recommendations": "`POST /recommendations/operator-actions`",
    "analyze_alarm_flood": "`POST /alarms/flood-analysis`",
    "find_rationalization_candidates": "`POST /alarms/rationalization-candidates`",
    "calculate_kpi": "`POST /calculation-code/generate` then `POST /calculation-code/execute` (chained)",
    "list_kpi_definitions": "`GET /analytics/kpi-definitions`",
}
SPECIFIC_ERRORS = {
    "search_assets": "Empty result is not an error (`results: []`, `total: 0`).",
    "get_asset_metadata": "`NOT_FOUND` (404, upstream `ASSET_NOT_FOUND`) for unknown ids.",
    "get_alarms": "`INVALID_ARGUMENT` when no scope (asset_id/site/unit) is given or end <= start.",
    "get_alarm_details": "`NOT_FOUND` (404, upstream `ALARM_NOT_FOUND`).",
    "summarize_alarms": "`INVALID_ARGUMENT` without scope, window > 366 days or end <= start.",
    "get_alarm_trends": "`INVALID_REQUEST` (400 `TOO_MANY_BUCKETS`) for hourly buckets over very long windows.",
    "correlate_alarms": "Transient `503` is retried; `UPSTREAM_UNAVAILABLE` after retries are exhausted.",
    "score_alarm_priority": "`NOT_FOUND` for unknown alarm ids.",
    "get_operator_recommendations": "`UPSTREAM_UNAVAILABLE` (503 `RECOMMENDATION_ENGINE_UNAVAILABLE`) e.g. SouthPlant.",
    "analyze_alarm_flood": "`INVALID_ARGUMENT` when neither site nor unit is given.",
    "find_rationalization_candidates": "`INVALID_ARGUMENT` without scope.",
    "calculate_kpi": "`NOT_FOUND` if the generated calculation expired; `INVALID_REQUEST` for bad filters.",
    "list_kpi_definitions": "-",
}
EXAMPLES: dict[str, dict[str, Any]] = {
    "search_assets": {"query": "Boiler Feed Pump 101", "limit": 3},
    "get_asset_metadata": {"asset_id": "AST-BFP-101"},
    "get_alarms": {"asset_id": "AST-BFP-101", "status": "active", "page_size": 2},
    "get_alarm_details": {"alarm_id": "<from get_alarms>"},
    "summarize_alarms": {
        "asset_ids": ["AST-BFP-101"],
        **W,
        "severity": ["high", "critical"],
        "group_by": ["alarm_name"],
        "kpis": ["alarm_count", "recurring_rate", "avg_ack_delay"],
    },
    "get_alarm_trends": {"asset_ids": ["AST-BFP-101"], **W, "bucket": "weekly"},
    "correlate_alarms": {"asset_ids": ["AST-BFP-101"], **W, "lag_window_minutes": 15, "min_support": 2},
    "score_alarm_priority": {"alarm_id": "<from get_alarms>"},
    "get_operator_recommendations": {"alarm_id": "<from get_alarms>"},
    "analyze_alarm_flood": {"unit": "Unit 2", **W},
    "find_rationalization_candidates": {"unit": "Unit 4", **W, "recurrence_threshold": 8},
    "calculate_kpi": {"calculation_type": "nuisance_alarm_score", "unit": "Unit 4", **W},
    "list_kpi_definitions": {},
}

DOC_OP = {
    "search_documents": "Hybrid BM25 + dense search over the RAG index (`rag.retrieval.HybridRetriever`)",
    "get_document_section": "Chunk lookup in the RAG index by `chunk_id`",
    "list_documents": "RAG index manifest (`manifest.json`)",
}
DOC_ERRORS = {
    "search_documents": "Blank query -> `INVALID_ARGUMENT`; no match -> `results: []`, `low_confidence: true` "
    "(not an error). Quarantined passages are listed in `quarantined`, never returned as text.",
    "get_document_section": "`NOT_FOUND` for unknown ids; `QUARANTINED` for sections flagged by the "
    "prompt-injection scanner.",
    "list_documents": "`INDEX_UNAVAILABLE` if no index exists and auto-ingest is off.",
}
DOC_EXAMPLES: dict[str, dict[str, Any]] = {
    "search_documents": {
        "query": "restart boiler feed pump after low suction pressure trip",
        "doc_types": ["operating_procedure"],
        "asset_ids": ["AST-BFP-101"],
        "top_k": 3,
    },
    "get_document_section": {"chunk_id": "<from search_documents>"},
    "list_documents": {"doc_type": "operating_procedure"},
}


def trim(v: Any, depth: int = 0) -> Any:
    if isinstance(v, list):
        return [trim(x, depth + 1) for x in v[:2]] + ([f"... {len(v) - 2} more"] if len(v) > 2 else [])
    if isinstance(v, dict):
        return {k: trim(x, depth + 1) for k, x in v.items()}
    return v


def type_name(v: dict[str, Any], fallback: str) -> str:
    """JSON-schema type, or the referenced model name for ``$ref`` properties."""
    return str(v.get("type") or v.get("$ref", f"#/{fallback}").rsplit("/", 1)[-1])


def schema_table(schema: dict[str, Any]) -> str:
    props = schema.get("properties", {})
    req = set(schema.get("required", []))
    rows = ["| Field | Type / constraints | Required | Default | Description |", "| --- | --- | --- | --- | --- |"]
    for name, p in props.items():
        variants = p.get("anyOf", [p])
        types = []
        for v in variants:
            if v.get("type") == "null":
                continue
            t = type_name(v, "object")
            if "enum" in v:
                t = " \\| ".join(f"`{e}`" for e in v["enum"])
            if t == "array":
                items = v.get("items", {})
                inner = " \\| ".join(f"`{e}`" for e in items["enum"]) if "enum" in items else type_name(items, "any")
                t = f"array of {inner}"
            cons = [
                f"{k}={v[k]}"
                for k in ("minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "pattern", "format")
                if k in v
            ]
            if "items" in v and "pattern" in v["items"]:
                cons.append(f"items.pattern={v['items']['pattern']}")
            types.append(t + (f" ({', '.join(cons)})" if cons else ""))
        default = json.dumps(p["default"]) if "default" in p else ""
        rows.append(
            f"| `{name}` | {'; '.join(types) or 'object'} | {'yes' if name in req else ''} | {default} | "
            f"{p.get('description', '')} |"
        )
    return "\n".join(rows)


def tool_section(
    t: Any, args: dict[str, Any], res: Any, operation: str, auth: str, errors: str, timeout: str
) -> list[str]:
    return [
        "",
        f"### {t.name}",
        "",
        f"**{t.title}.** {t.description}",
        "",
        f"- **Underlying operation:** {operation}",
        f"- **Authentication:** {auth}",
        f"- **Errors:** common mapping (above). {errors}",
        f"- **Timeout:** {timeout}",
        "",
        "**Input schema**",
        "",
        schema_table(t.inputSchema),
        "",
        "**Output schema**",
        "",
        schema_table(t.outputSchema or {}),
        "",
        "<details><summary>Full input / output JSON Schema</summary>",
        "",
        "```json",
        json.dumps({"inputSchema": t.inputSchema, "outputSchema": t.outputSchema}, indent=2),
        "```",
        "",
        "</details>",
        "",
        "**Example invocation** (`tools/call`)",
        "",
        "```json",
        json.dumps({"name": t.name, "arguments": args, "_meta": {"trace_id": "trace-demo-001"}}, indent=2),
        "```",
        "",
        "**Example response** (`structuredContent`, lists truncated)",
        "",
        "```json",
        json.dumps(trim(res), indent=2)[:3500],
        "```",
    ]


async def alarm_server_lines() -> list[str]:
    sim = create_app(SimSettings(token="doc", anchor=parse_time("2026-07-01T00:00:00Z")))
    client = AlarmApiClient(AlarmApiSettings(base_url="http://sim", token="doc"), transport=httpx.ASGITransport(sim))
    mcp = create_server(ServerSettings(), client)
    tools = await mcp.list_tools()
    _, alarms = await mcp.call_tool("get_alarms", {"asset_id": "AST-BFP-101", "status": "active"})
    alarm_id = alarms["alarms"][0]["alarm_id"]
    lines = [
        "## Server 1 - `alarm-management` (mcp-servers/alarm-management)",
        "",
        "**Transport:** streamable HTTP at `http://<host>:9000/mcp` (stateless, JSON responses) or stdio "
        "(`python -m alarm_mcp --transport stdio`).",
        "",
        "### Behaviour common to all tools",
        "",
        "| Aspect | Behaviour |",
        "| --- | --- |",
        "| Authentication (client -> MCP) | `Authorization: Bearer $MCP_SERVER_TOKEN` required on `/mcp` when the token "
        "is configured (401 otherwise). `/healthz` is public. |",
        "| Authentication (MCP -> API) | The server injects `Authorization: Bearer $ALARM_API_TOKEN`. The token never "
        "appears in tool results, traces or logs (SecretStr, redacted repr). |",
        "| Authorization | All tools are read-only (`readOnlyHint=true`, `destructiveHint=false`). `MCP_ENABLED_TOOLS` "
        "restricts the exposed set. The copilot refuses non-read-only tools without explicit user confirmation. |",
        "| Input validation | JSON Schema from typed signatures (Pydantic): enums, ranges, id patterns "
        "`" + ID_PATTERN + "`, list sizes; plus semantic checks (scope required, "
        "end > start, window <= 366 days). |",
        "| Output | `structuredContent` validated against the tool `outputSchema`; every result has a `trace` object "
        "(`trace_id`, `tool`, `duration_ms`, `retries`, `api_calls[]` with method, path, params, body, status, "
        "attempt, outcome, request_id). |",
        "| Timeouts | Per-HTTP-attempt timeout `ALARM_API_TIMEOUT_SECONDS` (default 10 s) -> `UPSTREAM_TIMEOUT`. The "
        "copilot additionally applies `MCP_TIMEOUT_SECONDS` (default 30 s) per tool call. |",
        "| Retries | `ALARM_API_MAX_RETRIES` (default 2) with exponential backoff + jitter (honours `Retry-After`) for "
        "429 / 502 / 503 / 504, timeouts and connection errors. 4xx are never retried. |",
        "| Trace propagation | `_meta.trace_id`, `_meta.conversation_id`, `_meta.client_id` from the MCP request are "
        "forwarded as `trace_id`, `x-client-id`, `x-metadata-tag`, `x-request-id` headers to the API. |",
        '| Error format | `isError=true` result whose text is `{"error": {"code", "message", "http_status", '
        '"upstream_code", "retryable", "attempts", "trace_id", "details"}}`. Codes: `INVALID_ARGUMENT`, '
        "`NOT_FOUND`, `INVALID_REQUEST`, `AUTHENTICATION_FAILED`, `RATE_LIMITED`, `UPSTREAM_UNAVAILABLE`, "
        "`UPSTREAM_TIMEOUT`, `CONNECTION_FAILED`, `UNEXPECTED_RESPONSE`. Schema violations return the Pydantic "
        "validation message. |",
        "",
        "### Tools",
        "",
        "| Tool | Purpose | API operation |",
        "| --- | --- | --- |",
    ]
    for t in tools:
        lines.append(f"| [`{t.name}`](#{t.name.replace('_', '-')}) | {t.title} | {API_OP[t.name]} |")
    for t in tools:
        args = {k: (alarm_id if v == "<from get_alarms>" else v) for k, v in EXAMPLES[t.name].items()}
        _, res = await mcp.call_tool(t.name, args)
        timeout = "per-attempt API timeout + retries as above" + (
            " (two API calls, each with its own timeout/retry budget)." if t.name == "calculate_kpi" else "."
        )
        auth = "MCP bearer token (client) -> API bearer token injected by the server."
        lines += tool_section(t, args, res, API_OP[t.name], auth, SPECIFIC_ERRORS[t.name], timeout)
    return lines


async def document_server_lines() -> list[str]:
    with tempfile.TemporaryDirectory() as index_dir:
        ingest(ROOT / "rag" / "documents", Path(index_dir), force=True)
        mcp = create_doc_server(DocServerSettings(RAG_INDEX_PATH=index_dir, DOCS_MCP_AUTO_INGEST=False))
        tools = await mcp.list_tools()
        _, hits = await mcp.call_tool("search_documents", DOC_EXAMPLES["search_documents"])
        chunk_id = hits["results"][0]["chunk_id"]
        lines = [
            "",
            "## Server 2 - `document-knowledge` (mcp-servers/optional-secondary-server)",
            "",
            "Optional secondary source: exposes the RAG corpus (operating procedures, maintenance manuals, "
            "troubleshooting guides, safety instructions, alarm philosophy) as read-only MCP tools, so any MCP "
            "client can retrieve cited procedure guidance. It reads the same index the ingestion pipeline builds.",
            "",
            "**Transport:** streamable HTTP at `http://<host>:9100/mcp` (stateless, JSON responses) or stdio "
            "(`python -m document_mcp --transport stdio`).",
            "",
            "### Behaviour common to all tools",
            "",
            "| Aspect | Behaviour |",
            "| --- | --- |",
            "| Authentication (client -> MCP) | `Authorization: Bearer $DOCS_MCP_SERVER_TOKEN` required on `/mcp` when "
            "configured (401 otherwise). `/healthz` is public. No upstream credentials (local index). |",
            "| Authorization | All tools are read-only (`readOnlyHint=true`, `destructiveHint=false`). |",
            "| Input validation | Typed signatures: `doc_types` enum, `top_k` 1-10, length limits, `chunk_id` pattern. |",
            "| Output | `structuredContent` validated against `outputSchema`; every result carries `trace` "
            "(`trace_id` from `_meta`, `tool`, `duration_ms`, `index_version` = corpus hash). |",
            "| Prompt-injection | Passage `text` is untrusted data. Chunks flagged at ingestion are never returned as "
            "text: search lists them under `quarantined`, `get_document_section` refuses with `QUARANTINED`. |",
            "| Timeouts | In-process index lookups (milliseconds, no network); the copilot's per-call "
            "`MCP_TIMEOUT_SECONDS` applies. The first call may build the index when `DOCS_MCP_AUTO_INGEST=true`. |",
            '| Error format | Same envelope as server 1: `{"error": {"code", "message", ...}}`. Codes: '
            "`INVALID_ARGUMENT`, `NOT_FOUND`, `QUARANTINED`, `INDEX_UNAVAILABLE`. |",
            "",
            "### Tools",
            "",
            "| Tool | Purpose | Operation |",
            "| --- | --- | --- |",
        ]
        for t in tools:
            lines.append(f"| [`{t.name}`](#{t.name.replace('_', '-')}) | {t.title} | {DOC_OP[t.name]} |")
        for t in tools:
            args = {k: (chunk_id if v == "<from search_documents>" else v) for k, v in DOC_EXAMPLES[t.name].items()}
            _, res = await mcp.call_tool(t.name, args)
            lines += tool_section(
                t,
                args,
                res,
                DOC_OP[t.name],
                "MCP bearer token (`DOCS_MCP_SERVER_TOKEN`); no upstream credentials.",
                DOC_ERRORS[t.name],
                "local index lookup (no upstream calls); client-side per-call timeout applies.",
            )
        return lines


async def main() -> None:
    header = [
        "# MCP Tool Catalog",
        "",
        "_Generated by `scripts/generate_tool_catalog.py` from the running server definitions and real example calls "
        "(simulator anchor 2026-07-01). Do not edit by hand._",
        "",
        "| Server | Folder | Tools | Default endpoint |",
        "| --- | --- | --- | --- |",
        "| `alarm-management` | `mcp-servers/alarm-management` | 13 | `http://localhost:9000/mcp` |",
        "| `document-knowledge` | `mcp-servers/optional-secondary-server` | 3 | `http://localhost:9100/mcp` |",
        "",
    ]
    lines = header + await alarm_server_lines() + await document_server_lines()
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
