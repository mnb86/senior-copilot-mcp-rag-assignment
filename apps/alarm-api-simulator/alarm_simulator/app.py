"""Starlette application implementing the Alarm Management API contract (see postman/)."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import analytics as an
from .schemas import (
    AlarmRef,
    CalcExecuteRequest,
    CalcGenerateRequest,
    CorrelationRequest,
    FloodRequest,
    RationalizationRequest,
    RecommendationRequest,
    SummaryRequest,
    TrendsRequest,
)
from .store import AlarmStore, iso, parse_time

log = logging.getLogger("alarm_simulator")
TRACE_HEADERS = ("trace_id", "x-client-id", "x-metadata-tag")
SORTABLE = {"start_time", "severity", "alarm_name", "asset_name", "duration_minutes"}


@dataclass
class SimSettings:
    token: str = "demo-token"  # noqa: S105 - documented demo default, overridden by ALARM_API_TOKEN
    anchor: datetime = field(
        default_factory=lambda: datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    seed: int = 42
    latency_ms: int = 0
    faults: dict[str, tuple[int, int]] = field(default_factory=dict)  # "POST /path" -> (status, first_n)
    allow_fault_header: bool = True
    fault_clients: frozenset[str] = frozenset()  # limit SIM_FAULTS to these x-client-id values (empty = all)

    @classmethod
    def from_env(cls) -> SimSettings:
        s = cls()
        s.token = os.getenv("ALARM_API_TOKEN", s.token)
        if os.getenv("SIM_ANCHOR_TIME"):
            s.anchor = parse_time(os.environ["SIM_ANCHOR_TIME"])
        s.seed = int(os.getenv("SIM_SEED", s.seed))
        s.latency_ms = int(os.getenv("SIM_LATENCY_MS", "0"))
        s.allow_fault_header = os.getenv("SIM_ALLOW_FAULT_HEADER", "true").lower() == "true"
        s.faults = parse_faults(os.getenv("SIM_FAULTS", ""))
        s.fault_clients = frozenset(c.strip() for c in os.getenv("SIM_FAULT_CLIENTS", "").split(",") if c.strip())
        return s


def parse_faults(spec: str) -> dict[str, tuple[int, int]]:
    """Parse ``"POST /alarms/correlation=503x1;GET /alarms=500x2"``.

    Each entry fails the first N calls *per trace id* with the given status, so a retrying
    client observes a transient fault that then recovers.
    """
    out: dict[str, tuple[int, int]] = {}
    for part in filter(None, (p.strip() for p in spec.split(";"))):
        route, _, rule = part.partition("=")
        status, _, count = rule.partition("x")
        out[route.strip()] = (int(status), int(count or "1"))
    return out


def error(status: int, code: str, message: str, request: Request, details: Any = None) -> JSONResponse:
    body = {
        "error": {"code": code, "message": message, "details": details},
        "trace_id": request.headers.get("trace_id"),
        "request_id": request.state.request_id,
    }
    return JSONResponse(body, status_code=status)


class GatewayMiddleware(BaseHTTPMiddleware):
    """Auth, trace echo, latency + fault injection and structured access logging."""

    def __init__(self, app: Any, settings: SimSettings) -> None:
        super().__init__(app)
        self.s = settings
        self.fault_counts: dict[tuple[str, str], int] = defaultdict(int)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        response = await self._handle(request, call_next)
        for h in TRACE_HEADERS:
            if request.headers.get(h):
                response.headers[h] = request.headers[h]
        response.headers["x-request-id"] = request.state.request_id
        log.info(
            json.dumps(
                {
                    "event": "http_request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "trace_id": request.headers.get("trace_id"),
                    "client_id": request.headers.get("x-client-id"),
                    "request_id": request.state.request_id,
                }
            )
        )
        return response

    async def _handle(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), self.s.token):
            return error(401, "UNAUTHORIZED", "Missing or invalid bearer token", request)
        if self.s.latency_ms:
            await asyncio.sleep(self.s.latency_ms / 1000)
        fault = request.headers.get("x-simulate-fault") if self.s.allow_fault_header else None
        if fault:
            if fault.startswith("timeout"):
                await asyncio.sleep(float(fault.partition(":")[2] or "30"))
            elif fault.isdigit():
                return error(int(fault), "SIMULATED_FAULT", f"Simulated HTTP {fault}", request)
        route_key = f"{request.method} {request.url.path}"
        client = request.headers.get("x-client-id", "")
        if route_key in self.s.faults and (not self.s.fault_clients or client in self.s.fault_clients):
            status, first_n = self.s.faults[route_key]
            trace = request.headers.get("trace_id") or "no-trace"
            self.fault_counts[(route_key, trace)] += 1
            if self.fault_counts[(route_key, trace)] <= first_n:
                return error(
                    status, "TRANSIENT_UPSTREAM_ERROR", "Analytics worker temporarily unavailable, retry later", request
                )
        return await call_next(request)


def create_app(settings: SimSettings | None = None) -> Starlette:
    s = settings or SimSettings.from_env()
    store = AlarmStore(anchor=s.anchor, seed=s.seed)
    calcs: dict[str, dict[str, Any]] = {}

    async def body(request: Request, model: type[BaseModel]) -> Any:
        try:
            raw = await request.body()
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise an.ApiError(400, "INVALID_JSON", f"Request body is not valid JSON: {exc.msg}") from exc
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            details = [{"loc": ".".join(str(x) for x in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
            raise an.ApiError(422, "VALIDATION_ERROR", "Request validation failed", details) from exc

    def time_window(tr: Any) -> tuple[datetime, datetime]:
        try:
            start, end = parse_time(tr.start_time), parse_time(tr.end_time)
        except ValueError as exc:
            raise an.ApiError(422, "VALIDATION_ERROR", "start_time/end_time must be ISO-8601") from exc
        if end <= start:
            raise an.ApiError(422, "VALIDATION_ERROR", "end_time must be after start_time")
        return start, end

    def scoped_events(req: Any, severities: Sequence[str] | None = None, types: Sequence[str] | None = None):
        start, end = time_window(req.time_range)
        return (
            start,
            end,
            store.filter(
                asset_ids=req.asset_ids,
                site=req.site,
                unit=req.unit,
                severities=severities,
                alarm_types=types,
                start=start,
                end=end,
            ),
        )

    def qint(request: Request, name: str, default: int, lo: int, hi: int) -> int:
        raw = request.query_params.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except ValueError as exc:
            raise an.ApiError(422, "VALIDATION_ERROR", f"'{name}' must be an integer") from exc
        if not lo <= v <= hi:
            raise an.ApiError(422, "VALIDATION_ERROR", f"'{name}' must be between {lo} and {hi}")
        return v

    # ------------------------------------------------------------------ handlers
    async def health(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "alarm-api-simulator",
                "version": "1.0.0",
                "alarm_events": len(store.events),
                "data_window": {"start_time": iso(store.window_start), "end_time": iso(store.anchor)},
            }
        )

    async def search_assets(request: Request) -> JSONResponse:
        q = request.query_params.get("query", "")
        if len(q) > 200:
            raise an.ApiError(422, "VALIDATION_ERROR", "query must be at most 200 characters")
        limit = qint(request, "limit", 10, 1, 100)
        return JSONResponse(
            an.search_assets(q, request.query_params.get("site"), request.query_params.get("unit"), limit)
        )

    async def metadata(request: Request) -> JSONResponse:
        return JSONResponse(an.asset_metadata(request.path_params["asset_id"]))

    async def list_alarms(request: Request) -> JSONResponse:
        qp = request.query_params
        page = qint(request, "page", 1, 1, 100000)
        page_size = qint(request, "page_size", 50, 1, 500)
        sort_by = qp.get("sort_by", "start_time")
        sort_order = qp.get("sort_order", "desc")
        if sort_by not in SORTABLE:
            raise an.ApiError(422, "VALIDATION_ERROR", f"sort_by must be one of {sorted(SORTABLE)}")
        if sort_order not in ("asc", "desc"):
            raise an.ApiError(422, "VALIDATION_ERROR", "sort_order must be asc or desc")
        status = qp.get("status")
        if status and status not in ("active", "cleared", "shelved"):
            raise an.ApiError(422, "VALIDATION_ERROR", "status must be active, cleared or shelved")
        severities = [s for s in qp.get("severity", "").split(",") if s] or None
        if severities and any(s not in an.SEVERITY_ORDER for s in severities):
            raise an.ApiError(422, "VALIDATION_ERROR", "severity must be low, medium, high or critical")
        try:
            start = parse_time(qp["start_time"]) if qp.get("start_time") else None
            end = parse_time(qp["end_time"]) if qp.get("end_time") else None
        except ValueError as exc:
            raise an.ApiError(422, "VALIDATION_ERROR", "start_time/end_time must be ISO-8601") from exc
        asset_ids = [a for a in qp.get("asset_id", "").split(",") if a] or None
        events = store.filter(
            asset_ids=asset_ids,
            site=qp.get("site"),
            unit=qp.get("unit"),
            status=status,
            severities=severities,
            start=start,
            end=end,
        )
        name_filter = qp.get("alarm_name")
        if name_filter:
            events = [e for e in events if name_filter.lower() in e.alarm_name.lower()]
        rows = [e.to_dict() for e in events]
        sev_rank = an.SEVERITY_ORDER
        keyfn = (
            (lambda r: sev_rank[r["severity"]])
            if sort_by == "severity"
            else (lambda r: (r[sort_by] is None, r[sort_by] or 0))
        )
        rows.sort(key=keyfn, reverse=sort_order == "desc")
        total = len(rows)
        total_pages = max(1, -(-total // page_size))
        data = rows[(page - 1) * page_size : page * page_size]
        return JSONResponse(
            {
                "data": data,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                },
            }
        )

    async def get_alarm(request: Request) -> JSONResponse:
        ev = store.get(request.path_params["alarm_id"])
        if not ev:
            raise an.ApiError(404, "ALARM_NOT_FOUND", f"Alarm '{request.path_params['alarm_id']}' was not found")
        return JSONResponse(ev.to_dict())

    async def summary(request: Request) -> JSONResponse:
        req: SummaryRequest = await body(request, SummaryRequest)
        start, end, events = scoped_events(req, req.severity, req.alarm_types)
        out = an.summarize(events, req.group_by, req.kpis)
        out["time_range"] = {"start_time": iso(start), "end_time": iso(end)}
        out["filters"] = req.model_dump(exclude={"time_range", "group_by", "kpis"}, exclude_none=True)
        return JSONResponse(out)

    async def trends(request: Request) -> JSONResponse:
        req: TrendsRequest = await body(request, TrendsRequest)
        start, end, events = scoped_events(req, req.severity)
        out = an.trends(events, start, end, req.bucket, req.metrics)
        out["time_range"] = {"start_time": iso(start), "end_time": iso(end)}
        return JSONResponse(out)

    async def correlation(request: Request) -> JSONResponse:
        req: CorrelationRequest = await body(request, CorrelationRequest)
        start, end = time_window(req.time_range)
        asset_ids = list(req.asset_ids or [])
        if asset_ids and req.include_related_assets:
            for aid in list(asset_ids):
                a = an.ASSET_INDEX.get(aid)
                if a:
                    asset_ids.extend(rid for rid, _ in a.related if rid not in asset_ids)
        events = store.filter(
            asset_ids=asset_ids or None,
            site=req.site,
            unit=req.unit,
            severities=an.severity_at_least(req.severity_threshold),
            start=start,
            end=end,
        )
        pairs = an.correlate(events, req.lag_window_minutes, req.min_support)
        return JSONResponse(
            {
                "method": req.correlation_method,
                "lag_window_minutes": req.lag_window_minutes,
                "assets_considered": sorted(set(asset_ids)) if asset_ids else None,
                "events_considered": len(events),
                "pairs": pairs,
                "time_range": {"start_time": iso(start), "end_time": iso(end)},
            }
        )

    async def flood(request: Request) -> JSONResponse:
        req: FloodRequest = await body(request, FloodRequest)
        start, end, events = scoped_events(req)
        return JSONResponse(an.flood_analysis(events, start, end, req.threshold_count, req.rolling_window_minutes))

    async def rationalization(request: Request) -> JSONResponse:
        req: RationalizationRequest = await body(request, RationalizationRequest)
        _, _, events = scoped_events(req)
        return JSONResponse(an.rationalization(events, req.recurrence_threshold, req.stale_minutes_threshold))

    def _alarm(alarm_id: str) -> Any:
        ev = store.get(alarm_id)
        if not ev:
            raise an.ApiError(404, "ALARM_NOT_FOUND", f"Alarm '{alarm_id}' was not found")
        return ev

    async def priority(request: Request) -> JSONResponse:
        req: AlarmRef = await body(request, AlarmRef)
        return JSONResponse(an.priority_score(store, _alarm(req.alarm_id)))

    async def recommend(request: Request) -> JSONResponse:
        req: RecommendationRequest = await body(request, RecommendationRequest)
        return JSONResponse(
            an.recommendations(
                store,
                _alarm(req.alarm_id),
                req.include_related,
                req.include_asset_context,
                req.include_historical_pattern,
            )
        )

    async def calc_generate(request: Request) -> JSONResponse:
        req: CalcGenerateRequest = await body(request, CalcGenerateRequest)
        if req.calculation_type not in an.CALC_TYPES:
            raise an.ApiError(
                400,
                "UNKNOWN_CALCULATION",
                f"Unsupported calculation_type '{req.calculation_type}'",
                {"supported": sorted(an.CALC_TYPES)},
            )
        cid = an.calc_id(req.calculation_type, req.filters.model_dump(exclude_none=True))
        calcs[cid] = {"calculation_type": req.calculation_type}
        return JSONResponse(
            {
                "calculation_id": cid,
                "calculation_type": req.calculation_type,
                "description": an.CALC_TYPES[req.calculation_type],
                "language": "pseudo-python",
                "code": an.calc_code(req.calculation_type),
                "created_at": iso(datetime.now(UTC)),
            }
        )

    async def calc_execute(request: Request) -> JSONResponse:
        req: CalcExecuteRequest = await body(request, CalcExecuteRequest)
        calc = calcs.get(req.calculation_id)
        if not calc:
            raise an.ApiError(404, "CALCULATION_NOT_FOUND", f"Calculation '{req.calculation_id}' was not found")
        f = req.filters
        start, end = parse_time(f.start_time), parse_time(f.end_time)
        events = store.filter(asset_ids=f.asset_ids, site=f.site, unit=f.unit, start=start, end=end)
        result = an.run_calculation(calc["calculation_type"], events, start, end)
        return JSONResponse(
            {
                "calculation_id": req.calculation_id,
                "calculation_type": calc["calculation_type"],
                "filters": f.model_dump(exclude_none=True),
                "result": result,
                "executed_at": iso(datetime.now(UTC)),
            }
        )

    async def kpi_definitions(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "kpis": an.KPI_DEFINITIONS,
                "calculation_types": [{"calculation_type": k, "description": v} for k, v in an.CALC_TYPES.items()],
            }
        )

    def wrap(fn: Any) -> Any:
        async def handler(request: Request) -> Response:
            try:
                return await fn(request)  # type: ignore[no-any-return]
            except an.ApiError as exc:
                return error(exc.status, exc.code, exc.message, request, exc.details)
            except Exception:  # pragma: no cover - defensive
                log.exception("unhandled error")
                return error(500, "INTERNAL_ERROR", "Unexpected simulator error", request)

        return handler

    routes = [
        Route("/health", wrap(health), methods=["GET"]),
        Route("/assets/search", wrap(search_assets), methods=["GET"]),
        Route("/assets/{asset_id}/metadata", wrap(metadata), methods=["GET"]),
        Route("/alarms", wrap(list_alarms), methods=["GET"]),
        Route("/alarms/summary", wrap(summary), methods=["POST"]),
        Route("/alarms/trends", wrap(trends), methods=["POST"]),
        Route("/alarms/correlation", wrap(correlation), methods=["POST"]),
        Route("/alarms/flood-analysis", wrap(flood), methods=["POST"]),
        Route("/alarms/rationalization-candidates", wrap(rationalization), methods=["POST"]),
        Route("/alarms/priority-score", wrap(priority), methods=["POST"]),
        Route("/alarms/{alarm_id}", wrap(get_alarm), methods=["GET"]),
        Route("/recommendations/operator-actions", wrap(recommend), methods=["POST"]),
        Route("/calculation-code/generate", wrap(calc_generate), methods=["POST"]),
        Route("/calculation-code/execute", wrap(calc_execute), methods=["POST"]),
        Route("/analytics/kpi-definitions", wrap(kpi_definitions), methods=["GET"]),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(GatewayMiddleware, settings=s)])
    app.state.store = store
    app.state.settings = s
    return app


__all__ = ["SimSettings", "create_app", "parse_faults"]
