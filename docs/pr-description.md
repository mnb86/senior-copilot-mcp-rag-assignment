# PR: Alarm investigation copilot - MCP server, MCP client, document RAG and GUI

## Summary
Implements the Alarm Investigation and Procedure Guidance Copilot as one vertical slice: an Alarm Management API
simulator (Postman contract), a candidate-developed MCP server with 13 typed tools, an MCP-client-based orchestrator
that chains tools and feeds RAG from their outputs, a hybrid RAG pipeline with citations and injection protection,
and a React GUI with a full execution trace.

## Scope
- `apps/alarm-api-simulator` - contract implementation, deterministic data, fault injection
- `mcp-servers/alarm-management` + `connectors/alarm_api` - MCP server and reusable API connector
- `apps/backend` - copilot API, intent/planner/executor, MCP client, reasoning, composer, LLM providers
- `rag/` - corpus, ingestion, retrieval, tests
- `apps/frontend` - GUI
- Docker Compose, Makefile, CI, docs

## Architecture changes
See `docs/architecture.md` and `docs/architecture-diagram.png`. There are auth boundaries at copilot→MCP and
MCP→API; the copilot has no direct API access.

## MCP tools added
search_assets, get_asset_metadata, get_alarms, get_alarm_details, summarize_alarms, get_alarm_trends,
correlate_alarms, score_alarm_priority, get_operator_recommendations, analyze_alarm_flood,
find_rationalization_candidates, calculate_kpi, list_kpi_definitions (`docs/mcp-tool-catalog.md`).

## RAG workflow added
10 documents (md/txt/html/pdf) → heading-aware chunks → BM25 + LSA hybrid index; filters and verification queries
derived from MCP data; quarantine of injected content; citations S1..Sn (`docs/rag-design.md`).

## Screenshots
`docs/screenshots/02-acceptance-investigation.png`, `04-acceptance-mcp-trace.png`, `05-consistency-conflict.png`,
`06-degraded-recommendations-unavailable.png`, `07-mcp-tool-discovery.png`, `08-prompt-injection-quarantine.png`.

## Test evidence
- `make test`: 128 passed (unit, RAG, MCP server, MCP client over HTTP, orchestration, e2e)
- `make lint` / `make typecheck`: clean
- Postman collections: 15/15, 32/32, 15/15 passing against the simulator
- Coverage: `docs/coverage-summary.md` (pytest-cov artifact in CI)

## Design decisions
`docs/design-decisions.md` (deterministic data plans, RAG as a plan step, offline-first LLM, hybrid local
retrieval, defence-in-depth against injection).

## Known limitations
`docs/known-limitations.md`.

## Review checklist
- [x] Copilot calls the Alarm API only through the MCP server
- [x] Tools have typed input/output schemas, validation, error mapping and tests
- [x] Answers carry citations and an MCP trace
- [x] No secrets committed; `.env.example` provided
- [x] Lint, types and tests pass
- [x] Docs updated
