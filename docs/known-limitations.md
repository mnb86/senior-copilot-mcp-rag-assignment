# Known limitations and future improvements

## Known limitations

1. **Rule-based language understanding by default.** Intent and entity extraction use domain rules. They cover the
   alarm-investigation intents (investigate, site priority, related assets, procedure lookup, recommendation check,
   KPIs, document questions) and robust follow-ups, but not arbitrary phrasing. With `LLM_PROVIDER` set, the LLM
   refines intent/entities (schema-validated) and writes the answer.
2. **The planner is deterministic.** Tool selection follows intent-specific plan templates parameterised by entities
   and discovery. It doesn't invent new tool sequences; an LLM-driven planner would plug in at the `Plan` model.
3. **Corpus-local embeddings.** LSA vectors are trained on the 51 chunks of this corpus; semantic recall on a large or
   very different corpus needs `EMBEDDING_PROVIDER=fastembed` (or a hosted model) and ideally a vector database.
4. **Heuristic conflict detection.** Recommendation vs procedure checks match prohibition clauses ("do not …",
   "… is prohibited") and action verbs; paraphrased contradictions without such wording can be missed (reported as
   "not covered", never as "consistent" without support).
5. **In-memory conversation store.** Context is lost on restart and not shared across backend replicas (the
   `ConversationStore` interface is ready for Redis).
6. **No end-user authentication/authorization** on the GUI/copilot API; only the service-to-service boundaries
   (MCP and API bearer tokens) are enforced. Tokens are static shared secrets (no OAuth / rotation).
7. **Read-only scope.** No ticketing or write tools are implemented. The client policy blocks non-read-only tools
   without explicit confirmation, but there is no confirmation UI yet.
8. **Copilot RAG runs in-process.** The `document-knowledge` MCP server (`mcp-servers/optional-secondary-server`)
   exposes the corpus to external MCP clients, but the copilot still calls the retrieval service in-process for its
   RAG step (multi-query fusion needs the raw ranked chunks). Future work: route the RAG step through
   `search_documents` so both sources appear in one MCP trace.
9. **Synthetic data and documents.** Patterns (causal chains, conflicts, faults) are designed to exercise the
   workflow; they are not real plant data.
10. **Loosely matched sources for undocumented equipment.** When the corpus has no document for an asset type
    (e.g. Forced Draft Fan 301), retrieval cites the closest general procedures and confidence can still be "high"
    because the MCP evidence is complete. A per-asset-type relevance check before citing would tighten this.
11. **Coverage gaps.** Line coverage is 94% (`docs/coverage-summary.md`); the uncovered lines are mostly defensive
    branches (unexpected upstream payloads, provider-specific LLM errors) that are hard to trigger without fault
    injection in every dependency.
12. **No streaming.** Answers are returned when the plan completes (typically 0.3–1.5 s offline).

## Future improvements

- LLM-planned tool chains (validated against discovered schemas) with the deterministic plans as guard rails and
  fallback.
- Server-sent progress events: stream wave-by-wave tool execution to the GUI.
- Vector database (Qdrant/pgvector) + neural embeddings + cross-encoder reranking; extend the relevance suite over
  `test-data/retrieval_eval.json` (already run in CI) with recall@k / MRR metrics and more queries.
- NLI-based consistency checking between recommendations and procedures.
- A ticketing MCP server with write tools behind explicit, audited user confirmation (a confirmation UI in the chat
  panel); route the copilot's RAG step through the existing `document-knowledge` MCP server.
- OAuth2 / OIDC for users, per-tool authorization scopes on the MCP server, secret rotation via a vault.
- OpenTelemetry traces and metrics (the `trace_id` propagation already matches the span model), dashboards for tool
  latency and error rates.
- Redis conversation store, horizontal scaling of the stateless MCP server behind a load balancer.
- Browser-driven GUI tests in CI (the screenshots in `docs/screenshots` are produced by `scripts/capture_screenshots.mjs`,
  which drives headless Edge over the DevTools protocol).
