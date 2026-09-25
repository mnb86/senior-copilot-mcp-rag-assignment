"""Deterministic, template-based answer composer (used offline and as the LLM fallback).

Only facts present in the structured evidence are rendered; every document statement carries a
citation marker ``[S#]`` and every data statement names its MCP tool.
"""

from __future__ import annotations

from typing import Any

from .domain import AlarmSummaryPanel, CauseFinding, Citation, Intent, RecommendationAssessment

STATUS_LABEL = {
    "consistent": "Consistent with procedure",
    "conflict": "CONFLICT with procedure",
    "not_covered": "Not covered by retrieved documents",
    "document_guidance": "Procedure step",
}


def _cite(ids: list[str]) -> str:
    return " " + " ".join(f"[{i}]" for i in ids) if ids else ""


def _pct(v: Any) -> str:
    return f"{v:.0%}" if isinstance(v, int | float) else "n/a"


def compose(
    intent: Intent,
    panel: AlarmSummaryPanel | None,
    causes: list[CauseFinding],
    recs: list[RecommendationAssessment],
    citations: list[Citation],
    low_confidence: bool,
    warnings: list[str],
    out: dict[str, Any],
    clarification: str | None = None,
) -> str:
    if clarification:
        return f"**More information needed.** {clarification}"
    lines: list[str] = []
    e = intent.entities
    name = intent.name

    # ---------------------------------------------------------------- headline
    if name == "site_priority" and panel and panel.primary_alarm:
        p = panel.primary_alarm
        lines.append(
            f"**Highest-priority active alarm in {e.site or e.unit or panel.scope_label}:** "
            f"{p.alarm_name} on {p.asset_name or panel.scope_label} ({p.alarm_id}) - priority "
            f"{p.priority_score} ({p.priority_band}) from `score_alarm_priority`."
        )
        if panel.priority_rationale:
            lines.append(f"Why: {panel.priority_rationale}")
        scan = [s for s in out.get("priority_scan") or [] if isinstance(s, dict)]
        if len(scan) > 1:
            ranked = sorted(scan, key=lambda s: -s["priority_score"])
            lines.append(
                "Ranking of active alarms: "
                + "; ".join(
                    f"{s['alarm_name']} ({s['asset_id']}) {s['priority_score']} {s['priority_band']}"
                    for s in ranked[:5]
                )
                + "."
            )
    elif panel and panel.asset:
        a = panel.asset
        w = panel.window.label if panel.window else ""
        head = f"**{a['asset_name']}** ({a['asset_id']}, {a['site']} {a['unit']}, criticality {a['criticality']})"
        if "alarms" in out or "summary" in out:
            sev = ", ".join(f"{v} {k}" for k, v in panel.by_severity.items())
            sev = f" ({sev})" if sev else ""
            lines.append(f"{head}: {panel.total_alarms} alarm(s) {w}{sev} from `get_alarms` / `summarize_alarms`.")
        else:
            lines.append(f"{head}.")
        if panel.primary_alarm and "alarms" not in out:
            p = panel.primary_alarm
            lines.append(
                f"Alarm under review: {p.alarm_id} '{p.alarm_name}' ({p.severity}, {p.status}, started "
                f"{p.start_time}) from `get_alarm_details`."
            )
        if panel.top_alarm_groups:
            g = panel.top_alarm_groups[0]
            lines.append(
                f"Most frequent: **{g['alarm_name']}** - {g['count']} occurrences, "
                f"{_pct(g.get('recurring_rate'))} recurring within 24 h, average acknowledgement "
                f"{g.get('avg_ack_delay_s') or 'n/a'} s."
            )
        if panel.trend:
            lines.append(
                f"Weekly trend: {panel.trend['direction']} ({panel.trend['first_half_count']} -> "
                f"{panel.trend['second_half_count']} alarms, first vs second half)."
            )
        if panel.active_alarms:
            lines.append(
                "Active now: "
                + "; ".join(
                    f"{r.alarm_name} ({r.severity}{', unacknowledged' if not r.acknowledged else ''})"
                    for r in panel.active_alarms[:4]
                )
                + "."
            )
        if panel.primary_alarm and panel.primary_alarm.priority_score is not None:
            p = panel.primary_alarm
            lines.append(f"Focus alarm {p.alarm_id} '{p.alarm_name}' scored {p.priority_score} ({p.priority_band}).")
    elif panel and panel.kpis:
        lines.append(f"**Alarm KPIs for {panel.scope_label}** ({panel.window.label if panel.window else ''}):")
        for k, v in panel.kpis.items():
            if isinstance(v, dict) and "value" in v:
                lines.append(f"- {k.replace('_', ' ')}: **{v['value']} {v['unit']}** (`calculate_kpi`)")
            elif isinstance(v, dict):
                lines.append(f"- {k}: " + ", ".join(f"{kk.replace('_', ' ')} {vv}" for kk, vv in v.items()))
            else:
                lines.append(f"- {k.replace('_', ' ')}: {v}")
        cands = (out.get("rationalization") or {}).get("candidates") or []
        if cands:
            lines.append(
                "Top rationalization candidates: "
                + "; ".join(
                    f"{c['asset_name']} {c['alarm_name']} ({', '.join(c['reasons'])}, {c['occurrences']}x)"
                    for c in cands[:4]
                )
                + "."
            )

    # ---------------------------------------------------------------- procedure lookup
    if name == "procedure_lookup":
        procs = [
            c
            for c in citations
            if c.doc_type in ("operating_procedure", "safety_instruction", "troubleshooting_guide")
            and c.trust_level != "external"
        ]
        alarm = panel.primary_alarm.alarm_name if panel and panel.primary_alarm else ", ".join(e.alarm_keywords)
        if procs:
            about = [c for c in procs if alarm and alarm.lower() in c.section.lower()]
            best = about[0] if about else procs[0]
            procs = [best] + [c for c in procs if c is not best]
            lines.append(
                f"\n**Applicable procedure{' for ' + repr(alarm) if alarm else ''}:** {best.doc_id} rev "
                f"{best.revision or '-'} - {best.title}, section '{best.section}' [{best.id}]"
            )
            others = list(dict.fromkeys(f"{c.doc_id} '{c.section}' [{c.id}]" for c in procs[1:4]))
            if others:
                lines.append("Also relevant: " + "; ".join(others) + ".")
        else:
            lines.append("\nNo approved operating procedure matched this alarm in the document corpus.")

    # ---------------------------------------------------------------- related assets
    if name == "related_assets" and panel and panel.related_assets:
        lines.append("\n**Related assets to inspect** (from `get_asset_metadata`):")
        for ra in panel.related_assets:
            lines.append(f"- {ra['asset_name']} ({ra['asset_id']}) - {ra['relationship'].replace('_', ' ')}")
        rel = (out.get("recommendations") or {}).get("related_alarms") or []
        if rel:
            lines.append(
                "Alarms on related assets around the focus alarm: "
                + "; ".join(f"{x['asset_name']} {x['alarm_name']} ({x['offset_minutes']:+} min)" for x in rel[:5])
                + "."
            )

    # ---------------------------------------------------------------- causes
    if causes:
        lines.append("\n**Likely contributing factors**")
        for cause in causes:
            doc_refs = [ev.ref for ev in cause.evidence if ev.kind == "document"]
            tool = next((ev for ev in cause.evidence if ev.kind == "tool"), None)
            detail = f" - {tool.detail} (`{tool.ref}`)" if tool else ""
            lines.append(f"- **{cause.cause}** [{cause.confidence}]{detail}{_cite(doc_refs)}")

    # ---------------------------------------------------------------- recommendations
    api = [r for r in recs if r.source == "api"]
    docs = [r for r in recs if r.source == "document"]
    if name == "recommendation_check" and api:
        counts = {s: sum(1 for r in api if r.status == s) for s in ("consistent", "conflict", "not_covered")}
        lines.append(
            f"\n**Consistency check:** {counts['consistent']} of {len(api)} API recommendation(s) are "
            f"consistent with the retrieved documents, {counts['conflict']} conflict, "
            f"{counts['not_covered']} not covered."
        )
    if api:
        lines.append("\n**Recommended actions (API, checked against documents)**")
        for ar in api:
            flag = "**Do not follow as written** - " if ar.status == "conflict" else ""
            lines.append(
                f"- {flag}{ar.action} _({ar.urgency}; {STATUS_LABEL[ar.status]})_{_cite(ar.citations)}"
                + (f" - {ar.explanation}" if ar.status == "conflict" else "")
            )
    if docs:
        lines.append("\n**Procedure guidance**")
        for dr in docs:
            lines.append(f"- {dr.action}{_cite(dr.citations)}")

    # ---------------------------------------------------------------- document excerpts (RAG-only answers)
    if citations and (name == "general_question" or (not api and not docs and name != "procedure_lookup")):
        lines.append("\n**What the documents say**")
        for cit in citations[:3]:
            if cit.trust_level == "external":
                continue
            lines.append(f"- {cit.doc_id}, '{cit.section}': \"{cit.snippet}\" [{cit.id}]")

    # ---------------------------------------------------------------- sources
    if citations:
        lines.append("\n**Applicable documents**")
        by_doc: dict[str, list[Citation]] = {}
        for cit in citations:
            by_doc.setdefault(cit.doc_id, []).append(cit)
        for doc_id, cs in by_doc.items():
            c0 = cs[0]
            tag = " (external, unverified)" if c0.trust_level == "external" else ""
            secs = "; ".join(f"[{c.id}] '{c.section}'" for c in cs)
            lines.append(f"- **{doc_id}** rev {c0.revision or '-'} - {c0.title}{tag}: {secs}")
    if low_confidence:
        lines.append(
            "\n_Document retrieval confidence is low: no procedure passage closely matches this request. "
            "Treat document guidance as indicative and confirm with the responsible engineer._"
        )
    if warnings:
        lines.append("\n**Data gaps / degraded sources**")
        lines.extend(f"- {w}" for w in warnings)
    if not lines:
        lines.append(
            "I could not find alarm data or document evidence for this request. Try naming an asset "
            "(e.g. 'Boiler Feed Pump 101'), a site (e.g. 'EastRefinery') or an alarm type."
        )
    return "\n".join(lines).strip()
