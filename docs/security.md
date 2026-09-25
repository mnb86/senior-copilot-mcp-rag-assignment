# Security considerations

| Topic | Implementation |
| --- | --- |
| Secret management | Env-only configuration, `.env` git-ignored, `.env.example` with placeholders; `SecretStr` for `ALARM_API_TOKEN`, `MCP_SERVER_TOKEN`, `LLM_API_KEY`; connector `repr` masks the token; tests assert tokens never appear in results, traces or settings dumps; gitleaks in CI. |
| MCP tool authorization | Bearer token on `/mcp` (constant-time compare); all tools `readOnlyHint=true`; `MCP_ENABLED_TOOLS` allow-list; the client refuses non-read-only tools without explicit confirmation (`CONFIRMATION_REQUIRED`). |
| Input validation | Copilot API: Pydantic request model, 2,000-character message, id pattern, 16 KB body limit. MCP: JSON Schema (client) + Pydantic (server) + semantic checks. Simulator: request models with `extra="forbid"`, enum/range checks, whitelisted `sort_by`/`group_by`. |
| Injection (SQL/path) | No SQL anywhere (in-memory data); sort/group fields are allow-listed; path identifiers are regex-validated and URL-encoded as single segments. |
| Output encoding | The GUI renders Markdown through a tokenizer into React nodes (no `innerHTML`); nginx sends CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`. |
| Prompt injection | Ingestion redaction, retrieval quarantine, `<document>` isolation with an untrusted-data instruction, trust levels, citation validation and an unsafe-advice output guard (see rag-design.md §11). |
| Retrieved-document trust boundary | `trust_level` metadata; external documents are down-weighted and can't confirm or overrule recommendations. |
| Write-operation approval | No write tools are exposed; any future tool without `readOnlyHint` requires explicit user confirmation in the client policy. Ticket creation would follow the same path. |
| Tool misuse | Scope required for list/summary tools, window ≤ 366 days, page size and page count caps, `foreach` capped at 6 items with concurrency 4, request timeouts. |
| Logging | Structured logs contain ids, statuses and durations; no tokens, no full documents, no request bodies from the GUI. |
| Dependency risk | Pinned Python versions; `pip-audit` and `npm audit` in CI; minimal dependency set (no UI kit, no LLM SDKs). |
| Containers | Non-root user (uid 10001), slim base image, only the required ports published. |
