"""Plan construction.

A plan is *data*: a list of :class:`PlanStep` (MCP tool calls or a RAG retrieval) whose arguments may
reference **bindings** (``{"$var": "asset_id"}``). A binding is produced by a named, reusable
*selector* applied to the output of an earlier step (e.g. "pick the best asset from search results",
"pick the primary alarm"). This lets the executor chain MCP outputs into subsequent MCP calls and into
RAG queries without hard-coding any particular question.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .domain import Entities, Intent, PlanStep, TimeWindow

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


class SelectorError(Exception):
    """A binding could not be produced (e.g. no search match)."""


@dataclass
class Binding:
    step: str | None  # source step id (None = derived from several steps)
    selector: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    tolerant: bool = False  # resolve even if some source steps failed


@dataclass
class Plan:
    intent: Intent
    steps: list[PlanStep]
    bindings: dict[str, Binding]
    window: TimeWindow
    notes: list[str] = field(default_factory=list)
    needs_clarification: str | None = None


@dataclass
class ConversationContext:
    asset: dict[str, Any] | None = None
    alarm: dict[str, Any] | None = None
    site: str | None = None
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0


# ============================================================================ selectors
Outputs = dict[str, Any]


def _kw_match(name: str, keywords: list[str]) -> bool:
    n = name.lower()
    return any(k in n or all(w in n for w in k.split()) for k in keywords)


def sel_best_asset(out: Outputs, step: str, p: dict[str, Any]) -> str:
    results = (out.get(step) or {}).get("results") or []
    if not results:
        raise SelectorError(f"No asset matched '{p.get('query')}'")
    if p.get("specific") and results[0].get("match_score", 0) < 5 and len(results) > 1:
        raise SelectorError(f"'{p.get('query')}' is ambiguous: " + ", ".join(r["asset_name"] for r in results[:4]))
    return str(results[0]["asset_id"])


def sel_candidate_ids(out: Outputs, step: str, p: dict[str, Any]) -> list[str]:
    results = (out.get(step) or {}).get("results") or []
    typ = p.get("equipment_type")
    ids = [r["asset_id"] for r in results if not typ or r.get("asset_type") == typ]
    ids = ids or [r["asset_id"] for r in results]
    if not ids:
        raise SelectorError(f"No assets matched '{p.get('query')}'")
    return ids[: p.get("limit", 6)]


def sel_focus_asset(out: Outputs, step: str, p: dict[str, Any]) -> str:
    """Asset with the most alarms matching the keywords (from a summary grouped by asset_id, alarm_name)."""
    groups = (out.get(step) or {}).get("groups") or []
    kws = p.get("keywords") or []
    totals: dict[str, float] = {}
    for g in groups:
        name = str(g["group"].get("alarm_name", ""))
        if kws and not _kw_match(name, kws):
            continue
        aid = g["group"].get("asset_id")
        totals[aid] = totals.get(aid, 0) + g.get("alarm_count", 0) * (1 + g.get("recurring_rate", 0) or 0)
    if not totals:
        fallback = p.get("fallback_step")
        if fallback:
            return sel_best_asset(out, fallback, {})
        raise SelectorError("No candidate asset has matching alarms")
    return max(totals, key=lambda k: totals[k])


def _alarm_sort_key(a: dict[str, Any]) -> tuple[int, int, str]:
    return (
        1 if a.get("status") == "active" else 0,
        SEVERITY_RANK.get(a.get("severity", ""), 0),
        a.get("start_time", ""),
    )


def sel_primary_alarm(out: Outputs, step: str, p: dict[str, Any]) -> str:
    alarms = (out.get(step) or {}).get("alarms") or []
    if p.get("context_alarm_id"):
        return str(p["context_alarm_id"])
    if not alarms:
        raise SelectorError("No alarms found in the selected window")
    kws = p.get("keywords") or []
    pool = [a for a in alarms if _kw_match(a["alarm_name"], kws)] if kws else []
    if not pool:  # a standing alarm is what the operator must act on first
        pool = [a for a in alarms if a.get("status") == "active"]
    if not pool and p.get("prefer_recurring"):
        counts: dict[str, int] = {}
        for a in alarms:
            counts[a["alarm_name"]] = counts.get(a["alarm_name"], 0) + 1
        top = max(
            counts,
            key=lambda k: (counts[k], max(SEVERITY_RANK.get(a["severity"], 0) for a in alarms if a["alarm_name"] == k)),
        )
        pool = [a for a in alarms if a["alarm_name"] == top]
    pool = pool or alarms
    return str(max(pool, key=_alarm_sort_key)["alarm_id"])


def sel_candidate_alarms(out: Outputs, step: str, p: dict[str, Any]) -> list[str]:
    alarms = (out.get(step) or {}).get("alarms") or []
    if not alarms:
        raise SelectorError("No active alarms found in scope")
    ranked = sorted(alarms, key=_alarm_sort_key, reverse=True)
    return [a["alarm_id"] for a in ranked[: p.get("limit", 6)]]


def sel_best_priority(out: Outputs, step: str, p: dict[str, Any]) -> str:
    scores = [s for s in (out.get(step) or []) if isinstance(s, dict) and "priority_score" in s]
    if not scores:
        raise SelectorError("Priority scoring returned no results")
    return str(max(scores, key=lambda s: s["priority_score"])["alarm_id"])


def sel_asset_of_alarm(out: Outputs, step: str, p: dict[str, Any]) -> str:
    data = out.get(step)
    rows = data if isinstance(data, list) else [data]
    target = p.get("alarm_id")
    for r in rows:
        if isinstance(r, dict) and (not target or r.get("alarm_id") == target):
            return str(r["asset_id"])
    raise SelectorError("Could not determine the asset of the selected alarm")


SELECTORS: dict[str, Callable[[Outputs, str, dict[str, Any]], Any]] = {
    "best_asset": sel_best_asset,
    "candidate_asset_ids": sel_candidate_ids,
    "focus_asset": sel_focus_asset,
    "primary_alarm": sel_primary_alarm,
    "candidate_alarm_ids": sel_candidate_alarms,
    "best_priority_alarm": sel_best_priority,
    "asset_of_alarm": sel_asset_of_alarm,
}


# ============================================================================ RAG query builder
INTENT_QUERY_HINT = {
    "investigate": "recurring alarm causes and operator response procedure",
    "site_priority": "alarm response procedure priority",
    "related_assets": "related assets to inspect after the alarm",
    "procedure_lookup": "operating procedure alarm response",
    "recommendation_check": "procedure guidance",
    "alarm_kpi": "alarm management philosophy flood chattering stale rationalization",
    "general_question": "",
}


def build_rag_request(out: Outputs, p: dict[str, Any]) -> dict[str, Any]:
    """Derive retrieval queries + filters from whatever MCP outputs are available (tolerant)."""
    intent: str = p["intent"]
    message: str = p["message"]
    meta = (out.get("asset_metadata") or {}).get("asset") or p.get("context_asset") or {}
    asset_type = meta.get("asset_type") or p.get("equipment_type")
    alarm_names: list[str] = []
    for key in ("recommendations", "priority"):
        d = out.get(key)
        if isinstance(d, dict) and d.get("alarm_name"):
            alarm_names.append(d["alarm_name"])
    detail = (out.get("alarm_detail") or {}).get("alarm") or {}
    if detail.get("alarm_name"):
        alarm_names.append(detail["alarm_name"])
    for g in ((out.get("summary") or {}).get("groups") or [])[:2]:
        if g["group"].get("alarm_name"):
            alarm_names.append(g["group"]["alarm_name"])
    if p.get("context_alarm_name"):
        alarm_names.append(p["context_alarm_name"])
    alarm_names = list(dict.fromkeys(alarm_names))
    causes: list[str] = []
    cause_alarms: list[str] = []
    for pair in ((out.get("correlation") or {}).get("pairs") or [])[:3]:
        if pair["target"]["alarm_name"] in alarm_names or pair["target"]["asset_id"] == meta.get("asset_id"):
            causes.append(
                f"{pair['source']['asset_name']} {pair['source']['alarm_name']} cause of {pair['target']['alarm_name']}"
            )
            cause_alarms.append(pair["source"]["alarm_name"])
    subject = " ".join(filter(None, [meta.get("asset_name") or p.get("asset_query"), asset_type]))
    primary = alarm_names[0] if alarm_names else " ".join(p.get("keywords") or [])
    queries = [
        q
        for q in [
            re.sub(r"\s+", " ", f"{primary} {subject} {INTENT_QUERY_HINT.get(intent, '')}").strip()
            if (primary or subject)
            else "",
            message,
        ]
        if q
    ]
    queries += causes[:2]
    recs = (out.get("recommendations") or {}).get("recommendations") or p.get("context_recommendations") or []
    queries += [r["action"] for r in recs[: 5 if intent == "recommendation_check" else 3]]
    if intent == "related_assets" and primary:
        queries.insert(0, f"related assets to inspect after {primary}")
    doc_types = {
        "procedure_lookup": ["operating_procedure", "safety_instruction", "troubleshooting_guide"],
        "alarm_kpi": ["alarm_philosophy", "maintenance_manual"],
    }.get(intent)
    related_ids = [r["asset_id"] for r in meta.get("related_assets") or []]
    filters = {
        "doc_types": doc_types,
        "site": meta.get("site"),
        "asset_types": [asset_type] if asset_type else None,
        "asset_ids": ([meta["asset_id"]] if meta.get("asset_id") else []) + related_ids or None,
        "alarm_names": list(dict.fromkeys(alarm_names + cause_alarms)) or None,
    }
    return {"queries": list(dict.fromkeys(queries))[:8], "filters": filters}


# ============================================================================ planner
class Planner:
    def __init__(self, default_lookback_days: int = 90) -> None:
        self.default_lookback_days = default_lookback_days

    def build(self, intent: Intent, message: str, ctx: ConversationContext, window: TimeWindow) -> Plan:
        e = intent.entities
        steps: list[PlanStep] = []
        b: dict[str, Binding] = {}
        notes: list[str] = []
        plan = Plan(intent=intent, steps=steps, bindings=b, window=window, notes=notes)
        w = {"start_time": window.start_time, "end_time": window.end_time}
        used_ctx: dict[str, bool] = {}
        sev = e.severities

        def add(step: PlanStep) -> None:
            steps.append(step)

        def resolve_asset(required: bool = True) -> bool:
            """Adds asset-resolution steps; returns True if an ``asset_id`` binding is available."""
            type_ok = not e.equipment_type or not ctx.asset or ctx.asset.get("asset_type") == e.equipment_type
            use_ctx = (
                ctx.asset
                and type_ok
                and (e.refers_to_context or not e.asset_query)
                and not (e.site and not e.asset_query)
            )
            if use_ctx and ctx.asset:
                used_ctx["asset"] = True
                b["asset_id"] = Binding(None, "literal", {"value": ctx.asset["asset_id"]})
                notes.append(f"Using asset from conversation context: {ctx.asset['asset_name']}")
                return True
            if not e.asset_query:
                if required:
                    plan.needs_clarification = (
                        "Which asset should I investigate? Please name the asset "
                        "(e.g. 'Boiler Feed Pump 101') or a site/unit."
                    )
                return False
            add(
                PlanStep(
                    id="resolve_asset",
                    tool="search_assets",
                    purpose=f"Resolve '{e.asset_query}' to an asset identifier",
                    args={
                        "query": e.asset_query,
                        "site": e.site,
                        "unit": e.unit,
                        "limit": 5 if e.asset_is_specific else 8,
                    },
                )
            )
            if e.asset_is_specific:
                b["asset_id"] = Binding("resolve_asset", "best_asset", {"specific": True, "query": e.asset_query})
            else:
                b["candidate_asset_ids"] = Binding(
                    "resolve_asset", "candidate_asset_ids", {"equipment_type": e.equipment_type, "query": e.asset_query}
                )
                add(
                    PlanStep(
                        id="rank_candidates",
                        tool="summarize_alarms",
                        purpose=f"Rank candidate {e.equipment_type or 'asset'}s by matching alarm activity",
                        args={
                            "asset_ids": {"$var": "candidate_asset_ids"},
                            **w,
                            "group_by": ["asset_id", "asset_name", "alarm_name"],
                            "kpis": ["alarm_count", "recurring_rate"],
                            "severity": sev,
                        },
                    )
                )
                b["asset_id"] = Binding(
                    "rank_candidates",
                    "focus_asset",
                    {"keywords": e.alarm_keywords, "fallback_step": "resolve_asset"},
                    depends_on=["resolve_asset"],
                    tolerant=True,
                )
            return True

        def investigate_core(alarm_keywords: list[str], prefer_recurring: bool, with_trend: bool = True) -> None:
            add(
                PlanStep(
                    id="asset_metadata",
                    tool="get_asset_metadata",
                    purpose="Fetch asset metadata, operating limits and related assets",
                    args={"asset_id": {"$var": "asset_id"}},
                )
            )
            add(
                PlanStep(
                    id="alarms",
                    tool="get_alarms",
                    purpose="Retrieve alarm occurrences in the window",
                    args={
                        "asset_id": {"$var": "asset_id"},
                        **w,
                        "severity": sev,
                        "status": e.status,
                        "page_size": 100,
                        "fetch_all_pages": True,
                        "max_pages": 3,
                        "sort_by": "start_time",
                        "sort_order": "desc",
                    },
                )
            )
            add(
                PlanStep(
                    id="summary",
                    tool="summarize_alarms",
                    purpose="Summarize alarms by name with recurrence and acknowledgement KPIs",
                    args={
                        "asset_ids": [{"$var": "asset_id"}],
                        **w,
                        "severity": sev,
                        "group_by": ["alarm_name"],
                        "kpis": ["alarm_count", "recurring_rate", "avg_ack_delay", "critical_count"],
                    },
                )
            )
            if with_trend:
                add(
                    PlanStep(
                        id="trend",
                        tool="get_alarm_trends",
                        purpose="Weekly alarm trend",
                        optional=True,
                        args={
                            "asset_ids": [{"$var": "asset_id"}],
                            **w,
                            "bucket": "weekly",
                            "metrics": ["alarm_count"],
                            "severity": sev,
                        },
                    )
                )
            add(
                PlanStep(
                    id="correlation",
                    tool="correlate_alarms",
                    optional=True,
                    purpose="Correlate alarms across the asset and its related assets",
                    args={
                        "asset_ids": [{"$var": "asset_id"}],
                        **w,
                        "lag_window_minutes": 15,
                        "severity_threshold": "medium",
                        "min_support": 2,
                        "include_related_assets": True,
                    },
                )
            )
            ctx_alarm = ctx.alarm["alarm_id"] if (ctx.alarm and e.refers_to_context and used_ctx.get("asset")) else None
            b["primary_alarm_id"] = Binding(
                "alarms",
                "primary_alarm",
                {"keywords": alarm_keywords, "prefer_recurring": prefer_recurring, "context_alarm_id": ctx_alarm},
            )
            add(
                PlanStep(
                    id="priority",
                    tool="score_alarm_priority",
                    optional=True,
                    purpose="Score the priority of the primary alarm",
                    args={"alarm_id": {"$var": "primary_alarm_id"}},
                )
            )
            add(
                PlanStep(
                    id="recommendations",
                    tool="get_operator_recommendations",
                    optional=True,
                    purpose="Get operator recommendations incl. related alarms and historical pattern",
                    args={
                        "alarm_id": {"$var": "primary_alarm_id"},
                        "include_related": True,
                        "include_asset_context": True,
                        "include_historical_pattern": True,
                    },
                )
            )

        name = intent.name
        if name in ("investigate", "related_assets"):
            if resolve_asset():
                investigate_core(
                    e.alarm_keywords, prefer_recurring=name == "investigate", with_trend=name == "investigate"
                )
        elif name == "site_priority":
            scope: dict[str, Any] = {"site": e.site or (ctx.site if not e.unit else None), "unit": e.unit}
            if not scope["site"] and not scope["unit"]:
                if resolve_asset(required=False):
                    scope = {"asset_id": {"$var": "asset_id"}}
                else:
                    plan.needs_clarification = "Which site or unit should I rank alarms for (e.g. EastRefinery)?"
            if not plan.needs_clarification:
                add(
                    PlanStep(
                        id="active_alarms",
                        tool="get_alarms",
                        purpose="List active alarms in scope",
                        args={
                            **{k: v for k, v in scope.items() if v},
                            "status": "active",
                            "severity": sev,
                            "page_size": 50,
                            "sort_by": "start_time",
                            "sort_order": "desc",
                        },
                    )
                )
                b["candidate_alarm_ids"] = Binding("active_alarms", "candidate_alarm_ids", {"limit": 6})
                add(
                    PlanStep(
                        id="priority_scan",
                        tool="score_alarm_priority",
                        purpose="Score each candidate active alarm",
                        foreach={"$var": "candidate_alarm_ids"},
                        args={"alarm_id": {"$item": True}},
                    )
                )
                b["primary_alarm_id"] = Binding("priority_scan", "best_priority_alarm")
                b["asset_id"] = Binding(
                    "priority_scan",
                    "asset_of_alarm",
                    {"alarm_id": {"$var": "primary_alarm_id"}},
                    depends_on=["priority_scan"],
                )
                add(
                    PlanStep(
                        id="asset_metadata",
                        tool="get_asset_metadata",
                        optional=True,
                        purpose="Fetch metadata of the asset with the top-priority alarm",
                        args={"asset_id": {"$var": "asset_id"}},
                    )
                )
                add(
                    PlanStep(
                        id="recommendations",
                        tool="get_operator_recommendations",
                        optional=True,
                        purpose="Recommendations for the top-priority alarm",
                        args={
                            "alarm_id": {"$var": "primary_alarm_id"},
                            "include_related": True,
                            "include_asset_context": True,
                            "include_historical_pattern": True,
                        },
                    )
                )
        elif name in ("procedure_lookup", "recommendation_check"):
            if ctx.alarm and (e.refers_to_context or not e.asset_query):
                used_ctx["asset"] = True
                b["primary_alarm_id"] = Binding(None, "literal", {"value": ctx.alarm["alarm_id"]})
                notes.append(
                    f"Using alarm from conversation context: {ctx.alarm['alarm_name']} ({ctx.alarm['alarm_id']})"
                )
                add(
                    PlanStep(
                        id="alarm_detail",
                        tool="get_alarm_details",
                        purpose="Confirm the alarm in context",
                        args={"alarm_id": {"$var": "primary_alarm_id"}},
                    )
                )
                if ctx.asset:
                    b["asset_id"] = Binding(None, "literal", {"value": ctx.asset["asset_id"]})
                    add(
                        PlanStep(
                            id="asset_metadata",
                            tool="get_asset_metadata",
                            optional=True,
                            purpose="Asset context for document filtering",
                            args={"asset_id": {"$var": "asset_id"}},
                        )
                    )
            elif resolve_asset(required=name == "recommendation_check"):
                add(
                    PlanStep(
                        id="asset_metadata",
                        tool="get_asset_metadata",
                        purpose="Asset context for document filtering",
                        args={"asset_id": {"$var": "asset_id"}},
                    )
                )
                add(
                    PlanStep(
                        id="alarms",
                        tool="get_alarms",
                        purpose="Find the most relevant recent alarm",
                        args={
                            "asset_id": {"$var": "asset_id"},
                            **w,
                            "severity": sev,
                            "status": e.status,
                            "page_size": 50,
                        },
                    )
                )
                b["primary_alarm_id"] = Binding("alarms", "primary_alarm", {"keywords": e.alarm_keywords})
            if name == "recommendation_check" and "primary_alarm_id" in b:
                add(
                    PlanStep(
                        id="recommendations",
                        tool="get_operator_recommendations",
                        purpose="Fetch the API recommendations to verify against documents",
                        args={
                            "alarm_id": {"$var": "primary_alarm_id"},
                            "include_related": False,
                            "include_asset_context": True,
                            "include_historical_pattern": False,
                        },
                    )
                )
        elif name == "alarm_kpi":
            scope = {k: v for k, v in {"site": e.site, "unit": e.unit}.items() if v}
            if not scope and resolve_asset(required=False):
                scope = {"asset_ids": [{"$var": "asset_id"}]}
            if not scope:
                plan.needs_clarification = "Which site or unit should I calculate alarm KPIs for (e.g. Unit 2)?"
            else:
                low = message.lower()
                calc = (
                    "nuisance_alarm_score"
                    if re.search(r"nuisance|chatter|stale|rationali", low)
                    else "operator_response_efficiency"
                    if "response" in low
                    else "alarm_flood_index"
                )
                if "asset_ids" not in scope:
                    add(
                        PlanStep(
                            id="flood",
                            tool="analyze_alarm_flood",
                            purpose="Detect alarm-flood windows",
                            args={**scope, **w, "threshold_count": 10, "rolling_window_minutes": 10},
                        )
                    )
                add(
                    PlanStep(
                        id="kpi",
                        tool="calculate_kpi",
                        purpose=f"Calculate {calc}",
                        args={"calculation_type": calc, **scope, **w},
                    )
                )
                add(
                    PlanStep(
                        id="rationalization",
                        tool="find_rationalization_candidates",
                        optional=True,
                        purpose="Find chattering/stale/frequent alarms",
                        args={**scope, **w},
                    )
                )
                add(
                    PlanStep(
                        id="summary",
                        tool="summarize_alarms",
                        optional=True,
                        purpose="Alarm counts by severity",
                        args={
                            **scope,
                            **w,
                            "group_by": ["severity"],
                            "kpis": ["alarm_count", "suppression_candidate_rate"],
                        },
                    )
                )

        # RAG retrieval participates in every plan and is fed by MCP outputs.
        rag_params = {
            "intent": name,
            "message": message,
            "keywords": e.alarm_keywords,
            "equipment_type": e.equipment_type,
            "asset_query": e.asset_query,
            "context_asset": (ctx.asset or {}) if (used_ctx.get("asset") or e.refers_to_context) else {},
            "context_alarm_name": (ctx.alarm or {}).get("alarm_name") if e.refers_to_context else None,
            "context_recommendations": ctx.recommendations if name == "recommendation_check" else [],
        }
        mcp_ids = [s.id for s in steps]
        b["rag_request"] = Binding(None, "rag_request", rag_params, depends_on=mcp_ids, tolerant=True)
        steps.append(
            PlanStep(
                id="retrieve_documents",
                kind="rag",
                tool="retrieve_documents",
                purpose="Retrieve procedures/manuals relevant to the investigated alarms (RAG)",
                args={"request": {"$var": "rag_request"}},
                depends_on=mcp_ids,
            )
        )
        # prune None args
        for s in steps:
            s.args = {k: v for k, v in s.args.items() if v is not None}
        return plan


def vars_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        if "$var" in value:
            return {value["$var"]}
        return set().union(*(vars_in(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(vars_in(v) for v in value)) if value else set()
    return set()


def entities_summary(e: Entities) -> dict[str, Any]:
    return e.model_dump(exclude_none=True, exclude_defaults=True)
