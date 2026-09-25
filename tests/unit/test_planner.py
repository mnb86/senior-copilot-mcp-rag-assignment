"""Plan construction and selectors (MCP output -> next MCP input)."""

from __future__ import annotations

import pytest

from copilot.domain import TimeWindow
from copilot.intent import classify
from copilot.planner import (
    ConversationContext,
    Planner,
    SelectorError,
    build_rag_request,
    sel_best_asset,
    sel_candidate_alarms,
    sel_focus_asset,
    sel_primary_alarm,
    vars_in,
)

W = TimeWindow(days=90, start_time="2026-04-02T00:00:00Z", end_time="2026-07-01T00:00:00Z", label="in the last 90 days")


def plan_for(msg: str, ctx: ConversationContext | None = None):
    return Planner().build(classify(msg), msg, ctx or ConversationContext(), W)


def test_investigation_plan_chains_asset_resolution_into_all_tools():
    p = plan_for("Investigate recurring alarms for Boiler Feed Pump 101")
    tools = [s.tool for s in p.steps]
    assert tools[0] == "search_assets" and tools[-1] == "retrieve_documents"
    assert {
        "get_asset_metadata",
        "get_alarms",
        "summarize_alarms",
        "correlate_alarms",
        "score_alarm_priority",
        "get_operator_recommendations",
    } <= set(tools)
    meta = next(s for s in p.steps if s.id == "asset_metadata")
    assert meta.args == {"asset_id": {"$var": "asset_id"}}
    assert p.bindings["asset_id"].step == "resolve_asset"
    prio = next(s for s in p.steps if s.id == "priority")
    assert vars_in(prio.args) == {"primary_alarm_id"}


def test_generic_equipment_plan_ranks_candidates():
    p = plan_for("Why are compressor discharge pressure alarms repeatedly occurring?")
    assert [s.id for s in p.steps][:2] == ["resolve_asset", "rank_candidates"]
    assert p.bindings["asset_id"].selector == "focus_asset"


def test_site_priority_plan_uses_foreach():
    p = plan_for("Which alarm has the highest priority in EastRefinery, and why?")
    scan = next(s for s in p.steps if s.id == "priority_scan")
    assert scan.foreach == {"$var": "candidate_alarm_ids"} and scan.args == {"alarm_id": {"$item": True}}
    first = p.steps[0]
    assert first.args["site"] == "EastRefinery" and first.args["status"] == "active"


def test_context_is_used_for_follow_up_questions():
    ctx = ConversationContext(
        asset={"asset_id": "AST-BFP-101", "asset_name": "Boiler Feed Pump 101", "asset_type": "pump"},
        alarm={"alarm_id": "ALM-000123", "alarm_name": "Low Suction Pressure"},
    )
    p = plan_for("Which operating procedure applies to this alarm?", ctx)
    assert p.bindings["primary_alarm_id"].params["value"] == "ALM-000123"
    assert any("conversation context" in n for n in p.notes)


def test_missing_scope_requests_clarification():
    assert plan_for("Which alarm has the highest priority?").needs_clarification
    assert plan_for("Are the API recommendations consistent with the maintenance manual?").needs_clarification


def test_selectors():
    out = {"s": {"results": [{"asset_id": "A1", "asset_name": "Pump 1", "match_score": 100}]}}
    assert sel_best_asset(out, "s", {}) == "A1"
    with pytest.raises(SelectorError):
        sel_best_asset({"s": {"results": []}}, "s", {"query": "x"})
    alarms = {
        "a": {
            "alarms": [
                {
                    "alarm_id": "1",
                    "alarm_name": "High Vibration",
                    "severity": "high",
                    "status": "cleared",
                    "start_time": "2",
                },
                {
                    "alarm_id": "2",
                    "alarm_name": "Motor Trip",
                    "severity": "critical",
                    "status": "active",
                    "start_time": "1",
                },
                {
                    "alarm_id": "3",
                    "alarm_name": "Motor Trip",
                    "severity": "critical",
                    "status": "cleared",
                    "start_time": "3",
                },
            ]
        }
    }
    assert sel_primary_alarm(alarms, "a", {}) == "2"  # active + critical wins
    assert sel_primary_alarm(alarms, "a", {"keywords": ["vibration"]}) == "1"
    assert sel_candidate_alarms(alarms, "a", {"limit": 2}) == ["2", "3"]
    groups = {
        "g": {
            "groups": [
                {"group": {"asset_id": "K1", "alarm_name": "High Discharge Pressure"}, "alarm_count": 3},
                {"group": {"asset_id": "K2", "alarm_name": "High Discharge Pressure"}, "alarm_count": 9},
                {"group": {"asset_id": "K1", "alarm_name": "High Vibration"}, "alarm_count": 50},
            ]
        }
    }
    assert sel_focus_asset(groups, "g", {"keywords": ["discharge pressure"]}) == "K2"


def test_rag_request_is_built_from_mcp_outputs():
    out = {
        "asset_metadata": {
            "asset": {
                "asset_id": "AST-BFP-101",
                "asset_name": "Boiler Feed Pump 101",
                "asset_type": "pump",
                "site": "NorthPlant",
                "related_assets": [{"asset_id": "AST-DEA-101"}],
            }
        },
        "recommendations": {
            "alarm_name": "Low Suction Pressure",
            "recommendations": [{"action": "Check deaerator level"}],
        },
        "correlation": {
            "pairs": [
                {
                    "source": {"asset_name": "Deaerator 101", "alarm_name": "Deaerator Low Level"},
                    "target": {"asset_id": "AST-BFP-101", "alarm_name": "Low Suction Pressure"},
                }
            ]
        },
    }
    req = build_rag_request(out, {"intent": "investigate", "message": "why?", "keywords": []})
    assert req["filters"]["asset_types"] == ["pump"] and req["filters"]["site"] == "NorthPlant"
    assert set(req["filters"]["asset_ids"]) == {"AST-BFP-101", "AST-DEA-101"}
    assert "Deaerator Low Level" in req["filters"]["alarm_names"]
    assert any("Low Suction Pressure" in q for q in req["queries"])
    assert "Check deaerator level" in req["queries"]
