"""Intent detection and entity extraction (deterministic rules; an LLM can refine via llm.py)."""

from __future__ import annotations

import re

from .domain import Entities, Intent, IntentName

EQUIPMENT_TYPES = {
    "pump": "pump",
    "pumps": "pump",
    "compressor": "compressor",
    "compressors": "compressor",
    "motor": "motor",
    "motors": "motor",
    "fan": "fan",
    "fans": "fan",
    "valve": "valve",
    "valves": "valve",
    "deaerator": "vessel",
    "boiler": "boiler",
    "heater": "heat_exchanger",
    "cooler": "heat_exchanger",
    "exchanger": "heat_exchanger",
    "drum": "vessel",
    "tank": "tank",
    "mcc": "electrical",
    "switchgear": "electrical",
}

# Domain vocabulary of alarm phrases (longest match first).
ALARM_TERMS = sorted(
    [
        "low suction pressure",
        "suction pressure",
        "high discharge pressure",
        "discharge pressure",
        "discharge temperature",
        "high bearing temperature",
        "bearing temperature",
        "winding temperature",
        "outlet temperature",
        "high vibration",
        "vibration",
        "pump trip",
        "motor trip",
        "trip",
        "surge",
        "low lube oil pressure",
        "lube oil",
        "undervoltage",
        "overcurrent",
        "ground fault",
        "seal leak",
        "seal gas",
        "low level",
        "high level",
        "drum level",
        "level",
        "low flow",
        "flow",
        "overload",
        "flame instability",
        "phase imbalance",
        "valve position deviation",
        "positioner fault",
        "tube leak",
    ],
    key=len,
    reverse=True,
)

SPECIFIC_ASSET = re.compile(
    r"\b((?:[A-Z][A-Za-z]+\s+){1,5}(?:[A-Z]{1,4}-)?\d{2,4}[A-Z]?)\b"  # "Boiler Feed Pump 101", "... K-301"
    r"|\b(AST-[A-Z0-9-]+)\b"  # asset id
    r"|\b([A-Z]{1,4}-\d{2,4}[A-Z]?)\b"
)  # tag, e.g. K-301, BFP-101
SITE = re.compile(r"\b([A-Z][a-z]+(?:Plant|Refinery|Terminal|Works|Site))\b")
UNIT = re.compile(r"\b(Unit\s+\d+|[A-Z]{2,4}-\d)\b")
LOOKBACK = re.compile(r"\b(?:last|past|previous)\s+(\d{1,3})\s*(day|week|month|year)s?\b", re.I)
NAMED_LOOKBACK = {
    "last week": 7,
    "past week": 7,
    "last month": 30,
    "past month": 30,
    "last quarter": 90,
    "last year": 365,
    "past year": 365,
    "today": 1,
    "yesterday": 2,
    "last 24 hours": 1,
}
CONTEXT_REFS = re.compile(
    r"\b(this|that|these|those|the same)\s+(alarm|asset|pump|motor|compressor|equipment|"
    r"recommendations?|one|trip)\b|\bit\b",
    re.I,
)
_LEADING_NOISE = re.compile(
    r"^(?:For|On|Show|Investigate|Why|Which|What|Are|The|Is|Of|At|In|Check|Get|Review|"
    r"Analy[sz]e|Explain|Diagnose|Find|List|Display|Tell|Give|Recommend|Me|About|"
    r"Alarms?|Asset)\s+",
    re.I,
)


def _kw(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def extract_entities(message: str) -> Entities:
    text = message.strip()
    low = text.lower()
    e = Entities()

    for m in SPECIFIC_ASSET.finditer(text):
        cand = next(g for g in m.groups() if g)
        prev = None
        while prev != cand:
            prev, cand = cand, _LEADING_NOISE.sub("", cand).strip()
        if UNIT.fullmatch(cand) or re.fullmatch(r"(?:Last|Past|Previous)\s+\d+", cand, re.I):
            continue
        if re.fullmatch(r"\d+", cand):
            continue
        e.asset_query, e.asset_is_specific = cand, True
        break

    if site_m := SITE.search(text):
        e.site = site_m.group(1)
    if unit_m := UNIT.search(text):
        e.unit = unit_m.group(1)

    for word, typ in EQUIPMENT_TYPES.items():
        if re.search(rf"\b{word}\b", low):
            e.equipment_type = typ
            if not e.asset_query:
                e.asset_query = word.rstrip("s") if word.endswith("s") and word not in ("mcc",) else word
            break

    found: list[str] = []
    rest = low
    for term in ALARM_TERMS:
        if term in rest:
            found.append(term)
            rest = rest.replace(term, " ")
    e.alarm_keywords = found

    if _kw(low, "critical"):
        e.severities = ["critical"]
    if re.search(r"\bhigh[- ](severity|priority)\b|\bsevere\b|\bserious\b", low):
        e.severities = ["high", "critical"]
    if _kw(low, "active", "current", "currently", "standing", "open", "ongoing"):
        e.status = "active"

    if lb := LOOKBACK.search(low):
        n, unit = int(lb.group(1)), lb.group(2).lower()
        e.lookback_days = min(365, n * {"day": 1, "week": 7, "month": 30, "year": 365}[unit])
    else:
        for phrase, days in NAMED_LOOKBACK.items():
            if phrase in low:
                e.lookback_days = days
                break

    e.refers_to_context = bool(CONTEXT_REFS.search(text))
    return e


def classify(message: str, entities: Entities | None = None, has_context: bool = False) -> Intent:
    low = message.lower()
    e = entities or extract_entities(message)
    has_scope = bool(e.asset_query or e.site or e.unit)
    scores: dict[IntentName, float] = {}
    reasons: dict[IntentName, str] = {}

    def vote(name: IntentName, score: float, why: str) -> None:
        if score > scores.get(name, 0):
            scores[name], reasons[name] = score, why

    if re.search(r"\b(consistent|consistency|agree|contradict|conflict|align|match)\w*\b", low) and re.search(
        r"\b(recommend\w*|manual|procedure|sop|guidance)\b", low
    ):
        vote("recommendation_check", 0.92, "asks to compare API recommendations with documentation")
    if re.search(
        r"\brelated (assets?|equipment)\b|\bupstream\b|\bwhat else\b|\bwhich (other )?assets?\b.*inspect", low
    ):
        vote("related_assets", 0.88, "asks which related assets to inspect")
    if re.search(
        r"\b(procedure|sop|operating instruction|which manual|what does the manual|applies|applicable)\b", low
    ) and not scores.get("recommendation_check"):
        vote("procedure_lookup", 0.85, "asks which procedure/document applies")
    if re.search(r"\b(highest|top|most urgent|most important|rank\w*)\b", low) and re.search(
        r"\b(priority|prioriti\w+|urgent|important)\b", low
    ):
        vote(
            "site_priority",
            0.9 if (e.site or e.unit) and not e.asset_is_specific else 0.7,
            "asks for the highest-priority alarm in a scope",
        )
    if re.search(
        r"\b(flood\w*|kpi|nuisance|chatter\w*|rationali[sz]ation|response efficiency|alarm rate|"
        r"stale alarms?)\b",
        low,
    ):
        vote("alarm_kpi", 0.85, "asks for alarm-management KPIs")
    if re.search(r"\b(investigate|investigation|root cause|contributing|recurring|repeatedly)\b", low) and (
        has_scope or has_context
    ):
        vote("investigate", 0.93, "explicit investigation of recurring alarms / contributing factors")
    if re.search(
        r"\b(investigate|why|root cause|cause|recurring|repeated\w*|keeps?|frequent\w*|show|recommend\w*|"
        r"what should|actions?|status|summar\w+|history|trend)\b",
        low,
    ) and (has_scope or has_context):
        vote("investigate", 0.8, "alarm investigation request with an asset/site scope")
    if not scores:
        if has_scope or e.alarm_keywords:
            vote("investigate", 0.6, "mentions an asset or alarm; defaulting to investigation")
        else:
            vote("general_question", 0.55, "no asset, site or alarm scope detected; answering from documents")

    order: list[IntentName] = [
        "recommendation_check",
        "related_assets",
        "procedure_lookup",
        "site_priority",
        "alarm_kpi",
        "investigate",
        "general_question",
    ]
    best = max(scores, key=lambda n: (scores[n], -order.index(n)))
    return Intent(name=best, confidence=scores[best], rationale=reasons[best], entities=e)
