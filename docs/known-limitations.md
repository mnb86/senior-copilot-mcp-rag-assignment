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
8. **No `optional-secondary-server`.** Only the Alarm Management MCP server exists; documents are served by the
   in-process retrieval service rather than a second MCP server.
9. **Synthetic data and documents.** Patterns (causal chains, conflicts, faults) are designed to exercise the
   workflow; they are not real plant data.
10. **Frontend lockfile.** `package-lock.json` was not generated in the build environment (no registry access). CI
    and Docker run `npm install` and the npm audit job generates the lockfile first; commit a lockfile for fully
    reproducible frontend builds.
11. **Coverage number.** The committed `docs/coverage-summary.md` comes from a stdlib tracer
    (`scripts/coverage_lite.py`, counts executed lines of all code objects, about 95%); CI publishes the canonical
    `pytest-cov` report, which may differ by a few points.
12. **No streaming.** Answers are returned when the plan completes (typically 0.3–1.5 s offline).

## Future improvements

- LLM-planned tool chains (validated against discovered schemas) with the deterministic plans as guard rails and
  fallback.
- Server-sent progress events: stream wave-by-wave tool execution to the GUI.
- Vector database (Qdrant/pgvector) + neural embeddings + cross-encoder reranking; an evaluation harness (recall@k,
  MRR) over `test-data/retrieval_eval.json` in CI.
- NLI-based consistency checking between recommendations and procedures.
- Second MCP server for documents/ticketing, with write tools behind explicit, audited user confirmation.
- OAuth2 / OIDC for users, per-tool authorization scopes on the MCP server, secret rotation via a vault.
- OpenTelemetry traces and metrics (the `trace_id` propagation already matches the span model), dashboards for tool
  latency and error rates.
- Redis conversation store, horizontal scaling of the stateless MCP server behind a load balancer.
- Playwright GUI tests in CI (screenshots in `docs/screenshots` are already produced with Playwright).
