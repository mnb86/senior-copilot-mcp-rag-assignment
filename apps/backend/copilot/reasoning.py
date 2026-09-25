"""Combine structured MCP evidence with retrieved documents into a grounded investigation result.

Everything produced here is traceable: causes reference the MCP step that produced the evidence and
document citations (``S1``...), recommendations are checked against retrieved passages.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from rag.retrieval.models import RetrievalResult
from rag.retrieval.text import tokenize

from .domain import (
    AlarmRow,
    AlarmSummaryPanel,
    CauseFinding,
    Citation,
    Evidence,
    Intent,
    RecommendationAssessment,
    TimeWindow,
)

ACTION_VERBS = {
    "restart",
    "reset",
    "start",
    "open",
    "close",
    "bypass",
    "disable",
    "increase",
    "reduce",
    "continue",
    "run",
    "operate",
    "shelve",
    "defeat",
    "stop",
    "transfer",
    "resume",
    "suppress",
    "override",
}
PROHIBIT_AFTER = re.compile(
    r"\b(?:do not|don't|never|must not|shall not|should not|is not permitted to|"
    r"not permitted to)\b([^.;\n]{5,200})",
    re.I,
)
PROHIBIT_BEFORE = re.compile(r"([^.;\n:]{10,200}?)\b(?:is|are)\s+(?:prohibited|not permitted|not allowed)\b", re.I)
STEP_LINE = re.compile(r"^\s*\d+\.\s+(.{15,300})$", re.M)
IMPERATIVE = re.compile(
    r"^(check|start|stop|inspect|verify|confirm|request|reduce|transfer|compare|take|record|"
    r"notify|inform|wash|replace|trend|allow|megger|apply|do not|never|if )",
    re.I,
)
SEV = ("critical", "high", "medium", "low")
GUARDED = re.compile(r"^\s*(do not|don't|never|avoid)\b|\b(before|until|only after|once|unless|provided that)\b", re.I)


# ---------------------------------------------------------------------------- citations
def build_citations(retrieval: RetrievalResult | None) -> list[Citation]:
    if not retrieval:
        return []
    cites = []
    for i, rc in enumerate(retrieval.results, start=1):
        c = rc.chunk
        snippet = re.sub(r"\s+", " ", c.text).strip()
        cites.append(
            Citation(
                id=f"S{i}",
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                title=c.title,
                section=c.section,
                doc_type=c.doc_type,
                revision=c.revision,
                source_path=c.source_path,
                score=rc.score,
                confidence=rc.confidence,
                snippet=snippet[:420] + ("..." if len(snippet) > 420 else ""),
                trust_level=c.trust_level,
            )
        )
    return cites


def _chunk_text(retrieval: RetrievalResult | None) -> dict[str, str]:
    if not retrieval:
        return {}
    return {f"S{i}": rc.chunk.text for i, rc in enumerate(retrieval.results, start=1)}


# ---------------------------------------------------------------------------- summary panel
def _row(a: dict[str, Any], prio: dict[str, Any] | None = None) -> AlarmRow:
    return AlarmRow(
        alarm_id=a["alarm_id"],
        asset_name=a.get("asset_name", ""),
        alarm_name=a["alarm_name"],
        severity=a["severity"],
        status=a["status"],
        start_time=a["start_time"],
        acknowledged=bool(a.get("acknowledged")),
        priority_score=(prio or {}).get("priority_score"),
        priority_band=(prio or {}).get("priority_band"),
    )


def build_summary(
    intent: Intent, out: dict[str, Any], window: TimeWindow, bindings: dict[str, Any]
) -> AlarmSummaryPanel | None:
    meta = (out.get("asset_metadata") or {}).get("asset")
    alarms = (out.get("alarms") or out.get("active_alarms") or {}).get("alarms") or []
    if not (meta or alarms or out.get("summary") or out.get("kpi") or out.get("alarm_detail")):
        return None
    e = intent.entities
    scope = meta["asset_name"] if meta else (e.site or e.unit or "Selected scope")
    panel = AlarmSummaryPanel(
        asset={
            k: meta.get(k)
            for k in ("asset_id", "asset_name", "asset_type", "site", "unit", "criticality", "standby_asset_id")
        }
        if meta
        else None,
        scope_label=scope,
        window=window,
    )
    sev_counts = Counter(a["severity"] for a in alarms)
    summary = out.get("summary") or {}
    totals = summary.get("totals") or {}
    panel.total_alarms = int(totals.get("alarm_count", len(alarms)))
    panel.by_severity = {s: sev_counts.get(s, 0) for s in SEV if sev_counts.get(s)}
    if summary.get("groups") and "severity" in (summary["groups"][0].get("group") or {}):
        panel.by_severity = {g["group"]["severity"]: g.get("alarm_count", 0) for g in summary["groups"]}
    prio_by_id: dict[str, dict[str, Any]] = {}
    for p in [out.get("priority"), *(out.get("priority_scan") or [])]:
        if isinstance(p, dict) and p.get("alarm_id"):
            prio_by_id[p["alarm_id"]] = p
    panel.active_alarms = [_row(a, prio_by_id.get(a["alarm_id"])) for a in alarms if a["status"] == "active"][:10]
    panel.top_alarm_groups = [
        {
            "alarm_name": g["group"].get("alarm_name") or g["group"].get("severity"),
            "count": g.get("alarm_count"),
            "recurring_rate": g.get("recurring_rate"),
            "avg_ack_delay_s": g.get("avg_ack_delay"),
            "critical_count": g.get("critical_count"),
            "last_occurrence": g.get("last_occurrence"),
        }
        for g in (summary.get("groups") or [])[:6]
    ]
    if out.get("trend"):
        panel.trend = {
            **out["trend"]["trend"],
            "bucket": out["trend"]["bucket"],
            "series": [{"t": b["bucket_start"][:10], "v": b.get("alarm_count", 0)} for b in out["trend"]["buckets"]],
        }
    primary_id = bindings.get("primary_alarm_id")
    primary = next((a for a in alarms if a["alarm_id"] == primary_id), None)
    if primary is None and out.get("alarm_detail"):
        primary = out["alarm_detail"]["alarm"]
    if primary:
        panel.primary_alarm = _row(primary, prio_by_id.get(primary["alarm_id"]))
    elif primary_id and primary_id in prio_by_id:
        p = prio_by_id[primary_id]
        panel.primary_alarm = AlarmRow(
            alarm_id=primary_id,
            asset_name=p.get("asset_id", ""),
            alarm_name=p["alarm_name"],
            severity="high",
            status="active",
            start_time="",
            priority_score=p["priority_score"],
            priority_band=p["priority_band"],
        )
    if primary_id and primary_id in prio_by_id:
        panel.priority_rationale = prio_by_id[primary_id].get("rationale")
    if meta:
        panel.related_assets = meta.get("related_assets") or []
    if out.get("kpi"):
        k = out["kpi"]
        panel.kpis[k["calculation_type"]] = k["result"]
    if out.get("flood"):
        f = out["flood"]
        panel.kpis["flood"] = {
            "flood_windows": f["flood_window_count"],
            "flood_percentage": f["flood_percentage"],
            "total_alarms": f["total_alarms"],
        }
    if out.get("rationalization"):
        panel.kpis["rationalization_candidates"] = out["rationalization"]["candidate_count"]
    return panel


# ---------------------------------------------------------------------------- causes
def _doc_support(text_by_id: dict[str, str], *phrases: str) -> list[str]:
    refs = []
    for sid, text in text_by_id.items():
        toks = set(tokenize(text))
        for ph in phrases:
            pt = [t for t in tokenize(ph) if len(t) > 2]
            if pt and sum(t in toks for t in pt) / len(pt) >= 0.67:
                refs.append(sid)
                break
    return refs


def build_causes(
    out: dict[str, Any], retrieval: RetrievalResult | None, bindings: dict[str, Any]
) -> list[CauseFinding]:
    text_by_id = _chunk_text(retrieval)
    meta = (out.get("asset_metadata") or {}).get("asset") or {}
    asset_id = meta.get("asset_id") or bindings.get("asset_id")
    focus_names = {g["group"].get("alarm_name") for g in ((out.get("summary") or {}).get("groups") or [])[:3]}
    rec = out.get("recommendations") or {}
    if rec.get("alarm_name"):
        focus_names.add(rec["alarm_name"])
    causes: list[CauseFinding] = []
    seen: set[str] = set()
    for pair in (out.get("correlation") or {}).get("pairs") or []:
        src, tgt = pair["source"], pair["target"]
        if asset_id and tgt["asset_id"] != asset_id:
            continue  # only causes that lead to alarms on the investigated asset
        if not asset_id and tgt["alarm_name"] not in focus_names:
            continue
        if src["asset_id"] == tgt["asset_id"] and src["alarm_name"] == tgt["alarm_name"]:
            continue
        key = f"{src['asset_id']}|{src['alarm_name']}"
        if key in seen:
            continue
        seen.add(key)
        conf = pair["confidence"]
        level = (
            "high"
            if conf >= 0.5 and pair["support"] >= 5
            else "medium"
            if conf >= 0.25 or pair["support"] >= 3
            else "low"
        )
        same_asset = src["asset_id"] == tgt["asset_id"]
        where = "on the same asset" if same_asset else f"on related asset {src['asset_name']}"
        ev = [
            Evidence(
                kind="tool",
                ref="correlate_alarms",
                detail=f"'{src['alarm_name']}' {where} preceded '{tgt['alarm_name']}' "
                f"{pair['support']} times ({conf:.0%} of source occurrences, avg lag "
                f"{pair['avg_lag_minutes']} min, lift {pair['lift']})",
            )
        ]
        for sid in _doc_support(text_by_id, f"{src['asset_name']} {src['alarm_name']}", src["alarm_name"])[:2]:
            ev.append(Evidence(kind="document", ref=sid, detail="Procedure/manual describes this causal link"))
        causes.append(
            CauseFinding(
                cause=f"{src['asset_name']}: {src['alarm_name']} leading to {tgt['alarm_name']}",
                confidence=level,
                evidence=ev,
            )
        )
        if len(causes) >= 4:
            break
    for pre in ((rec.get("historical_pattern") or {}).get("common_precursors") or [])[:3]:
        label = pre["alarm"]
        if any(label.split(": ")[-1] in c.cause and label.split(": ")[0] in c.cause for c in causes):
            continue
        causes.append(
            CauseFinding(
                cause=f"Recurring precursor: {label}",
                confidence="medium" if pre["count"] >= 3 else "low",
                evidence=[
                    Evidence(
                        kind="tool",
                        ref="get_operator_recommendations",
                        detail=f"Seen within 20 min before the alarm {pre['count']} time(s) in 90 days",
                    )
                ],
            )
        )
    groups = (out.get("summary") or {}).get("groups") or []
    if groups and (groups[0].get("recurring_rate") or 0) >= 0.1:
        g = groups[0]
        causes.append(
            CauseFinding(
                cause=f"Chronic recurrence of '{g['group'].get('alarm_name')}' "
                "(symptom of an unresolved upstream issue)",
                confidence="medium",
                evidence=[
                    Evidence(
                        kind="tool",
                        ref="summarize_alarms",
                        detail=f"{g.get('alarm_count')} occurrences; {g.get('recurring_rate', 0):.0%} "
                        f"re-occurred within 24 h",
                    )
                ]
                + [
                    Evidence(kind="document", ref=s, detail="Guidance on recurring alarms")
                    for s in _doc_support(text_by_id, "recurring alarms")[:1]
                ],
            )
        )
    trend = (out.get("trend") or {}).get("trend")
    if trend and trend.get("direction") == "increasing":
        causes.append(
            CauseFinding(
                cause="Alarm frequency is increasing over the window",
                confidence="medium",
                evidence=[
                    Evidence(
                        kind="tool",
                        ref="get_alarm_trends",
                        detail=f"{trend['first_half_count']} alarms in first half vs "
                        f"{trend['second_half_count']} in second half",
                    )
                ],
            )
        )
    return causes[:6]


# ---------------------------------------------------------------------------- recommendation checks
def _prohibitions(text: str) -> list[str]:
    clauses = [m.group(1).strip() for m in PROHIBIT_AFTER.finditer(text)]
    clauses += [m.group(1).strip() for m in PROHIBIT_BEFORE.finditer(text)]
    return clauses


def assess_recommendations(
    out: dict[str, Any], citations: list[Citation], retrieval: RetrievalResult | None
) -> list[RecommendationAssessment]:
    text_by_id = _chunk_text(retrieval)
    trust = {c.id: c.trust_level for c in citations}
    recs = (out.get("recommendations") or {}).get("recommendations") or []
    results: list[RecommendationAssessment] = []
    for r in recs:
        rt = set(tokenize(r["action"]))
        verbs = rt & ACTION_VERBS
        # A recommendation that is itself a restriction ("do not ...") or is conditional ("... before restart",
        # "only after ...") cannot contradict a documented prohibition; only unconditional affirmative actions can.
        guarded = bool(GUARDED.search(r["action"]))
        conflict: tuple[str, str] | None = None
        best: tuple[float, str] = (0.0, "")
        for sid, text in text_by_id.items():
            if trust.get(sid) == "external":
                continue  # unverified sources may support context but never overrule/confirm actions
            for clause in [] if guarded else _prohibitions(text):
                ct = set(tokenize(clause))
                if len(rt & ct) >= 3 and verbs & ct:
                    conflict = (sid, clause)
                    break
            if conflict:
                break
            toks = set(tokenize(text))
            content = [t for t in rt if len(t) > 2]
            ratio = sum(t in toks for t in content) / max(1, len(content))
            if ratio > best[0]:
                best = (ratio, sid)
        if conflict:
            results.append(
                RecommendationAssessment(
                    action=r["action"],
                    source="api",
                    urgency=r.get("urgency"),
                    status="conflict",
                    explanation=f'Conflicts with documented restriction: "...{conflict[1][:180]}". The approved '
                    f"procedure takes precedence.",
                    citations=[conflict[0]],
                )
            )
        elif best[0] >= 0.5:
            results.append(
                RecommendationAssessment(
                    action=r["action"],
                    source="api",
                    urgency=r.get("urgency"),
                    status="consistent",
                    explanation=f"Supported by documented guidance ({best[0]:.0%} term overlap).",
                    citations=[best[1]],
                )
            )
        else:
            results.append(
                RecommendationAssessment(
                    action=r["action"],
                    source="api",
                    urgency=r.get("urgency"),
                    status="not_covered",
                    explanation="No retrieved procedure passage covers this action; verify with the process engineer.",
                    citations=[],
                )
            )
    # document-derived steps from the top procedural passages (numbered steps; imperative sentences as
    # a fallback, e.g. when the recommendation engine is unavailable)
    added = 0
    alarm = str((out.get("recommendations") or {}).get("alarm_name") or "").lower()
    procedural = [
        c
        for c in citations
        if c.doc_type in ("operating_procedure", "troubleshooting_guide", "safety_instruction", "maintenance_manual")
        and c.trust_level != "external"
    ]
    procedural.sort(key=lambda c: 0 if alarm and alarm in c.section.lower() else 1)
    for c in procedural:
        text = re.sub(r"\n\s{2,}(?=\S)", " ", text_by_id.get(c.id, ""))
        steps = [m.group(1) for m in STEP_LINE.finditer(text)]
        if not steps and not recs:
            steps = [sn for sn in re.split(r"(?<=[.])\s+", re.sub(r"\s+", " ", text)) if IMPERATIVE.match(sn)][:3]
        for raw in steps:
            step = re.sub(r"\s+", " ", raw.replace("**", "")).strip()
            if any(_similar(step, x.action) for x in results):
                continue
            results.append(
                RecommendationAssessment(
                    action=step,
                    source="document",
                    status="document_guidance",
                    explanation=f"From {c.doc_id}, {c.section}",
                    citations=[c.id],
                )
            )
            added += 1
            if added >= 4:
                return results
        if added >= 2:
            break
    return results


def _similar(a: str, b: str) -> bool:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.6
