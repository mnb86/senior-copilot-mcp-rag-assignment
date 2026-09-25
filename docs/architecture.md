# Architecture

![Architecture diagram](architecture-diagram.png)

(Source: [`architecture-diagram.svg`](architecture-diagram.svg).)

## 1. Components and boundaries

| Layer | Component | Location | Responsibility |
| --- | --- | --- | --- |
| UI | GUI | `apps/frontend` | React. Chat panel (conversation + message box) on the right; the selected answer's report in the middle (Overview: assessment, asset and KPIs, likely causes, action verdicts, alarms; Evidence: citations and quarantined passages; Execution trace: waves, JSON-RPC request/response, upstream API calls, retries; Tool catalog: live discovery); case history and saved scenarios on the left. Talks only to the copilot API. |
| Copilot | API | `copilot/api.py` | HTTP surface, request validation and size limits, CORS, error envelopes, lifespan wiring. |
| Copilot | Orchestrator | `copilot/orchestrator.py` | Runs one request end to end: intent → plan → MCP session → execution → reasoning → answer; context retention; structured request log. |
| Copilot | Intent + entities | `copilot/intent.py` (+ `llm.refine_intent`) | Classifies into 7 intents and extracts asset, equipment type, site, unit, alarm terms, severity, status, window and context references. |
| Copilot | Planner | `copilot/planner.py` | Builds a **data plan**: `PlanStep`s (MCP tool or RAG) whose arguments reference **bindings** produced by named **selectors** over earlier outputs. |
| Copilot | Executor | `copilot/executor.py` | Resolves dependencies, runs ready steps in parallel **waves**, supports `foreach` fan-out, isolates failures (error/skip), records a `ToolCallRecord` per call. |
| Copilot | Reasoning | `copilot/reasoning.py` | Summary panel, likely causes (correlation, precursors, recurrence, trend) with tool and document evidence, API-recommendation vs procedure check, citations. |
| Copilot | Composer / LLM | `copilot/composer.py`, `copilot/llm.py` | Grounded Markdown answer (template, or LLM with citation validation and an unsafe-advice guard). Replaceable provider. |
| Copilot | MCP client | `copilot/mcp_client.py` | Streamable-HTTP `ClientSession`, discovery cache, client-side JSON-Schema validation, output-schema check, read-only policy, error parsing. |
| Copilot | Retrieval service | `copilot/retrieval_service.py` | Loads the index (auto-ingest), multi-query fusion, guaranteed evidence for verification queries. |
| Tools | MCP server | `mcp-servers/alarm-management/alarm_mcp` | 13 typed read-only tools, validation, error mapping, trace, bearer auth, allow-list, `/healthz`, HTTP + stdio. |
| Tools | Secondary MCP server | `mcp-servers/optional-secondary-server/document_mcp` | `document-knowledge`: 3 read-only tools over the RAG index (search with citations, section lookup, document list), quarantine refusal, bearer auth, `/healthz`, HTTP + stdio. |
| Tools | API connector | `connectors/` | Auth, trace headers, timeout, retry/backoff, typed errors, pagination, attempt audit. Reusable outside MCP. |
| Source | Alarm API simulator | `apps/backend/alarm_simulator` | Postman-contract implementation, deterministic data, fault injection. |
| Knowledge | Ingestion | `rag/ingestion` | Discover → extract → chunk → injection scan and redaction → index; idempotent. |
| Knowledge | Retrieval | `rag/retrieval` | BM25 + LSA hybrid, filters/boosts, fallback, quarantine, low-confidence. |
| Knowledge | Document store / index | `rag/documents`, volume `rag-index` | Corpus and persisted index. |
| Domain | Models | `copilot/domain.py`, `alarm_mcp/models.py`, `rag/retrieval/models.py` | Typed contracts on every boundary (Pydantic). |
| Config | Settings | `copilot/config.py`, `alarm_mcp/config.py`, `document_mcp/config.py` | Env-only configuration, `SecretStr` secrets. |
| Observability | Logs + trace | every service | JSON log lines keyed by `trace_id`; the trace is also returned to the GUI. |

**Authentication boundaries.** (1) Browser → copilot API: input validation and size limits (no user auth in this
scope). (2) Copilot → MCP server: `Authorization: Bearer $MCP_SERVER_TOKEN`, checked with constant-time compare.
(3) MCP server → Alarm API: `Authorization: Bearer $ALARM_API_TOKEN`, held only by the MCP server. The copilot never
sees the API token and **cannot call the API directly** (it has no connector; only MCP). (4) MCP client →
`document-knowledge` server: `Authorization: Bearer $DOCS_MCP_SERVER_TOKEN`; the server mounts the index read-only.

## 2. Request flow (acceptance scenario)

> "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely
> contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source
> evidence."

1. **GUI → `POST /api/chat`** with `{message, conversation_id}`. The API validates the body (≤ 2,000 chars, id
   pattern, ≤ 16 KB).
2. **Intent + entities.** `investigate` (0.93): asset "Boiler Feed Pump 101" (specific), severities
   `[high, critical]`, window 90 days. With an LLM configured, the rule result is refined and **validated** against
   the `Entities` schema; any failure keeps the rule result.
3. **Plan** (data, not code):
   `resolve_asset(search_assets)` → {`asset_metadata`, `alarms` (all pages), `summary`, `trend`, `correlation`} →
   {`priority`, `recommendations`} → `retrieve_documents (RAG)`. Bindings: `asset_id = best_asset(resolve_asset)`,
   `primary_alarm_id = primary_alarm(alarms)` (active first, then most recurrent), and
   `rag_request = build_rag_request(all MCP outputs)`.
4. **MCP session:** open streamable HTTP with the bearer token → `initialize` → **`tools/list`** (discovery is
   recorded as wave 0 in the trace and cached for 60 s).
5. **Execution waves** (each call carries `_meta.trace_id / conversation_id / client_id / step_id`; arguments are
   validated client-side against the discovered `inputSchema`):
   - wave 1: `search_assets` → `AST-BFP-101`
   - wave 2 (parallel): `get_asset_metadata`, `get_alarms` (follows `pagination.has_next` across pages), `summarize_alarms`, `get_alarm_trends`,
     `correlate_alarms` (the simulator's transient 503 is retried inside the MCP server; `retries: 1` appears in the
     trace)
   - wave 3 (parallel): `score_alarm_priority`, `get_operator_recommendations` for the selected focus alarm
   - wave 4: **RAG** with queries built from the MCP results (focus alarm + asset type, the user message, correlated
     causes, and each API recommendation as a verification query) and filters `site=NorthPlant`,
     `asset_types=[pump]`, boosts for the asset and its related assets and for the alarm names.
6. **MCP server** per call: Pydantic validation of arguments → semantic checks → connector call with auth and trace
   headers, timeout and retries → typed result + `trace.api_calls[]` → `structuredContent` validated against the
   `outputSchema`. Errors become `isError` results with a stable code.
7. **Reasoning:** summary panel; causes, where correlation `Deaerator Low Level → Low Suction Pressure` (69%, 9
   times) is corroborated by SOP-DEA-002 / SOP-BFP-001; recommendation check, where "restart immediately" conflicts
   with SOP-BFP-001 §4; citations S1..Sn.
8. **Answer:** the template composer (or LLM) writes Markdown with `[S#]` markers and tool names; citations are
   validated and the output guard blocks advice to bypass or disable protections; a *request* to bypass or disable one
   is refused at the top of the answer (`unsafe_request` flag). Confidence is high/medium/low depending on MCP
   coverage, retrieval confidence and errors.
9. **Context** (asset, focus alarm, API recommendations) is stored for follow-ups like "Are the API recommendations
   consistent with the maintenance manual?".
10. **Response** includes `answer`, `alarm_summary`, `likely_causes`, `recommendations`, `citations`, `retrieval`
    diagnostics, the full `tool_trace` (JSON-RPC request, response, upstream API attempts), `plan`, `warnings`,
    `errors` and `timings`. The GUI shows the answer in the chat panel and the rest in the report tabs.

## 3. Failure handling

| Failure | Where handled | Result |
| --- | --- | --- |
| Transient upstream 429/5xx/timeout | connector retry with backoff and jitter | success with `retries > 0`, shown as a note |
| Persistent upstream failure | connector → typed error → MCP `isError` (`UPSTREAM_UNAVAILABLE`) | step `error`, answer degraded (medium confidence), procedure guidance still given |
| Invalid arguments | client JSON-Schema check (before the network) and server Pydantic/semantic checks | `INVALID_ARGUMENT` recorded; plan continues |
| Tool missing from discovery | executor | step `skipped` with `TOOL_NOT_FOUND`, dependants skipped, answer continues |
| MCP server down or wrong token | gateway (`MCP_UNAVAILABLE`) | all MCP steps skipped, RAG-only answer, error banner |
| Unresolvable asset | selector raises `SelectorError` | clarification request, dependent steps collapsed into one note |
| Low-confidence or no retrieval | retriever | explicit low-confidence disclaimer, no invented guidance |
| Injected instructions in documents | ingestion flag + retrieval quarantine + prompt isolation + output guard | chunk excluded and listed in the GUI |
| LLM failure / invalid JSON / unsafe output | llm module | deterministic template answer + warning |
| User asks to bypass or disable a protection | orchestrator (same pattern as the output guard) | refusal at the top of the answer, `unsafe_request` safety flag, read-only evidence still shown |
| How-to question with no asset, site or context | intent rules | answered from documents (no MCP calls) instead of asking for an asset |
| "Investigate" with no asset, site or context | intent rules + planner | clarification: asks which asset to investigate |

## 4. Observability

Every service logs one JSON line per unit of work:

- simulator: `http_request` (method, path, status, duration, trace_id, client_id, request_id)
- connector: `alarm_api_call` (status, attempt, duration, trace_id)
- MCP servers: `mcp_tool_call` (server, tool, outcome, api_status, trace_id, conversation_id, duration; the
  document server adds doc ids and top confidence)
- copilot: `copilot_request` (request_id, conversation_id, trace_id, intent, confidence, generator, per-tool
  mcp_server/tool/status/duration/retries/api_status, retrieval query, doc ids, scores, `llm_latency_ms` (null in
  offline mode), timings)

Example (abridged: one tool entry shown, values from two runs of the acceptance scenario):

```json
{"event": "copilot_request", "request_id": "066a1ee3fdbd4b06", "conversation_id": "e074bb5a50af",
 "trace_id": "trace-55fce18d11464ed6", "intent": "investigate", "confidence": "high", "generator": "template",
 "tools": [{"mcp_server": "alarm-management", "tool": "correlate_alarms", "status": "ok", "duration_ms": 332.6,
            "retries": 1, "api_status": 200}],
 "retrieval": {"query": "Low Suction Pressure Boiler Feed Pump 101 pump alarm response procedure | ...",
               "doc_ids": ["SOP-BFP-001#3-low-suction-pressure-alarm-bfp-pt-001-"], "scores": [1.0805]},
 "llm_latency_ms": null, "timings": {"execution_ms": 335.6, "total_ms": 370.5}}
```

`trace_id` is created per chat request and propagated GUI response ← copilot → MCP `_meta` → API `trace_id` header, so
one `grep trace-…` follows a request across all four services. Logs never contain tokens or full documents.

## 5. Deployment

`docker compose up --build` builds one Python image (five roles by `command`: simulator, alarm MCP server, document
MCP server, ingestion job, copilot backend) and an nginx image for the GUI. Health checks gate start-up:
`alarm-api` → `alarm-mcp` → `copilot-backend` → `frontend`, and `rag-ingest` must complete before `copilot-backend` and
`docs-mcp` start. The index lives on the named volume `rag-index` (read-only for `docs-mcp`); containers run as a
non-root user. Without Docker, `python scripts/run_local.py` starts the same services.
