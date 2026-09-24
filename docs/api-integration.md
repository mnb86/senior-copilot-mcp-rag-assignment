# Alarm Management API integration

The simulator (`apps/alarm-api-simulator`) implements the contract defined by the Postman collections in
[`postman/`](../postman). The MCP server is its **only** consumer inside the solution, through the reusable connector
`connectors/alarm_api`.

## 1. Contract conformance

| Collection | Requests | Result against the simulator |
| --- | --- | --- |
| `Alarm-API-Simulator.postman_collection.json` (E2E baseline) | 15 | 15 passed |
| `chaining/Alarm-API-Chaining.postman_collection.json` (10 chains) | 32 | 32 passed |
| `scenarios/Alarm-API-Scenarios.postman_collection.json` | 15 | 15 passed |

Run locally with `make postman` (dependency-free runner that executes the collections' own `pm` test scripts) or in
CI with **newman** (`contract` job).

## 2. Authentication

- Every endpoint except `GET /health` requires `Authorization: Bearer <ALARM_API_TOKEN>` (constant-time compare);
  otherwise `401 {"error": {"code": "UNAUTHORIZED"}}`.
- The token lives only in the MCP server's environment (`ALARM_API_TOKEN`, `SecretStr`). It is added per request by
  the connector and never recorded in attempt audits, tool results or logs.

## 3. Trace metadata

| Header | Direction | Source |
| --- | --- | --- |
| `trace_id` | request → echoed in response | MCP `_meta.trace_id` (copilot creates one per chat request) |
| `x-client-id` | request → echoed | `_meta.client_id` (`alarm-copilot`) or the connector default `alarm-mcp-server` |
| `x-metadata-tag` | request → echoed | `_meta.metadata_tag` (optional) |
| `x-request-id` | request (new per attempt) → echoed | connector; lets retries be told apart in logs |

Values from `_meta` are sanitised (alphanumeric plus `-_.:`, 128 chars max) before they become headers.

## 4. Endpoints and connector methods

| Endpoint | Connector method | MCP tool |
| --- | --- | --- |
| `GET /health` | `health` | (`/healthz` of the MCP server) |
| `GET /assets/search?query&limit&site&unit` | `search_assets` | `search_assets` |
| `GET /assets/{asset_id}/metadata` | `asset_metadata` | `get_asset_metadata` |
| `GET /alarms?asset_id&site&unit&status&severity&alarm_name&start_time&end_time&page&page_size&sort_by&sort_order` | `list_alarms`, `list_alarms_all_pages` | `get_alarms` |
| `GET /alarms/{alarm_id}` | `get_alarm` | `get_alarm_details` |
| `POST /alarms/summary` | `alarm_summary` | `summarize_alarms` |
| `POST /alarms/trends` | `alarm_trends` | `get_alarm_trends` |
| `POST /alarms/correlation` | `alarm_correlation` | `correlate_alarms` |
| `POST /alarms/flood-analysis` | `flood_analysis` | `analyze_alarm_flood` |
| `POST /alarms/rationalization-candidates` | `rationalization_candidates` | `find_rationalization_candidates` |
| `POST /alarms/priority-score` | `priority_score` | `score_alarm_priority` |
| `POST /recommendations/operator-actions` | `operator_recommendations` | `get_operator_recommendations` |
| `POST /calculation-code/generate` | `generate_calculation` | `calculate_kpi` (step 1) |
| `POST /calculation-code/execute` | `execute_calculation` | `calculate_kpi` (step 2) |
| `GET /analytics/kpi-definitions` | `kpi_definitions` | `list_kpi_definitions` |

Path identifiers are URL-encoded as single segments (`../admin` → `..%2Fadmin`), so a crafted id can't reach another
route.

## 5. Pagination

`GET /alarms` returns `{"data": [...], "pagination": {"page", "page_size", "total", "total_pages", "has_next"}}` with
`page_size ≤ 500` (the MCP tool caps it at 200). `list_alarms_all_pages` follows `has_next` up to `max_pages`
(tool default 3, max 10) and reports `pages_fetched` and `truncated`, so a caller knows when data was cut off.

## 6. Error format and mapping

Simulator errors: `{"error": {"code", "message", "details"}, "trace_id", "request_id"}`.

| HTTP | Connector exception | MCP error code | Retried |
| --- | --- | --- | --- |
| 400 / 409 / 422 | `InvalidRequestError` | `INVALID_REQUEST` | no |
| 401 / 403 | `AuthenticationError` | `AUTHENTICATION_FAILED` | no |
| 404 | `NotFoundError` | `NOT_FOUND` | no |
| 429 | `RateLimitedError` | `RATE_LIMITED` | yes (honours `Retry-After`) |
| 502 / 503 | `UpstreamUnavailableError` | `UPSTREAM_UNAVAILABLE` | yes |
| 504 / client timeout | `UpstreamTimeoutError` | `UPSTREAM_TIMEOUT` | yes |
| connection error | `ConnectionFailedError` | `CONNECTION_FAILED` | yes |
| 2xx non-JSON | `UnexpectedResponseError` | `UNEXPECTED_RESPONSE` | no |

The MCP error payload also carries `http_status`, `upstream_code` (e.g. `ASSET_NOT_FOUND`), `retryable`,
`attempts`, `trace_id` and `details.http_attempts`, so the GUI can show every attempt.

## 7. Timeouts and retries

- Per attempt: `ALARM_API_TIMEOUT_SECONDS` (default 10 s).
- Retries: `ALARM_API_MAX_RETRIES` (default 2) → at most 3 attempts; backoff `base · 2^(n-1) · U(0.5, 1.5)` capped at
  4 s, or `Retry-After` when present.
- Copilot side: `MCP_TIMEOUT_SECONDS` (30 s) per tool call.

## 8. Simulator behaviour worth knowing

- **Data:** 25 assets across NorthPlant (Units 1–5), EastRefinery (CDU-1, HCU-2, UTIL) and SouthPlant (CW-1);
  about 3,000 alarm occurrences over 365 days before the anchor, generated with seed 42. Causal chains are built in
  (deaerator low level → BFP low suction pressure → pump trip; lube-oil pressure → bearing temperature; E-301
  outlet temperature and FV-301 deviation → K-301 discharge pressure; MCC-501 undervoltage → motor trips), plus
  chattering alarms in Unit 4, flood bursts in Unit 2, and standing active alarms.
- **Correlation:** directed co-occurrence. A → B counts when B starts within `lag_window_minutes` after A. Reports
  `support`, `confidence = support / count(A)`, `lift` and average lag. Related assets are included by default.
- **Priority score (0–100):** severity (5–40) + asset criticality (5–25) + safety alarm (15) + recurrence in the
  prior 30 days (≤ 15) + unacknowledged active (5), banded P1 ≥ 75, P2 ≥ 55, P3 ≥ 35, else P4.
- **Recommendations:** rule engine keyed by alarm type with related alarms, asset context and 90-day precursors.
  One rule ("reset the pump trip and restart immediately") intentionally contradicts SOP-BFP-001 so that the
  consistency check has something to find.
- **Fault injection:**
  `SIM_FAULTS="POST /alarms/correlation=503x1"` fails the first call **per trace id** (a transient fault, recovered
  by retry), limited to `SIM_FAULT_CLIENTS` (default: only the MCP server, so Postman runs stay green). Recommendations
  for SouthPlant assets always return 503 (persistent outage for the degraded demo). The `x-simulate-fault:
  500|503|timeout:<s>` header is available for manual testing (`SIM_ALLOW_FAULT_HEADER`).

## 9. Chaining flows covered by the copilot

| Postman chain | Copilot intent / plan |
| --- | --- |
| CHAIN-01 asset → summary → rationalization | `investigate` / `alarm_kpi` |
| CHAIN-02 flood → alarms → summary | `alarm_kpi` (flood + summary) |
| CHAIN-03 compressor search → correlation → latest alarm → metadata → recommendations | `investigate` with generic equipment (candidate ranking) |
| CHAIN-04 / 07 / 10 KPI generate → execute → summary / trends / candidates | `alarm_kpi` (`calculate_kpi` chains generate+execute inside the MCP server) |
| CHAIN-05 BFP-102 active alarms → recommendations | `investigate` with `status=active` |
| CHAIN-06 stale + severity context | `alarm_kpi` (rationalization + severity summary) |
| CHAIN-08 motor correlation | `related_assets` |
| CHAIN-09 EastRefinery active → priority → recommendations | `site_priority` (`foreach` priority scoring) |
