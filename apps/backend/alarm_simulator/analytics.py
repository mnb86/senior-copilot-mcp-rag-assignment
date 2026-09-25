"""Analytics used by the simulator endpoints (summary, trends, correlation, flood, etc.)."""

from __future__ import annotations

import bisect
import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from .catalog import ASSET_INDEX, ASSETS, CRITICALITY_WEIGHT, SEVERITY_ORDER, Asset
from .store import AlarmEvent, AlarmStore, iso

RECUR_WINDOW = timedelta(hours=24)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


# ---------------------------------------------------------------------------- assets
def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def search_assets(query: str, site: str | None, unit: str | None, limit: int) -> dict[str, Any]:
    q = query.strip().lower()
    q_tokens = _tokens(q)
    scored: list[tuple[float, Asset]] = []
    for a in ASSETS:
        if site and a.site.lower() != site.lower():
            continue
        if unit and a.unit.lower() != unit.lower():
            continue
        name = a.asset_name.lower()
        hay = f"{name} {a.asset_type} {a.description.lower()} {a.asset_id.lower()} {a.tag_prefix.lower()}"
        hay_tokens = set(_tokens(hay))
        name_tokens = set(_tokens(name))
        score = 0.0
        if not q_tokens:
            score = 0.1
        elif q == name or q == a.asset_id.lower():
            score = 100.0
        elif q in name:
            score = 50.0 + len(q) / max(len(name), 1)
        else:
            name_hits = sum(1 for t in q_tokens if t in name_tokens)
            hay_hits = sum(1 for t in q_tokens if t in hay_tokens or t.rstrip("s") in hay_tokens)
            if hay_hits == 0:
                continue
            # every numeric token (e.g. "101") must match to avoid returning the wrong unit
            nums = [t for t in q_tokens if t.isdigit()]
            if nums and not all(n in name_tokens or n in hay_tokens for n in nums):
                continue
            score = 10.0 * name_hits + 3.0 * hay_hits + (5.0 if a.asset_type in q_tokens else 0.0)
            score = score / len(q_tokens)
        scored.append((score, a))
    scored.sort(key=lambda s: (-s[0], s[1].asset_name))
    results = [
        {
            "asset_id": a.asset_id,
            "asset_name": a.asset_name,
            "asset_type": a.asset_type,
            "site": a.site,
            "unit": a.unit,
            "criticality": a.criticality,
            "match_score": round(s, 3),
        }
        for s, a in scored[:limit]
    ]
    return {"query": query, "total": len(scored), "results": results}


def asset_metadata(asset_id: str) -> dict[str, Any]:
    a = ASSET_INDEX.get(asset_id)
    if not a:
        raise ApiError(404, "ASSET_NOT_FOUND", f"Asset '{asset_id}' was not found")
    return {
        "asset_id": a.asset_id,
        "asset_name": a.asset_name,
        "asset_type": a.asset_type,
        "site": a.site,
        "unit": a.unit,
        "criticality": a.criticality,
        "manufacturer": a.manufacturer,
        "model": a.model,
        "install_date": a.install_date,
        "description": a.description,
        "tag_prefix": a.tag_prefix,
        "standby_asset_id": a.standby_asset_id,
        "operating_limits": dict(a.operating_limits),
        "configured_alarms": [
            {
                "alarm_name": d.name,
                "tag": f"{a.tag_prefix}-{d.code}",
                "alarm_type": d.alarm_type,
                "severity": d.severity,
                "limit": None if d.uom == "state" else d.limit,
                "uom": d.uom,
            }
            for d in a.alarms
        ],
        "related_assets": [
            {
                "asset_id": rid,
                "asset_name": ASSET_INDEX[rid].asset_name,
                "asset_type": ASSET_INDEX[rid].asset_type,
                "relationship": rel,
            }
            for rid, rel in a.related
        ],
    }


# ---------------------------------------------------------------------------- KPIs
def _recurring_flags(events: list[AlarmEvent]) -> list[bool]:
    """True for an occurrence that repeats the same alarm on the same asset within 24 h."""
    last_seen: dict[tuple[str, str], datetime] = {}
    flags: list[bool] = []
    for ev in sorted(events, key=lambda e: e.start_time):
        key = (ev.asset_id, ev.alarm_name)
        prev = last_seen.get(key)
        flags.append(prev is not None and ev.start_time - prev <= RECUR_WINDOW)
        last_seen[key] = ev.start_time
    return flags


def _is_suppression_candidate(ev: AlarmEvent) -> bool:
    if ev.chatter:
        return True
    return bool(ev.end_time and (ev.end_time - ev.start_time) > timedelta(minutes=180))


def compute_kpis(events: list[AlarmEvent], kpis: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    n = len(events)
    for k in kpis:
        if k == "alarm_count":
            out[k] = n
        elif k == "recurring_rate":
            flags = _recurring_flags(events)
            out[k] = round(sum(flags) / n, 4) if n else 0.0
        elif k == "avg_ack_delay":
            delays = [(e.ack_time - e.start_time).total_seconds() for e in events if e.ack_time]
            out[k] = round(mean(delays), 1) if delays else None
        elif k == "critical_count":
            out[k] = sum(1 for e in events if e.severity == "critical")
        elif k == "suppression_candidate_rate":
            out[k] = round(sum(1 for e in events if _is_suppression_candidate(e)) / n, 4) if n else 0.0
        elif k == "active_count":
            out[k] = sum(1 for e in events if e.status == "active")
        elif k == "avg_duration_minutes":
            d = [(e.end_time - e.start_time).total_seconds() / 60 for e in events if e.end_time]
            out[k] = round(mean(d), 2) if d else None
        else:
            raise ApiError(400, "UNKNOWN_KPI", f"Unsupported KPI '{k}'", {"supported": list(KPI_NAMES)})
    return out


KPI_DEFINITIONS: list[dict[str, str]] = [
    {
        "kpi": "alarm_count",
        "description": "Number of alarm occurrences in the window.",
        "unit": "count",
        "formula": "COUNT(alarms)",
    },
    {
        "kpi": "recurring_rate",
        "description": "Share of occurrences that repeat the same alarm on the same "
        "asset within 24 hours of the previous occurrence.",
        "unit": "ratio",
        "formula": "recurring / total",
    },
    {
        "kpi": "avg_ack_delay",
        "description": "Mean time from alarm start to operator acknowledgement.",
        "unit": "seconds",
        "formula": "AVG(ack_time - start_time)",
    },
    {
        "kpi": "critical_count",
        "description": "Number of critical-severity occurrences.",
        "unit": "count",
        "formula": "COUNT(severity = critical)",
    },
    {
        "kpi": "suppression_candidate_rate",
        "description": "Share of occurrences that are chattering (< 1 min) or stale (> 180 min).",
        "unit": "ratio",
        "formula": "(chattering + stale) / total",
    },
    {
        "kpi": "active_count",
        "description": "Occurrences that are still active.",
        "unit": "count",
        "formula": "COUNT(status = active)",
    },
    {
        "kpi": "avg_duration_minutes",
        "description": "Mean alarm duration for cleared occurrences.",
        "unit": "minutes",
        "formula": "AVG(end_time - start_time)",
    },
    {
        "kpi": "flood_percentage",
        "description": "Percentage of 10-minute windows in flood (>= 10 alarms), per ISA-18.2.",
        "unit": "percent",
        "formula": "flood_windows / total_windows * 100",
    },
]
KPI_NAMES = tuple(k["kpi"] for k in KPI_DEFINITIONS if k["kpi"] != "flood_percentage")


# ---------------------------------------------------------------------------- summary / trends
GROUPABLE = {"alarm_name", "asset_id", "asset_name", "severity", "alarm_type", "site", "unit", "status", "tag"}


def summarize(events: list[AlarmEvent], group_by: list[str], kpis: list[str]) -> dict[str, Any]:
    bad = [g for g in group_by if g not in GROUPABLE]
    if bad:
        raise ApiError(
            400, "INVALID_GROUP_BY", f"Unsupported group_by field(s): {bad}", {"supported": sorted(GROUPABLE)}
        )
    groups: dict[tuple[Any, ...], list[AlarmEvent]] = defaultdict(list)
    for ev in events:
        d = ev.to_dict()
        groups[tuple(d[g] for g in group_by)].append(ev)
    rows = []
    for key, evs in groups.items():
        row: dict[str, Any] = {"group": dict(zip(group_by, key, strict=True))}
        row.update(compute_kpis(evs, kpis))
        row["first_occurrence"] = iso(min(e.start_time for e in evs))
        row["last_occurrence"] = iso(max(e.start_time for e in evs))
        rows.append(row)
    rows.sort(key=lambda r: -len(groups[tuple(r["group"].values())]))
    return {"groups": rows, "totals": compute_kpis(events, kpis), "group_count": len(rows)}


def trends(events: list[AlarmEvent], start: datetime, end: datetime, bucket: str, metrics: list[str]) -> dict:
    step = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(days=7)}.get(bucket)
    if step is None:
        raise ApiError(400, "INVALID_BUCKET", "bucket must be one of hourly, daily, weekly")
    if (end - start) / step > 2000:
        raise ApiError(400, "TOO_MANY_BUCKETS", "Requested range produces more than 2000 buckets")
    buckets: list[dict[str, Any]] = []
    t = start
    idx: dict[int, list[AlarmEvent]] = defaultdict(list)
    for ev in events:
        idx[int((ev.start_time - start) / step)].append(ev)
    i = 0
    while t < end:
        row: dict[str, Any] = {"bucket_start": iso(t)}
        row.update(compute_kpis(idx.get(i, []), metrics))
        buckets.append(row)
        t += step
        i += 1
    counts = [len(idx.get(j, [])) for j in range(len(buckets))]
    half = len(counts) // 2
    first, second = sum(counts[:half]), sum(counts[half:])
    direction = "increasing" if second > first * 1.2 else "decreasing" if second < first * 0.8 else "stable"
    return {
        "bucket": bucket,
        "buckets": buckets,
        "trend": {"direction": direction, "first_half_count": first, "second_half_count": second},
    }


# ---------------------------------------------------------------------------- correlation
def correlate(events: list[AlarmEvent], lag_minutes: int, min_support: int, top_n: int = 25) -> list[dict]:
    """Directed co-occurrence: B starts within ``lag`` minutes after A (A != B)."""
    lag = timedelta(minutes=lag_minutes)
    by_key: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for ev in events:
        by_key[(ev.asset_id, ev.alarm_name)].append(ev.start_time)
    for v in by_key.values():
        v.sort()
    keys = list(by_key)
    total_windows = max(1, len(events))
    pairs: list[dict[str, Any]] = []
    for a in keys:
        ta = by_key[a]
        for b in keys:
            if a == b:
                continue
            tb = by_key[b]
            hits = 0
            lags: list[float] = []
            for t in ta:
                j = bisect.bisect_right(tb, t)
                if j < len(tb) and tb[j] - t <= lag:
                    hits += 1
                    lags.append((tb[j] - t).total_seconds() / 60)
            if hits < min_support:
                continue
            confidence = hits / len(ta)
            p_b = len(tb) / total_windows
            lift = confidence / p_b if p_b else 0.0
            pairs.append(
                {
                    "source": {
                        "asset_id": a[0],
                        "asset_name": ASSET_INDEX[a[0]].asset_name,
                        "alarm_name": a[1],
                        "occurrences": len(ta),
                    },
                    "target": {
                        "asset_id": b[0],
                        "asset_name": ASSET_INDEX[b[0]].asset_name,
                        "alarm_name": b[1],
                        "occurrences": len(tb),
                    },
                    "support": hits,
                    "confidence": round(confidence, 3),
                    "lift": round(lift, 2),
                    "avg_lag_minutes": round(mean(lags), 2),
                }
            )
    pairs.sort(key=lambda p: (-p["confidence"] * min(p["support"], 20), -p["support"]))
    return pairs[:top_n]


# ---------------------------------------------------------------------------- flood
def flood_analysis(events: list[AlarmEvent], start: datetime, end: datetime, threshold: int, window_min: int):
    times = sorted(e.start_time for e in events)
    win = timedelta(minutes=window_min)
    windows: list[dict[str, Any]] = []
    i = 0
    while i < len(times):
        j = bisect.bisect_left(times, times[i] + win)
        if j - i >= threshold:
            w_start, w_end = times[i], times[j - 1]
            # extend while dense
            while j < len(times) and times[j] - times[j - 1] <= timedelta(minutes=2):
                j += 1
                w_end = times[j - 1]
            evs = [e for e in events if w_start <= e.start_time <= w_end]
            top = Counter((e.asset.asset_name, e.alarm_name) for e in evs).most_common(5)
            windows.append(
                {
                    "start": iso(w_start),
                    "end": iso(w_end + timedelta(seconds=1)),
                    "alarm_count": len(evs),
                    "peak_rate_per_10min": j - i,
                    "top_alarms": [{"asset_name": k[0], "alarm_name": k[1], "count": c} for k, c in top],
                }
            )
            i = j
        else:
            i += 1
    total_windows = max(1, int((end - start) / win))
    flood_minutes = sum(
        (datetime.fromisoformat(w["end"][:-1]) - datetime.fromisoformat(w["start"][:-1])).total_seconds() / 60
        for w in windows
    )
    return {
        "flood_windows": windows,
        "flood_window_count": len(windows),
        "flood_percentage": round(100 * max(len(windows), flood_minutes / window_min) / total_windows, 4),
        "total_alarms": len(events),
        "threshold_count": threshold,
        "rolling_window_minutes": window_min,
    }


# ---------------------------------------------------------------------------- rationalization
def rationalization(events: list[AlarmEvent], recurrence_threshold: int, stale_threshold: int) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[AlarmEvent]] = defaultdict(list)
    for ev in events:
        groups[(ev.asset_id, ev.alarm_name)].append(ev)
    out: list[dict[str, Any]] = []
    for (asset_id, name), evs in groups.items():
        reasons = []
        chatter = sum(1 for e in evs if e.chatter)
        stale = sum(1 for e in evs if e.end_time and (e.end_time - e.start_time) > timedelta(minutes=stale_threshold))
        if len(evs) >= recurrence_threshold:
            reasons.append("frequent")
        if chatter >= 3:
            reasons.append("chattering")
        if stale >= 1:
            reasons.append("stale")
        if not reasons:
            continue
        recommendation = (
            "Apply deadband / on-delay (e.g. 5-10 s) and review setpoint"
            if "chattering" in reasons
            else "Review alarm setpoint and operator response; consider shelving policy"
            if "stale" in reasons
            else "Review alarm necessity and priority in rationalization workshop"
        )
        out.append(
            {
                "asset_id": asset_id,
                "asset_name": ASSET_INDEX[asset_id].asset_name,
                "alarm_name": name,
                "occurrences": len(evs),
                "chattering_occurrences": chatter,
                "stale_occurrences": stale,
                "reasons": reasons,
                "recommendation": recommendation,
            }
        )
    out.sort(key=lambda c: -c["occurrences"])
    return {
        "candidates": out,
        "candidate_count": len(out),
        "criteria": {"recurrence_threshold": recurrence_threshold, "stale_minutes_threshold": stale_threshold},
    }


# ---------------------------------------------------------------------------- priority
def priority_score(store: AlarmStore, ev: AlarmEvent) -> dict[str, Any]:
    asset = ev.asset
    sev = {"critical": 40, "high": 30, "medium": 15, "low": 5}[ev.severity]
    crit = CRITICALITY_WEIGHT[asset.criticality]
    safety = 15 if ev.alarm_type == "safety" else 0
    recent = [
        e
        for e in store.filter(asset_ids=[ev.asset_id], start=ev.start_time - timedelta(days=30), end=ev.start_time)
        if e.alarm_name == ev.alarm_name
    ]
    recurrence = min(15.0, 1.5 * len(recent))
    standing = 5 if ev.status == "active" and ev.ack_time is None else 0
    score = min(100.0, sev + crit + safety + recurrence + standing)
    band = "P1" if score >= 75 else "P2" if score >= 55 else "P3" if score >= 35 else "P4"
    factors = {
        "severity": sev,
        "asset_criticality": crit,
        "safety_impact": safety,
        "recurrence_30d": round(recurrence, 1),
        "unacknowledged_active": standing,
    }
    top = sorted(factors.items(), key=lambda kv: -kv[1])[:2]
    rationale = (
        f"{ev.severity.title()} {ev.alarm_type} alarm on {asset.criticality}-criticality asset "
        f"{asset.asset_name}; {len(recent)} occurrence(s) in the prior 30 days. "
        f"Dominant factors: {', '.join(k for k, _ in top)}."
    )
    return {
        "alarm_id": ev.alarm_id,
        "asset_id": ev.asset_id,
        "alarm_name": ev.alarm_name,
        "priority_score": round(score, 1),
        "priority_band": band,
        "factors": factors,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------- recommendations
_RULES: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    # (keyword in alarm name, [(action, rationale, urgency, category)])
    (
        "low suction pressure",
        [
            (
                "Reset the pump trip and restart the pump immediately to restore feedwater flow",
                "Restores feedwater supply to the boiler as fast as possible.",
                "immediate",
                "operate",
            ),
            (
                "Check deaerator level and pressure and restore level above 40%",
                "Low suction pressure is most often caused by low deaerator level.",
                "immediate",
                "inspect",
            ),
            (
                "Inspect the suction strainer differential pressure",
                "A fouled strainer restricts suction flow.",
                "soon",
                "inspect",
            ),
        ],
    ),
    (
        "pump trip",
        [
            (
                "Start the standby pump and confirm feedwater header pressure",
                "Maintains boiler feedwater supply while the tripped pump is investigated.",
                "immediate",
                "operate",
            ),
            (
                "Reset the pump trip and restart the pump immediately to restore feedwater flow",
                "Restores redundancy quickly.",
                "immediate",
                "operate",
            ),
            (
                "Review the trip first-out indication before any restart",
                "Identifies the initiating cause.",
                "soon",
                "inspect",
            ),
        ],
    ),
    (
        "bearing temperature",
        [
            (
                "Verify lube oil pressure and lube oil cooler outlet temperature",
                "Bearing temperature rise usually follows lube oil supply degradation.",
                "immediate",
                "inspect",
            ),
            (
                "Increase monitoring frequency of bearing temperature to every 15 minutes",
                "Trend confirms whether temperature is stabilising.",
                "soon",
                "operate",
            ),
            ("Take an oil sample for particle and water analysis", "Detects contamination.", "planned", "maintain"),
        ],
    ),
    (
        "vibration",
        [
            (
                "Compare vibration with the standby unit and check for recent process changes",
                "Separates process-induced vibration from mechanical faults.",
                "immediate",
                "inspect",
            ),
            (
                "If vibration exceeds the trip limit, transfer load to the standby unit and stop the machine",
                "Protects bearings and seals from damage.",
                "immediate",
                "operate",
            ),
            (
                "Request a vibration spectrum analysis",
                "Diagnoses imbalance, misalignment or bearing defects.",
                "soon",
                "maintain",
            ),
        ],
    ),
    (
        "discharge pressure",
        [
            (
                "Check discharge cooler outlet temperature and cooler fan / cooling water status",
                "High cooler outlet temperature raises discharge pressure.",
                "immediate",
                "inspect",
            ),
            (
                "Verify anti-surge valve position against controller output",
                "A deviating anti-surge valve changes compressor operating point.",
                "immediate",
                "inspect",
            ),
            (
                "Reduce compressor load within the approved operating envelope",
                "Keeps discharge pressure below the trip setting.",
                "soon",
                "operate",
            ),
        ],
    ),
    (
        "discharge temperature",
        [
            (
                "Check discharge cooler performance and fouling",
                "Discharge temperature follows cooler performance.",
                "soon",
                "inspect",
            ),
        ],
    ),
    (
        "outlet temperature",
        [
            (
                "Check cooler fan status and louvre position; clean fouled fin banks",
                "Reduced air flow raises outlet temperature.",
                "soon",
                "maintain",
            ),
        ],
    ),
    (
        "surge",
        [
            (
                "Confirm anti-surge controller is in automatic and valve is responding",
                "Surge protection depends on valve response.",
                "immediate",
                "operate",
            ),
        ],
    ),
    (
        "motor trip",
        [
            (
                "Check the motor control center bus voltage and protection relay first-out",
                "Upstream undervoltage is a common common-mode cause of multiple motor trips.",
                "immediate",
                "inspect",
            ),
            (
                "Do not attempt more than two restarts within one hour",
                "Protects the motor from thermal damage.",
                "immediate",
                "operate",
            ),
            (
                "Megger test the motor before restart if a ground fault is indicated",
                "Confirms insulation integrity.",
                "soon",
                "maintain",
            ),
        ],
    ),
    (
        "winding temperature",
        [
            (
                "Check motor cooling fan and ambient temperature; verify load current",
                "Overload and cooling loss raise winding temperature.",
                "immediate",
                "inspect",
            ),
        ],
    ),
    (
        "undervoltage",
        [
            (
                "Check incoming supply and transformer tap position; notify electrical",
                "Restores bus voltage.",
                "immediate",
                "inspect",
            ),
        ],
    ),
    (
        "level",
        [
            (
                "Verify level transmitter against local gauge glass",
                "Confirms instrument accuracy.",
                "immediate",
                "inspect",
            ),
            (
                "Check level control valve response",
                "Level excursions often trace to valve performance.",
                "soon",
                "inspect",
            ),
        ],
    ),
    (
        "seal",
        [
            (
                "Check seal flush / seal gas supply and differential pressure",
                "Maintains seal integrity.",
                "immediate",
                "inspect",
            ),
        ],
    ),
]
_DEFAULT_ACTIONS = [
    (
        "Acknowledge the alarm and verify the process value in the field",
        "Standard first response.",
        "immediate",
        "inspect",
    )
]


def recommendations(
    store: AlarmStore, ev: AlarmEvent, include_related: bool, include_asset_context: bool, include_historical: bool
) -> dict[str, Any]:
    asset = ev.asset
    if asset.sim_fault == "recommendations_unavailable":
        raise ApiError(
            503, "RECOMMENDATION_ENGINE_UNAVAILABLE", "Recommendation engine for this site is temporarily unavailable"
        )
    name = ev.alarm_name.lower()
    actions: list[tuple[str, str, str, str]] = []
    for kw, rules in _RULES:
        if kw in name:
            actions.extend(r for r in rules if r not in actions)
    if not actions:
        actions = list(_DEFAULT_ACTIONS)
    recs = []
    for i, (action, rationale, urgency, category) in enumerate(actions, start=1):
        h = int(hashlib.sha1(f"{ev.alarm_name}{action}".encode(), usedforsecurity=False).hexdigest()[:4], 16)
        recs.append(
            {
                "rank": i,
                "action_id": f"REC-{h:04X}",
                "action": action,
                "rationale": rationale,
                "urgency": urgency,
                "category": category,
                "confidence": round(0.9 - 0.08 * (i - 1), 2),
            }
        )
    out: dict[str, Any] = {
        "alarm_id": ev.alarm_id,
        "asset_id": ev.asset_id,
        "alarm_name": ev.alarm_name,
        "severity": ev.severity,
        "recommendations": recs,
        "generated_by": "rules-engine-v2.3 (simulated)",
    }
    if include_related:
        related_ids = [rid for rid, _ in asset.related]
        window_start, window_end = ev.start_time - timedelta(minutes=60), ev.start_time + timedelta(minutes=30)
        rel = store.filter(asset_ids=[*related_ids, asset.asset_id], start=window_start, end=window_end)
        out["related_alarms"] = [
            {
                "alarm_id": r.alarm_id,
                "asset_id": r.asset_id,
                "asset_name": r.asset.asset_name,
                "alarm_name": r.alarm_name,
                "severity": r.severity,
                "start_time": iso(r.start_time),
                "offset_minutes": round((r.start_time - ev.start_time).total_seconds() / 60, 1),
            }
            for r in rel
            if r.alarm_id != ev.alarm_id
        ][:15]
    if include_asset_context:
        out["asset_context"] = {
            "asset_name": asset.asset_name,
            "asset_type": asset.asset_type,
            "criticality": asset.criticality,
            "standby_asset_id": asset.standby_asset_id,
            "related_assets": [
                {"asset_id": rid, "asset_name": ASSET_INDEX[rid].asset_name, "relationship": r}
                for rid, r in asset.related
            ],
        }
    if include_historical:
        hist = [
            e
            for e in store.filter(asset_ids=[ev.asset_id], start=ev.start_time - timedelta(days=90), end=ev.start_time)
            if e.alarm_name == ev.alarm_name
        ]
        durations = [(e.end_time - e.start_time).total_seconds() / 60 for e in hist if e.end_time]
        precursors: Counter[str] = Counter()
        rel_ids = [*(rid for rid, _ in asset.related), asset.asset_id]
        for occ in hist:
            for prev in store.filter(
                asset_ids=rel_ids, start=occ.start_time - timedelta(minutes=20), end=occ.start_time
            ):
                if prev.alarm_name != occ.alarm_name or prev.asset_id != occ.asset_id:
                    precursors[f"{prev.asset.asset_name}: {prev.alarm_name}"] += 1
        out["historical_pattern"] = {
            "occurrences_90d": len(hist),
            "avg_duration_minutes": round(mean(durations), 1) if durations else None,
            "common_precursors": [{"alarm": k, "count": c} for k, c in precursors.most_common(5)],
        }
    return out


# ---------------------------------------------------------------------------- calculation code
CALC_TYPES: dict[str, str] = {
    "alarm_flood_index": "Percentage of 10-minute windows with >= 10 alarms (ISA-18.2 flood).",
    "critical_alarm_density": "Critical alarms per asset per day.",
    "operator_response_efficiency": "Share of alarms acknowledged within the target time by severity.",
    "nuisance_alarm_score": "Weighted score of chattering, stale and frequent alarms (0-100).",
}

_CALC_CODE = {
    "alarm_flood_index": "windows = rolling(alarms.start_time, '10min').count()\nresult = (windows >= 10).mean()*100",
    "critical_alarm_density": "crit = alarms[alarms.severity=='critical']\nresult = len(crit)/n_assets/n_days",
    "operator_response_efficiency": "target = {'critical':120,'high':300,'medium':900,'low':1800}\n"
    "result = mean(ack_delay <= target[severity])",
    "nuisance_alarm_score": "score = 0.5*chatter_rate + 0.3*stale_rate + 0.2*frequent_rate\nresult = score*100",
}


def calc_id(calc_type: str, filters: dict[str, Any]) -> str:
    h = hashlib.sha1(f"{calc_type}|{sorted(filters.items())}".encode(), usedforsecurity=False).hexdigest()[:10]
    return f"CALC-{h.upper()}"


def run_calculation(calc_type: str, events: list[AlarmEvent], start: datetime, end: datetime) -> dict[str, Any]:
    days = max(1e-9, (end - start).total_seconds() / 86400)
    if calc_type == "alarm_flood_index":
        f = flood_analysis(events, start, end, 10, 10)
        return {
            "value": f["flood_percentage"],
            "unit": "percent",
            "details": {"flood_windows": f["flood_window_count"], "total_alarms": len(events)},
        }
    if calc_type == "critical_alarm_density":
        assets = {e.asset_id for e in events} or {"none"}
        crit = sum(1 for e in events if e.severity == "critical")
        return {
            "value": round(crit / len(assets) / days, 4),
            "unit": "critical alarms / asset / day",
            "details": {"critical_alarms": crit, "assets": len(assets), "days": round(days, 1)},
        }
    if calc_type == "operator_response_efficiency":
        target = {"critical": 120, "high": 300, "medium": 900, "low": 1800}
        acked = [e for e in events if e.ack_time]
        ok = [e for e in acked if (e.ack_time - e.start_time).total_seconds() <= target[e.severity]]  # type: ignore[operator]
        by_sev = {
            s: round(sum(1 for e in ok if e.severity == s) / max(1, sum(1 for e in acked if e.severity == s)), 3)
            for s in target
        }
        return {
            "value": round(len(ok) / max(1, len(acked)), 4),
            "unit": "ratio",
            "details": {
                "acknowledged": len(acked),
                "within_target": len(ok),
                "by_severity": by_sev,
                "targets_seconds": target,
            },
        }
    if calc_type == "nuisance_alarm_score":
        n = max(1, len(events))
        chatter = sum(1 for e in events if e.chatter) / n
        stale = sum(1 for e in events if e.end_time and (e.end_time - e.start_time) > timedelta(minutes=180)) / n
        counts = Counter((e.asset_id, e.alarm_name) for e in events)
        frequent = sum(c for c in counts.values() if c >= 10) / n
        score = 100 * (0.5 * chatter + 0.3 * stale + 0.2 * frequent)
        return {
            "value": round(score, 2),
            "unit": "score (0-100)",
            "details": {
                "chatter_rate": round(chatter, 4),
                "stale_rate": round(stale, 4),
                "frequent_rate": round(frequent, 4),
            },
        }
    raise ApiError(400, "UNKNOWN_CALCULATION", f"Unsupported calculation_type '{calc_type}'")


def calc_code(calc_type: str) -> str:
    return _CALC_CODE[calc_type]


def severity_at_least(threshold: str) -> list[str]:
    t = SEVERITY_ORDER.get(threshold.lower())
    if t is None:
        raise ApiError(400, "INVALID_SEVERITY", f"Unknown severity '{threshold}'")
    return [s for s, v in SEVERITY_ORDER.items() if v >= t]
