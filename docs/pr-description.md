# Alarm investigation copilot: MCP servers, MCP client, document RAG and GUI

## Summary
Implements the Alarm Investigation and Procedure Guidance Copilot as one vertical slice. An Alarm Management API
simulator implements the Postman contract. A candidate-developed MCP server exposes it as 13 typed tools, and a second
MCP server exposes the document corpus. The copilot discovers and chains the tools over MCP, feeds a hybrid RAG step
from their outputs, checks the API's recommendations against the procedures, and answers with citations and a full
execution trace in a React GUI. The mandatory acceptance scenario (Boiler Feed Pump 101, 90 days) runs end to end,
locally and under `docker compose up --build`.

## Scope
- [x] MCP server / tools: `mcp-servers/alarm-management` (13 tools) and `mcp-servers/optional-secondary-server` (3 tools)
- [x] MCP client / orchestration: `apps/backend/copilot` (intent, planner, executor, reasoning, composer, LLM providers)
- [x] RAG ingestion / retrieval: `rag/` (corpus, ingestion, hybrid retrieval, tests)
- [x] GUI: `apps/frontend` (chat panel, report tabs, execution trace, tool catalog)
- [x] Packaging / CI / docs: Dockerfile, `docker-compose.yml` (6 services, health-gated), Makefile, GitHub Actions, `docs/`
- Source system: `apps/backend/alarm_simulator` (Postman contract, deterministic data, fault injection); reusable
  connector in `connectors/`

## Architecture changes
New system; see `docs/architecture.md` and `docs/architecture-diagram.png`. The copilot has no API connector: it reaches
the Alarm Management API only through the MCP server. Authentication boundaries: copilot → MCP server (bearer token),
MCP server → Alarm API (bearer token held only by the MCP server), MCP client → document server (bearer token).
Structured JSON logs carry request, conversation and trace ids, MCP server and tool, duration, outcome, API status,
retries, retrieval query, document ids, scores and LLM latency.

## MCP tools added
- `alarm-management`: `search_assets`, `get_asset_metadata`, `get_alarms`, `get_alarm_details`, `summarize_alarms`,
  `get_alarm_trends`, `correlate_alarms`, `score_alarm_priority`, `get_operator_recommendations`,
  `analyze_alarm_flood`, `find_rationalization_candidates`, `calculate_kpi`, `list_kpi_definitions`
- `document-knowledge` (optional secondary source): `search_documents`, `get_document_section`, `list_documents`

Every tool has typed input and output schemas, validation, error mapping, timeouts and retries (alarm tools), and
trace metadata. Full contracts with example invocations and responses: `docs/mcp-tool-catalog.md`.

## RAG workflow added
10 synthetic documents (operating procedures, maintenance manuals, troubleshooting guides, a safety instruction PDF,
alarm philosophy and a vendor bulletin with a planted prompt injection) → extraction (md/txt/html/pdf) →
heading-aware chunking with overlap → metadata → injection scan and redaction → BM25 + LSA hybrid index. Filters and
verification queries are derived from the MCP results; injected passages are quarantined; citations are S1..Sn with
document, revision and section. Details: `docs/rag-design.md`.

## Screenshots
| Acceptance scenario | Execution trace (retry visible) |
| --- | --- |
| ![Acceptance scenario](https://github.com/mnb86/senior-copilot-mcp-rag-assignment/blob/feature/alarm-investigation-copilot/docs/screenshots/02-acceptance-investigation.png?raw=true) | ![Execution trace](https://github.com/mnb86/senior-copilot-mcp-rag-assignment/blob/feature/alarm-investigation-copilot/docs/screenshots/04-acceptance-mcp-trace.png?raw=true) |
| **Recommendation vs procedure conflict** | **Degraded source** |
| ![Conflict](https://github.com/mnb86/senior-copilot-mcp-rag-assignment/blob/feature/alarm-investigation-copilot/docs/screenshots/05-consistency-conflict.png?raw=true) | ![Degraded](https://github.com/mnb86/senior-copilot-mcp-rag-assignment/blob/feature/alarm-investigation-copilot/docs/screenshots/06-degraded-recommendations-unavailable.png?raw=true) |
| **MCP tool discovery** | **Prompt injection quarantined** |
| ![Tool discovery](https://github.com/mnb86/senior-copilot-mcp-rag-assignment/blob/feature/alarm-investigation-copilot/docs/screenshots/07-mcp-tool-discovery.png?raw=true) | ![Quarantine](https://github.com/mnb86/senior-copilot-mcp-rag-assignment/blob/feature/alarm-investigation-copilot/docs/screenshots/08-prompt-injection-quarantine.png?raw=true) |

All nine are in `docs/screenshots/` (regenerate with `make screenshots`).

## Test evidence
- `make test`: **146 passed** (unit 72, MCP server/client 34, RAG 22, orchestration 13, end-to-end 5); frontend: 7 passed
- Coverage: **94%** of lines (`docs/coverage-summary.md`; CI publishes the pytest-cov report as an artifact)
- `ruff check`, `ruff format --check`, `mypy`, `tsc`: clean
- Postman collections against the simulator: 15/15, 32/32, 15/15
- `docker compose up --build`: all five long-running services healthy, `rag-ingest` exits 0;
  `scripts/smoke_test.py` against the containers: **37/37** (every API endpoint, all 16 MCP tools, copilot API)
- `scripts/check_structure.py`: repository matches the required folder tree
- `pip-audit` and `npm audit`: no known vulnerabilities; no secrets in the working tree or history

## Design decisions
`docs/design-decisions.md`: deterministic, data-driven plans (auditable, testable offline) with an optional LLM;
RAG as a plan step fed by MCP outputs; offline-first answer generation with a replaceable LLM provider; local hybrid
retrieval instead of a vector database at this corpus size; defence in depth against prompt injection; read-only
tools with a confirmation policy for any write tool.

## Known limitations
`docs/known-limitations.md`. Main ones: rule-based intent detection unless an LLM is configured; corpus-local LSA
embeddings; in-memory conversation store; no end-user authentication; the copilot's own RAG step runs in-process
rather than through the document MCP server.

## Review checklist
- [x] Copilot calls the Alarm API only through the MCP server
- [x] Tools have typed input/output schemas, validation, error mapping and tests
- [x] MCP and RAG run in the same workflow; answers carry citations and an MCP trace
- [x] No secrets committed; `.env.example` covers every setting
- [x] Lint, types and tests pass; `docker compose up --build` verified
- [x] Docs updated: tool catalog, RAG design, architecture, screenshots
- [ ] Demo video (up to 10 minutes) linked in the README
