"""Deterministic synthetic alarm-event store.

All data is generated from a fixed random seed relative to an *anchor* time
(default: today at 00:00 UTC) so that relative queries such as "last 90 days"
always return data, while the event pattern stays reproducible.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .catalog import ACTIVE_SEEDS, ASSET_INDEX, ASSETS, FLOOD_SEEDS, AlarmDef, Asset

HISTORY_DAYS = 365


@dataclass
class AlarmEvent:
    alarm_id: str
    asset_id: str
    alarm_name: str
    tag: str
    alarm_type: str
    severity: str
    start_time: datetime
    end_time: datetime | None
    ack_time: datetime | None
    process_value: float | None
    limit: float | None
    uom: str
    status: str  # active | cleared | shelved
    chatter: bool = False

    @property
    def asset(self) -> Asset:
        return ASSET_INDEX[self.asset_id]

    def to_dict(self) -> dict[str, Any]:
        asset = self.asset
        ack_delay = (self.ack_time - self.start_time).total_seconds() if self.ack_time else None
        duration = (self.end_time - self.start_time).total_seconds() / 60 if self.end_time else None
        return {
            "alarm_id": self.alarm_id,
            "asset_id": self.asset_id,
            "asset_name": asset.asset_name,
            "asset_type": asset.asset_type,
            "site": asset.site,
            "unit": asset.unit,
            "alarm_name": self.alarm_name,
            "tag": self.tag,
            "alarm_type": self.alarm_type,
            "severity": self.severity,
            "status": self.status,
            "acknowledged": self.ack_time is not None,
            "start_time": iso(self.start_time),
            "end_time": iso(self.end_time) if self.end_time else None,
            "ack_time": iso(self.ack_time) if self.ack_time else None,
            "ack_delay_seconds": round(ack_delay, 1) if ack_delay is not None else None,
            "duration_minutes": round(duration, 2) if duration is not None else None,
            "process_value": self.process_value,
            "limit": self.limit,
            "uom": self.uom,
            "message": _message(self, asset),
        }


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str) -> datetime:
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _message(ev: AlarmEvent, asset: Asset) -> str:
    if ev.uom == "state" or ev.process_value is None:
        return f"{asset.asset_name}: {ev.alarm_name}"
    return f"{asset.asset_name}: {ev.alarm_name} ({ev.process_value} {ev.uom}, limit {ev.limit} {ev.uom})"


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(rng.gauss(lam, math.sqrt(lam))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


class AlarmStore:
    def __init__(self, anchor: datetime, seed: int = 42) -> None:
        self.anchor = anchor
        self.seed = seed
        self.window_start = anchor - timedelta(days=HISTORY_DAYS)
        self.events: list[AlarmEvent] = []
        self._by_id: dict[str, AlarmEvent] = {}
        self._generate()

    # ------------------------------------------------------------------ generation
    def _generate(self) -> None:
        rng = random.Random(self.seed)
        raw: list[tuple[datetime, str, AlarmDef, bool]] = []  # (start, asset_id, def, chatter-member)
        recent_start = self.anchor - timedelta(days=90)

        def add_with_effects(start: datetime, asset: Asset, adef: AlarmDef, depth: int = 0) -> None:
            raw.append((start, asset.asset_id, adef, False))
            if depth > 2:
                return
            for eff in adef.effects:
                if rng.random() < eff.probability:
                    lag = rng.uniform(*eff.lag_minutes)
                    target = ASSET_INDEX[eff.asset_id]
                    tdef = next(d for d in target.alarms if d.name == eff.alarm_name)
                    add_with_effects(start + timedelta(minutes=lag), target, tdef, depth + 1)

        for asset in ASSETS:
            for adef in asset.alarms:
                # Older period (first 275 days) and recent period (last 90 days) with optional multiplier.
                for period_start, days, mult in (
                    (self.window_start, HISTORY_DAYS - 90, 1.0),
                    (recent_start, 90, adef.recent_multiplier),
                ):
                    n = _poisson(rng, adef.rate_per_day * days * mult)
                    for _ in range(n):
                        start = period_start + timedelta(seconds=rng.uniform(0, days * 86400))
                        if adef.chatter:
                            burst = rng.randint(3, 7)
                            t = start
                            for _ in range(burst):
                                raw.append((t, asset.asset_id, adef, True))
                                t += timedelta(seconds=rng.uniform(20, 240))
                        else:
                            add_with_effects(start, asset, adef)

        # Flood bursts on Unit 2.
        unit2 = [a for a in ASSETS if a.site == "NorthPlant" and a.unit == "Unit 2"]
        for days_before, count in FLOOD_SEEDS:
            base = self.anchor - timedelta(days=days_before)
            for _ in range(count):
                asset = rng.choice(unit2)
                adef = rng.choice(asset.alarms)
                raw.append((base + timedelta(seconds=rng.uniform(0, 540)), asset.asset_id, adef, False))

        raw = [r for r in raw if self.window_start <= r[0] < self.anchor - timedelta(hours=6)]
        raw.sort(key=lambda r: (r[0], r[1], r[2].name))

        events: list[AlarmEvent] = []
        for start, asset_id, adef, chatter in raw:
            events.append(self._make_event(rng, start, ASSET_INDEX[asset_id], adef, chatter, active=False))

        for asset_id, alarm_name, hours, acked in ACTIVE_SEEDS:
            asset = ASSET_INDEX[asset_id]
            adef = next(d for d in asset.alarms if d.name == alarm_name)
            start = self.anchor - timedelta(hours=hours)
            ev = self._make_event(rng, start, asset, adef, False, active=True)
            ev.ack_time = start + timedelta(minutes=rng.uniform(2, 12)) if acked else None
            events.append(ev)

        events.sort(key=lambda e: (e.start_time, e.asset_id, e.alarm_name))
        for i, ev in enumerate(events, start=1):
            ev.alarm_id = f"ALM-{i:06d}"
        self.events = events
        self._by_id = {e.alarm_id: e for e in events}

    def _make_event(
        self, rng: random.Random, start: datetime, asset: Asset, adef: AlarmDef, chatter: bool, active: bool
    ) -> AlarmEvent:
        if chatter:
            duration_min = rng.uniform(0.2, 0.9)
        else:
            base = {"critical": 25, "high": 45, "medium": 70, "low": 90}[adef.severity]
            duration_min = max(1.0, rng.lognormvariate(math.log(base), 0.8))
            # a small share of standing ("stale") alarms
            if rng.random() < 0.04:
                duration_min = rng.uniform(200, 900)
        ack_base = {"critical": 60, "high": 150, "medium": 400, "low": 900}[adef.severity]
        ack_delay = max(10.0, rng.lognormvariate(math.log(ack_base), 0.7))
        end = None if active else start + timedelta(minutes=duration_min)
        ack: datetime | None = start + timedelta(seconds=ack_delay)
        if end is not None and ack is not None and ack > end and chatter:
            ack = None
        pv: float | None
        if adef.uom == "state":
            pv = None
        elif adef.direction == "low":
            pv = round(adef.limit * rng.uniform(0.75, 0.98), 2)
        else:
            pv = round(adef.limit * rng.uniform(1.01, 1.15), 2)
        return AlarmEvent(
            alarm_id="",
            asset_id=asset.asset_id,
            alarm_name=adef.name,
            tag=f"{asset.tag_prefix}-{adef.code}",
            alarm_type=adef.alarm_type,
            severity=adef.severity,
            start_time=start,
            end_time=end,
            ack_time=ack,
            process_value=pv,
            limit=None if adef.uom == "state" else adef.limit,
            uom=adef.uom,
            status="active" if active else "cleared",
            chatter=chatter,
        )

    # ------------------------------------------------------------------ queries
    def get(self, alarm_id: str) -> AlarmEvent | None:
        return self._by_id.get(alarm_id)

    def filter(
        self,
        *,
        asset_ids: Sequence[str] | None = None,
        site: str | None = None,
        unit: str | None = None,
        status: str | None = None,
        severities: Sequence[str] | None = None,
        alarm_types: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[AlarmEvent]:
        out: list[AlarmEvent] = []
        sev = {s.lower() for s in severities} if severities else None
        types = {t.lower() for t in alarm_types} if alarm_types else None
        ids = set(asset_ids) if asset_ids else None
        site_l = site.lower() if site else None
        unit_l = unit.lower() if unit else None
        for ev in self.events:
            a = ev.asset
            if ids is not None and ev.asset_id not in ids:
                continue
            if site_l and a.site.lower() != site_l:
                continue
            if unit_l and a.unit.lower() != unit_l:
                continue
            if status and ev.status != status.lower():
                continue
            if sev is not None and ev.severity not in sev:
                continue
            if types is not None and ev.alarm_type not in types:
                continue
            if start and ev.start_time < start:
                continue
            if end and ev.start_time >= end:
                continue
            out.append(ev)
        return out
