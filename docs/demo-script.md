# Demo video script (target 8–10 minutes)

Record the screen at 1440p or 1080p with `docker compose up --build` already running and the browser at
http://localhost:3000. Upload the video (GitHub release asset, Google Drive or YouTube unlisted) and put the link at
the top of the README.

| Time | Show | Say (key points) |
| --- | --- | --- |
| 0:00–0:45 | README header + architecture diagram | Use case; MCP path (orange) and RAG path (blue) in one plan; the copilot never calls the API directly. |
| 0:45–1:30 | Terminal: `docker compose ps` (all healthy), `curl localhost:9000/healthz`, `curl localhost:8000/health` | Five services, health-checked start-up order, one-shot `rag-ingest`. |
| 1:30–2:15 | GUI **Tools** tab: expand `get_alarms` and `correlate_alarms` | Live MCP tool discovery; typed input/output schemas; read-only annotations. |
| 2:15–4:15 | Ask the **acceptance scenario** (first example chip). Investigation tab. | Asset resolved via MCP; 90-day summary, trend, active alarm, P2 focus alarm; likely causes (deaerator low level → low suction pressure, 69%); the API's "restart immediately" flagged as a **conflict** with SOP-BFP-001 §4. |
| 4:15–5:15 | **MCP trace** tab: wave 0 discovery, wave 1 `search_assets`, wave 2 five parallel calls; expand `correlate_alarms` → *API calls* (503 then 200) → *request* (`_meta.trace_id`) | Multi-step chaining, output passing (asset_id → later tools), retry visible, trace id propagation. |
| 5:15–6:00 | **Sources** tab: citations S1..Sn, retrieval queries and filters | RAG filters derived from MCP data (asset type, site, related assets, alarm names); verification queries per recommendation. |
| 6:00–6:45 | Follow-up: "Are the API recommendations consistent with the maintenance manual?" then "Which operating procedure applies to this alarm?" | Context retention; consistency verdicts; the applicable procedure section with steps. |
| 6:45–7:45 | **Degraded scenario:** "Investigate alarms for Cooling Water Pump 301" | Recommendation engine returns 503 after 3 attempts → medium confidence, warning, procedure guidance only; the rest of the investigation still succeeds. |
| 7:45–8:30 | "Why are compressor discharge pressure alarms repeatedly occurring?" → Sources tab | Generic equipment resolution; the injected vendor note is **quarantined**. |
| 8:30–9:15 | Terminal: `make test` (128 passed), `make lint typecheck`, CI workflow file, `docs/coverage-summary.md` | TDD evidence, coverage, CI jobs (lint, types, tests, newman contract, audits, docker smoke). |
| 9:15–9:45 | Optional: `docker compose stop alarm-mcp`, ask a question → documents-only answer with error banner; `docker compose start alarm-mcp` | Unavailable-MCP handling. |
| 9:45–10:00 | Wrap-up | Known limitations and next steps. |
