# Design decisions

| # | Decision | Alternatives considered | Rationale |
| --- | --- | --- | --- |
| 1 | **Official MCP Python SDK (FastMCP) + streamable HTTP**, stateless, JSON responses | SSE transport; custom JSON-RPC | Standard transport the brief's `MCP_SERVER_URL` implies; stateless mode scales horizontally and survives restarts; stdio is also supported for desktop clients and the MCP Inspector. |
| 2 | **Separate connector package** under the MCP server | HTTP calls inside tool functions | Auth, retries, error typing and pagination are source-system concerns. The connector is unit-tested with `MockTransport`/`ASGITransport` and reusable by a second MCP server. |
| 3 | **Typed input *and* output schemas** (Pydantic return models → `outputSchema`, `structuredContent`) | text-only results | Machine-checkable contracts both ways; the client validates arguments before sending and results after receiving. |
| 4 | **Stable error codes in a JSON payload** inside `isError` results | raising raw exceptions | Clients can branch on `code`/`retryable`/`attempts`; the GUI shows the upstream attempts. |
| 5 | **Trace via MCP `_meta`**, forwarded as the Postman trace headers | custom HTTP headers on the MCP transport | `_meta` is per call and transport-agnostic (also works over stdio). |
| 6 | **Deterministic, data-driven planner** (plan + bindings + selectors) with an optional LLM for intent refinement and writing | a free-form LLM tool-calling agent | Industrial safety context: plans are auditable, reproducible and testable offline; tool choice is still driven by discovery (missing tools are skipped). The seam for an agentic planner is the `Plan` model. |
| 7 | **Executor with dependency waves** and `foreach` | sequential calls | Independent MCP calls run in parallel (five in wave 2 of the acceptance scenario); failure isolation per step; output passing is explicit and visible in the trace. |
| 8 | **RAG is a step in the same plan, fed by MCP outputs** | a separate retrieval call before tools | Makes MCP and RAG one workflow: filters come from asset metadata and correlation, and verification queries come from API recommendations. |
| 9 | **Recommendation vs procedure check** (prohibition-clause matching, guarded-action detection, trust levels) | leave it to the LLM | Works without an LLM, is testable, and gives the LLM (when used) a vetted verdict to explain. Procedures take precedence per the alarm philosophy (AP-ALM-001 §6). |
| 10 | **Hybrid BM25 + LSA with an on-disk index** | vector DB + hosted embeddings | No keys and no extra containers, deterministic, fast to build (~50 ms), good lexical precision on tags and alarm names. `fastembed` and a vector DB can be swapped in behind `Embedder`/`RetrievalIndex`. |
| 11 | **Absolute confidence separate from ranking score** | threshold on the fused score | Ranking scores are relative (normalised by the max); coverage + cosine gives a comparable low-confidence signal. |
| 12 | **Defence-in-depth against prompt injection** (redact at ingestion, quarantine at retrieval, isolate at generation, guard the output) | prompt-only mitigation | Each layer is testable; the planted vendor note demonstrates it end to end. |
| 13 | **Offline template answer by default**, LLM optional and validated | LLM required | Evaluators can run everything without secrets; the LLM path falls back safely (invalid citations stripped, unsafe advice rejected). |
| 14 | **Starlette** for the HTTP services | FastAPI | Same ASGI foundation; request/response contracts are explicit Pydantic models. It keeps dependencies minimal (FastAPI would add OpenAPI docs, a possible future addition). |
| 15 | **Simulator anchored to "today"** with a fixed seed | fixed calendar dates | "Last 90 days" always has data regardless of when the stack is run; tests pin `SIM_ANCHOR_TIME`. |
| 16 | **Fault injection per trace and per client** | random failures | Deterministic demos of retry (transient) and degradation (persistent) without breaking the Postman contract runs. |
| 17 | **One Python image, four roles** | one image per service | Faster builds, identical dependency set; roles are selected by the compose `command`. |
| 18 | **No `dangerouslySetInnerHTML`**; a tiny Markdown tokenizer renders React nodes | a Markdown library | Output encoding by construction (XSS-safe) with no extra dependency. |
