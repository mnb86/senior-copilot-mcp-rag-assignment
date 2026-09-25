"""Intent detection and entity extraction (tool selection starts here)."""

from __future__ import annotations

import pytest

from copilot.intent import classify, extract_entities

CASES = [
    ("Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.", "investigate"),
    ("Why are compressor discharge pressure alarms repeatedly occurring?", "investigate"),
    ("Which alarm has the highest priority in EastRefinery, and why?", "site_priority"),
    ("What related assets should be inspected for this motor trip alarm?", "related_assets"),
    ("Which operating procedure applies to this alarm?", "procedure_lookup"),
    ("Are the API recommendations consistent with the maintenance manual?", "recommendation_check"),
    (
        "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely "
        "contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source "
        "evidence.",
        "investigate",
    ),
    ("What is the alarm flood percentage in Unit 2 last month?", "alarm_kpi"),
    ("What does the alarm philosophy say about shelving?", "general_question"),
    ("What must be checked before restarting rotating equipment after a trip?", "general_question"),
    ("Why is Forced Draft Fan 301 alarming so often?", "investigate"),
    ("Investigate the alarms", "investigate"),  # no scope: the planner then asks which asset
]


def test_guidance_follow_up_keeps_case_context():
    # the same how-to wording inside an open case stays an investigation of that asset
    assert classify("What should I do about this alarm?", has_context=True).name != "general_question"


@pytest.mark.parametrize("message,intent", CASES)
def test_example_questions_map_to_expected_intent(message, intent):
    assert classify(message).name == intent


def test_entities_for_acceptance_scenario():
    e = extract_entities(CASES[6][0])
    assert e.asset_query == "Boiler Feed Pump 101" and e.asset_is_specific
    assert e.severities == ["high", "critical"] and e.lookback_days == 90


def test_generic_equipment_and_alarm_keywords():
    e = extract_entities("Why are compressor discharge pressure alarms repeatedly occurring?")
    assert e.asset_query == "compressor" and not e.asset_is_specific and e.equipment_type == "compressor"
    assert e.alarm_keywords == ["discharge pressure"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Check K-301 alarms", "K-301"),
        ("Investigate alarms on Recycle Gas Compressor K-301", "Recycle Gas Compressor K-301"),
        ("status of AST-BFP-102", "AST-BFP-102"),
    ],
)
def test_specific_asset_extraction(text, expected):
    assert extract_entities(text).asset_query == expected


def test_site_unit_status_and_lookback():
    e = extract_entities("active alarms in Unit 5 at NorthPlant over the past 2 weeks")
    assert (e.site, e.unit, e.status, e.lookback_days) == ("NorthPlant", "Unit 5", "active", 14)


def test_context_reference_detection():
    assert extract_entities("Which procedure applies to this alarm?").refers_to_context
    assert not extract_entities("Show alarms for Boiler Feed Pump 101").refers_to_context
