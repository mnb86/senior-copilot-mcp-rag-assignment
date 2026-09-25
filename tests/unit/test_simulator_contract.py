"""Alarm Management API simulator: contract checks derived from the Postman collections."""

from __future__ import annotations

from starlette.testclient import TestClient

from conftest import TOKEN, make_sim

H = {"Authorization": f"Bearer {TOKEN}", "trace_id": "trace-test-1", "x-client-id": "pytest", "x-metadata-tag": "unit"}
TR = {"start_time": "2026-04-01T00:00:00Z", "end_time": "2026-07-01T00:00:00Z"}


def client(app=None) -> TestClient:
    return TestClient(app or make_sim())


def test_health_is_public_and_reports_data_window(sim_app):
    r = client(sim_app).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["data_window"]["end_time"] == "2026-07-01T00:00:00Z"


def test_auth_required_and_wrong_token_rejected(sim_app):
    c = client(sim_app)
    assert c.get("/assets/search?query=pump").status_code == 401
    r = c.get("/assets/search?query=pump", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


def test_trace_headers_are_echoed(sim_app):
    r = client(sim_app).get("/assets/search", params={"query": "Boiler Feed Pump 101"}, headers=H)
    assert r.headers["trace_id"] == "trace-test-1"
    assert r.headers["x-client-id"] == "pytest"
    assert r.headers["x-metadata-tag"] == "unit"
    assert r.headers["x-request-id"]


def test_asset_search_ranks_exact_match_first(sim_app):
    body = (
        client(sim_app).get("/assets/search", params={"query": "Boiler Feed Pump 101", "limit": 10}, headers=H).json()
    )
    assert body["results"][0]["asset_id"] == "AST-BFP-101"
    assert all(r["asset_id"] != "AST-BFP-102" for r in body["results"])  # numeric token must match


def test_asset_search_by_type_and_unit(sim_app):
    c = client(sim_app)
    comp = c.get("/assets/search", params={"query": "compressor", "limit": 5}, headers=H).json()["results"]
    assert {r["asset_id"] for r in comp} >= {"AST-K-301", "AST-K-302", "AST-K-303"}
    motors = c.get("/assets/search", params={"query": "motor", "unit": "Unit 5"}, headers=H).json()["results"]
    assert len(motors) >= 3 and all(m["unit"] == "Unit 5" for m in motors)


def test_asset_metadata_and_404(sim_app):
    c = client(sim_app)
    meta = c.get("/assets/AST-BFP-101/metadata", headers=H).json()
    assert meta["standby_asset_id"] == "AST-BFP-102"
    assert {r["asset_id"] for r in meta["related_assets"]} >= {"AST-DEA-101", "AST-LOS-101"}
    r = c.get("/assets/AST-NOPE/metadata", headers=H)
    assert r.status_code == 404 and r.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_alarm_pagination_and_sorting(sim_app):
    c = client(sim_app)
    p1 = c.get(
        "/alarms",
        params={"asset_id": "AST-BFP-101", "page": 1, "page_size": 5, "sort_by": "start_time", "sort_order": "desc"},
        headers=H,
    ).json()
    p2 = c.get("/alarms", params={"asset_id": "AST-BFP-101", "page": 2, "page_size": 5}, headers=H).json()
    assert p1["pagination"]["has_next"] and p1["pagination"]["total"] > 10
    assert {a["alarm_id"] for a in p1["data"]}.isdisjoint({a["alarm_id"] for a in p2["data"]})
    starts = [a["start_time"] for a in p1["data"]]
    assert starts == sorted(starts, reverse=True)


def test_alarm_filters_and_validation(sim_app):
    c = client(sim_app)
    active = c.get("/alarms", params={"site": "EastRefinery", "status": "active"}, headers=H).json()
    assert active["data"] and all(a["status"] == "active" and a["site"] == "EastRefinery" for a in active["data"])
    assert c.get("/alarms", params={"page_size": 9999}, headers=H).status_code == 422
    assert c.get("/alarms", params={"sort_by": "drop table"}, headers=H).status_code == 422
    assert c.get("/alarms", params={"status": "weird"}, headers=H).status_code == 422


def test_get_alarm_by_id(sim_app):
    c = client(sim_app)
    first = c.get("/alarms", params={"asset_id": "AST-BFP-101", "page_size": 1}, headers=H).json()["data"][0]
    assert c.get(f"/alarms/{first['alarm_id']}", headers=H).json()["alarm_id"] == first["alarm_id"]
    assert c.get("/alarms/ALM-999999", headers=H).status_code == 404


def test_summary_trends_correlation(sim_app):
    c = client(sim_app)
    s = c.post(
        "/alarms/summary",
        headers=H,
        json={
            "asset_ids": ["AST-BFP-101"],
            "time_range": TR,
            "severity": ["high", "critical"],
            "group_by": ["alarm_name"],
            "kpis": ["alarm_count", "recurring_rate", "avg_ack_delay"],
        },
    ).json()
    assert s["groups"][0]["group"]["alarm_name"] == "Low Suction Pressure"
    assert 0 <= s["totals"]["recurring_rate"] <= 1
    t = c.post(
        "/alarms/trends",
        headers=H,
        json={"asset_ids": ["AST-BFP-101"], "time_range": TR, "bucket": "weekly", "metrics": ["alarm_count"]},
    ).json()
    assert t["trend"]["direction"] in {"increasing", "decreasing", "stable"} and len(t["buckets"]) >= 12
    corr = c.post(
        "/alarms/correlation",
        headers=H,
        json={"asset_ids": ["AST-BFP-101"], "time_range": TR, "lag_window_minutes": 15, "min_support": 2},
    ).json()
    top = corr["pairs"][0]
    assert (top["source"]["alarm_name"], top["target"]["alarm_name"]) == ("Deaerator Low Level", "Low Suction Pressure")


def test_invalid_bodies_are_rejected(sim_app):
    c = client(sim_app)
    r = c.post("/alarms/summary", headers=H, json={"asset_ids": ["x"], "time_range": TR, "group_by": ["password"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_GROUP_BY"
    r = c.post(
        "/alarms/summary",
        headers=H,
        json={"time_range": {"start_time": "2026-07-01T00:00:00Z", "end_time": "2026-06-01T00:00:00Z"}},
    )
    assert r.status_code == 422
    r = c.post("/alarms/correlation", headers=H, json={"time_range": TR})
    assert r.status_code == 422
    r = c.post("/alarms/priority-score", headers=H, content=b"{not json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_JSON"


def test_flood_rationalization_priority_recommendations(sim_app):
    c = client(sim_app)
    flood = c.post(
        "/alarms/flood-analysis",
        headers=H,
        json={"unit": "Unit 2", "time_range": TR, "threshold_count": 10, "rolling_window_minutes": 10},
    ).json()
    assert flood["flood_window_count"] >= 1 and flood["flood_windows"][0]["alarm_count"] >= 10
    rat = c.post(
        "/alarms/rationalization-candidates",
        headers=H,
        json={"unit": "Unit 4", "time_range": TR, "recurrence_threshold": 8},
    ).json()
    assert any("chattering" in cand["reasons"] for cand in rat["candidates"])
    alarm = c.get("/alarms", params={"site": "EastRefinery", "status": "active"}, headers=H).json()["data"][0]
    prio = c.post("/alarms/priority-score", headers=H, json={"alarm_id": alarm["alarm_id"]}).json()
    assert 0 <= prio["priority_score"] <= 100 and prio["priority_band"] in {"P1", "P2", "P3", "P4"}
    recs = c.post(
        "/recommendations/operator-actions",
        headers=H,
        json={
            "alarm_id": alarm["alarm_id"],
            "include_related": True,
            "include_asset_context": True,
            "include_historical_pattern": True,
        },
    ).json()
    assert recs["recommendations"] and "historical_pattern" in recs and "asset_context" in recs


def test_recommendation_engine_fault_for_southplant(sim_app):
    c = client(sim_app)
    alarm = c.get("/alarms", params={"asset_id": "AST-CWP-301", "page_size": 1}, headers=H).json()["data"][0]
    r = c.post("/recommendations/operator-actions", headers=H, json={"alarm_id": alarm["alarm_id"]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "RECOMMENDATION_ENGINE_UNAVAILABLE"


def test_calculation_generate_execute_chain(sim_app):
    c = client(sim_app)
    for calc in ("alarm_flood_index", "critical_alarm_density", "operator_response_efficiency", "nuisance_alarm_score"):
        gen = c.post(
            "/calculation-code/generate",
            headers=H,
            json={"calculation_type": calc, "filters": {"unit": "Unit 3", **TR}},
        ).json()
        exe = c.post(
            "/calculation-code/execute",
            headers=H,
            json={"calculation_id": gen["calculation_id"], "filters": {"unit": "Unit 3", **TR}},
        ).json()
        assert exe["calculation_type"] == calc and isinstance(exe["result"]["value"], float | int)
    assert (
        c.post("/calculation-code/execute", headers=H, json={"calculation_id": "CALC-NOPE", "filters": TR}).status_code
        == 404
    )
    assert (
        c.post("/calculation-code/generate", headers=H, json={"calculation_type": "rm -rf", "filters": TR}).status_code
        == 400
    )
    kpis = c.get("/analytics/kpi-definitions", headers=H).json()
    assert {k["kpi"] for k in kpis["kpis"]} >= {"alarm_count", "recurring_rate", "avg_ack_delay"}


def test_transient_fault_injection_is_per_trace():
    app = make_sim(faults={"POST /alarms/correlation": (503, 1)})
    c = client(app)
    body = {"asset_ids": ["AST-BFP-101"], "time_range": TR}
    assert c.post("/alarms/correlation", headers=H, json=body).status_code == 503
    assert c.post("/alarms/correlation", headers=H, json=body).status_code == 200
    other = {**H, "trace_id": "another-trace"}
    assert c.post("/alarms/correlation", headers=other, json=body).status_code == 503


def test_faults_can_be_limited_to_specific_clients():
    app = make_sim(faults={"POST /alarms/correlation": (503, 5)}, fault_clients=frozenset({"alarm-mcp-server"}))
    c = client(app)
    body = {"asset_ids": ["AST-BFP-101"], "time_range": TR}
    assert c.post("/alarms/correlation", headers=H, json=body).status_code == 200  # postman / other clients
    mcp = {**H, "x-client-id": "alarm-mcp-server"}
    assert c.post("/alarms/correlation", headers=mcp, json=body).status_code == 503


def test_fault_header(sim_app):
    r = client(sim_app).get("/assets/search?query=pump", headers={**H, "x-simulate-fault": "500"})
    assert r.status_code == 500


def test_data_is_deterministic():
    a, b = make_sim(), make_sim()
    assert [e.alarm_id for e in a.state.store.events[:50]] == [e.alarm_id for e in b.state.store.events[:50]]
    assert len(a.state.store.events) == len(b.state.store.events)
