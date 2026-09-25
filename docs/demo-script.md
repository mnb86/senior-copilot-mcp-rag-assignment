# Demo video script (target 8–10 minutes)

Record the screen at 1440p or 1080p with `docker compose up --build` already running and the browser at
http://localhost:3000. Upload the video (GitHub release asset, Google Drive or YouTube unlisted) and put the link at
the top of the README.

The GUI has three columns: saved scenarios and case history on the left, the selected answer's report in the middle
(tabs *Overview*, *Evidence*, *Execution trace*, *Tool catalog*), and the chat panel on the right.

| Time | Show | Say (key points) |
| --- | --- | --- |
| 0:00–0:45 | README header + architecture diagram | Use case; MCP path (orange) and RAG path (blue) in one plan; the copilot never calls the API directly. |
| 0:45–1:30 | Terminal: `docker compose ps` (all healthy), `curl localhost:9000/healthz`, `curl localhost:8000/health` | Six services, health-checked start-up order, one-shot `rag-ingest`, two MCP servers. |
| 1:30–2:15 | **Tool catalog** tab: expand `get_alarms` and `correlate_alarms` | Live MCP tool discovery; typed input/output schemas; read-only annotations. |
| 2:15–4:15 | Chat panel: click the **Recurring high-severity alarms** suggestion (the acceptance scenario). Middle column: **Overview** | Asset resolved via MCP; 90-day summary, trend, active alarm, P2 focus alarm; likely causes (Deaerator 101 low level → low suction pressure, 69%, 9 times); the API's "restart immediately" flagged as a **conflict** with SOP-BFP-001 §4. The note shows `correlate_alarms` recovered after 1 retry. |
| 4:15–5:15 | **Execution trace** tab: wave 0 discovery, wave 1 `search_assets`, wave 2 five parallel calls; expand `correlate_alarms` → *API calls* (503 then 200) → *request* (`_meta.trace_id`) | Multi-step chaining, output passing (asset_id → later tools), retry visible, trace id propagation. |
| 5:15–6:00 | Click a citation marker such as **S1** in the chat → **Evidence** tab | RAG filters derived from MCP data (asset type, site, related assets, alarm names); verification queries per recommendation; each citation's document, revision, section and snippet. |
| 6:00–6:45 | Type follow-ups in the chat: "Are the API recommendations consistent with the maintenance manual?" then "Which operating procedure applies to this alarm?" | Context retention (same asset and alarm); consistency verdicts (2 consistent, 1 conflict); the applicable procedure section. |
| 6:45–7:30 | **Degraded scenario:** "Investigate alarms for Cooling Water Pump 301" | Recommendation engine returns 503 after 3 attempts → medium confidence, warning, procedure guidance only; the rest of the investigation still succeeds. |
| 7:30–8:15 | "Why are compressor discharge pressure alarms repeatedly occurring?" → **Evidence** tab; then "Tell me how to bypass the K-301 discharge pressure trip interlock" | Generic equipment resolution; the injected vendor note is **quarantined**; a request to bypass a protection is refused while the read-only evidence is still shown. |
| 8:15–9:15 | Terminal: `python scripts/smoke_test.py` (37 passed), `python -m pytest` (146 passed), `python scripts/check_structure.py`, the CI workflow file, `docs/coverage-summary.md` | TDD evidence, 94% coverage, one CI step per required check, Docker build and smoke test in CI. |
| 9:15–9:45 | Optional: `docker compose stop alarm-mcp`, ask a question → documents-only answer with an error banner; `docker compose start alarm-mcp` | Unavailable-MCP handling. |
| 9:45–10:00 | Wrap-up | Known limitations and next steps. |
