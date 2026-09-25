"""Alarm Management MCP server.

Exposes Alarm Management API capabilities as typed, read-only MCP tools. The server owns
source-system authentication, retries/timeouts (via the connector), error mapping and
trace propagation; clients only ever see MCP tool contracts.
"""

# NOTE: no `from __future__ import annotations` here - FastMCP introspects real annotation objects.

import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, TypeVar

try:
    from mcp.server.fastmcp import Context, FastMCP
except ModuleNotFoundError as exc:  # mcp 2.x renamed FastMCP
    raise ImportError(
        'This project targets the MCP Python SDK v1 (FastMCP API). Install it with: pip install "mcp>=1.27,<2"'
    ) from exc
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from connectors import AlarmApiClient, AlarmApiError, AlarmApiSettings, ApiResult, TraceContext

from . import models as m
from .config import ServerSettings

log = logging.getLogger("alarm_mcp")

SERVER_NAME = "alarm-management"
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$"
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

AssetId = Annotated[str, Field(pattern=ID_PATTERN, description="Asset identifier, e.g. AST-BFP-101")]
AlarmId = Annotated[str, Field(pattern=ID_PATTERN, description="Alarm occurrence identifier, e.g. ALM-000123")]
OptText = Annotated[str | None, Field(default=None, max_length=100)]
StartTime = Annotated[
    datetime | None,
    Field(default=None, description="ISO-8601 start (inclusive). Defaults to end_time - lookback_days."),
]
EndTime = Annotated[datetime | None, Field(default=None, description="ISO-8601 end (exclusive). Defaults to now.")]
Lookback = Annotated[int, Field(default=30, ge=1, le=365, description="Used when start_time is omitted.")]
AssetIds = Annotated[
    list[Annotated[str, Field(pattern=ID_PATTERN)]] | None,
    Field(default=None, max_length=20, description="Asset identifiers to scope the query"),
]

T = TypeVar("T")


class ToolRuntime:
    """Holds the lazily-created API client (created inside the serving event loop)."""

    def __init__(self, settings: ServerSettings, client: AlarmApiClient | None = None) -> None:
        self.settings = settings
        self._client = client

    @property
    def client(self) -> AlarmApiClient:
        if self._client is None:
            s = self.settings
            self._client = AlarmApiClient(
                AlarmApiSettings(
                    base_url=s.alarm_api_base_url,
                    token=s.alarm_api_token.get_secret_value(),
                    timeout_seconds=s.alarm_api_timeout_seconds,
                    max_retries=s.alarm_api_max_retries,
                    backoff_base_seconds=s.alarm_api_backoff_seconds,
                )
            )
        return self._client


# ---------------------------------------------------------------------------- helpers
def trace_from_context(ctx: Context | None) -> TraceContext:
    """Build the trace context from MCP ``_meta`` (preferred) or HTTP headers."""
    meta: dict[str, Any] = {}
    if ctx is not None:
        try:
            rc = ctx.request_context
        except (ValueError, LookupError):
            rc = None
        if rc is not None and rc.meta is not None:
            meta = dict(rc.meta.model_extra or {})
        request = getattr(rc, "request", None) if rc is not None else None
        headers = getattr(request, "headers", None)
        if headers is not None:
            meta.setdefault("trace_id", headers.get("x-trace-id"))
            meta.setdefault("client_id", headers.get("x-client-id"))
    trace_id = str(meta.get("trace_id") or "") or None
    tc = TraceContext(
        client_id=_clean(meta.get("client_id")),
        metadata_tag=_clean(meta.get("metadata_tag")),
        conversation_id=_clean(meta.get("conversation_id")),
    )
    if trace_id:
        tc.trace_id = _clean(trace_id) or tc.trace_id
    return tc


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = "".join(ch for ch in str(v) if ch.isalnum() or ch in "-_.:")
    return s[:128] or None


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_window(start: datetime | None, end: datetime | None, lookback_days: int) -> tuple[str, str]:
    end_dt = end or datetime.now(UTC)
    start_dt = start or (end_dt - timedelta(days=lookback_days))
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=UTC)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    if end_dt <= start_dt:
        raise tool_error("INVALID_ARGUMENT", "end_time must be after start_time")
    if end_dt - start_dt > timedelta(days=366):
        raise tool_error("INVALID_ARGUMENT", "time window must not exceed 366 days")
    return _iso(start_dt), _iso(end_dt)


def require_scope(asset_ids: list[str] | None, site: str | None, unit: str | None) -> None:
    if not asset_ids and not site and not unit:
        raise tool_error("INVALID_ARGUMENT", "Provide at least one of asset_ids / asset_id, site or unit")


def tool_error(code: str, message: str, **extra: Any) -> ToolError:
    payload = {"error": {"code": code, "message": message, **extra}}
    return ToolError(json.dumps(payload))


def make_trace(tool: str, trace: TraceContext, started: float, results: list[ApiResult]) -> m.ToolTrace:
    calls = [a.to_dict() for r in results for a in r.attempts]
    return m.ToolTrace(
        trace_id=trace.trace_id,
        tool=tool,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        retries=sum(r.retries for r in results),
        api_calls=[m.ApiCall(**c) for c in calls],
    )


def mapped(tool_name: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator: map connector errors to structured MCP errors and emit a structured log line."""

    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            ctx = kwargs.get("ctx")
            trace = trace_from_context(ctx)
            kwargs["trace"] = trace
            started = time.perf_counter()
            outcome, status = "ok", None
            try:
                result = await fn(*args, **kwargs)
                calls = getattr(getattr(result, "trace", None), "api_calls", None) or []
                status = calls[-1].status if calls else None
                return result
            except AlarmApiError as exc:
                outcome, status = "error", exc.status
                raise tool_error(
                    exc.code,
                    exc.message,
                    http_status=exc.status,
                    upstream_code=exc.upstream_code,
                    retryable=exc.retryable,
                    attempts=exc.attempts,
                    trace_id=trace.trace_id,
                    details=exc.details,
                ) from exc
            except ToolError:
                outcome = "invalid_argument"
                raise
            finally:
                log.info(
                    json.dumps(
                        {
                            "event": "mcp_tool_call",
                            "server": SERVER_NAME,
                            "tool": tool_name,
                            "outcome": outcome,
                            "api_status": status,
                            "trace_id": trace.trace_id,
                            "conversation_id": trace.conversation_id,
                            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        }
                    )
                )

        # hide the injected ``trace`` kwarg from the MCP signature
        import inspect

        sig = inspect.signature(fn)
        wrapper.__signature__ = sig.replace(  # type: ignore[attr-defined]
            parameters=[p for p in sig.parameters.values() if p.name != "trace"]
        )
        wrapper.__annotations__ = {k: v for k, v in fn.__annotations__.items() if k != "trace"}
        return wrapper

    return deco


# ---------------------------------------------------------------------------- server factory
def create_server(settings: ServerSettings | None = None, client: AlarmApiClient | None = None) -> FastMCP:
    settings = settings or ServerSettings()
    rt = ToolRuntime(settings, client)
    allowed_hosts = [h.strip() for h in settings.allowed_hosts.split(",") if h.strip()]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(allowed_hosts), allowed_hosts=allowed_hosts, allowed_origins=[]
    )
    mcp = FastMCP(
        SERVER_NAME,
        instructions=(
            "Read-only tools over the Alarm Management API. Typical chain: search_assets -> "
            "get_asset_metadata -> get_alarms -> summarize_alarms / correlate_alarms -> "
            "score_alarm_priority -> get_operator_recommendations. All times are ISO-8601 UTC."
        ),
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.path,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    enabled = settings.enabled_tool_set()

    def register(name: str, title: str, description: str) -> Callable[[Any], Any]:
        def deco(fn: Any) -> Any:
            if enabled is None or name in enabled:
                mcp.add_tool(
                    mapped(name)(fn),
                    name=name,
                    title=title,
                    description=description,
                    annotations=READ_ONLY,
                    structured_output=True,
                )
            return fn

        return deco

    # ------------------------------------------------------------------ tools
    @register(
        "search_assets",
        "Search assets",
        "Resolve a free-text asset name, tag or equipment type (e.g. 'Boiler Feed Pump 101', 'compressor') "
        "to asset identifiers. Always call this before tools that need asset_id.",
    )
    async def search_assets(
        query: Annotated[str, Field(min_length=1, max_length=200, description="Asset name, tag or type")],
        site: OptText = None,
        unit: OptText = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.AssetSearchResult:
        t0 = time.perf_counter()
        r = await rt.client.search_assets(trace, query=query, limit=limit, site=site, unit=unit)
        return m.AssetSearchResult(
            query=query,
            total=r.data.get("total", 0),
            results=r.data.get("results", []),
            trace=make_trace("search_assets", trace, t0, [r]),
        )

    @register(
        "get_asset_metadata",
        "Get asset metadata",
        "Return asset master data: type, criticality, operating limits, configured alarms, standby unit and "
        "related assets (upstream/downstream/driver/power supply) to inspect during an investigation.",
    )
    async def get_asset_metadata(
        asset_id: AssetId, ctx: Context | None = None, *, trace: TraceContext
    ) -> m.AssetMetadataResult:
        t0 = time.perf_counter()
        r = await rt.client.asset_metadata(trace, asset_id)
        return m.AssetMetadataResult(asset=r.data, trace=make_trace("get_asset_metadata", trace, t0, [r]))

    @register(
        "get_alarms",
        "Get alarms",
        "Retrieve alarm occurrences filtered by asset/site/unit, status (active|cleared|shelved), severity "
        "and time window. Supports pagination; set fetch_all_pages=true to follow pages up to max_pages.",
    )
    async def get_alarms(
        asset_id: Annotated[str | None, Field(default=None, pattern=ID_PATTERN)] = None,
        site: OptText = None,
        unit: OptText = None,
        status: m.AlarmStatus | None = None,
        severity: Annotated[list[m.Severity] | None, Field(default=None, max_length=4)] = None,
        alarm_name: OptText = None,
        start_time: StartTime = None,
        end_time: EndTime = None,
        page: Annotated[int, Field(ge=1, le=10000)] = 1,
        page_size: Annotated[int, Field(ge=1, le=200)] = 50,
        sort_by: Literal["start_time", "severity", "alarm_name", "asset_name", "duration_minutes"] = "start_time",
        sort_order: Literal["asc", "desc"] = "desc",
        fetch_all_pages: bool = False,
        max_pages: Annotated[int, Field(ge=1, le=10)] = 3,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.AlarmListResult:
        require_scope([asset_id] if asset_id else None, site, unit)
        t0 = time.perf_counter()
        params: dict[str, Any] = {
            "asset_id": asset_id,
            "site": site,
            "unit": unit,
            "status": status,
            "severity": ",".join(severity) if severity else None,
            "alarm_name": alarm_name,
            "start_time": _iso(start_time) if start_time else None,
            "end_time": _iso(end_time) if end_time else None,
            "page": page,
            "page_size": page_size,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if start_time and end_time and end_time <= start_time:
            raise tool_error("INVALID_ARGUMENT", "end_time must be after start_time")
        if fetch_all_pages:
            r = await rt.client.list_alarms_all_pages(trace, params, max_pages)
        else:
            r = await rt.client.list_alarms(trace, params)
        return m.AlarmListResult(
            alarms=r.data.get("data", []),
            pagination=r.data["pagination"],
            trace=make_trace("get_alarms", trace, t0, [r]),
        )

    @register("get_alarm_details", "Get alarm details", "Return one alarm occurrence by alarm_id.")
    async def get_alarm_details(
        alarm_id: AlarmId, ctx: Context | None = None, *, trace: TraceContext
    ) -> m.AlarmDetailResult:
        t0 = time.perf_counter()
        r = await rt.client.get_alarm(trace, alarm_id)
        return m.AlarmDetailResult(alarm=r.data, trace=make_trace("get_alarm_details", trace, t0, [r]))

    @register(
        "summarize_alarms",
        "Summarize alarms",
        "Aggregate alarms for assets/site/unit over a window, grouped by fields such as alarm_name or "
        "severity, with KPIs: alarm_count, recurring_rate (repeat within 24h), avg_ack_delay (s), "
        "critical_count, suppression_candidate_rate.",
    )
    async def summarize_alarms(
        asset_ids: AssetIds = None,
        site: OptText = None,
        unit: OptText = None,
        start_time: StartTime = None,
        end_time: EndTime = None,
        lookback_days: Lookback = 30,
        severity: Annotated[list[m.Severity] | None, Field(default=None, max_length=4)] = None,
        alarm_types: Annotated[list[m.AlarmType] | None, Field(default=None, max_length=4)] = None,
        group_by: Annotated[list[m.GroupBy], Field(min_length=1, max_length=4)] = ["alarm_name"],  # noqa: B006
        kpis: Annotated[list[m.Kpi], Field(min_length=1, max_length=7)] = [  # noqa: B006
            "alarm_count",
            "recurring_rate",
            "avg_ack_delay",
        ],
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.AlarmSummaryResult:
        require_scope(asset_ids, site, unit)
        s, e = resolve_window(start_time, end_time, lookback_days)
        t0 = time.perf_counter()
        body = {
            "asset_ids": asset_ids,
            "site": site,
            "unit": unit,
            "time_range": {"start_time": s, "end_time": e},
            "severity": severity,
            "alarm_types": alarm_types,
            "group_by": group_by,
            "kpis": kpis,
        }
        r = await rt.client.alarm_summary(trace, {k: v for k, v in body.items() if v is not None})
        return m.AlarmSummaryResult(
            groups=r.data["groups"],
            totals=r.data["totals"],
            group_count=r.data["group_count"],
            time_range=r.data["time_range"],
            trace=make_trace("summarize_alarms", trace, t0, [r]),
        )

    @register(
        "get_alarm_trends",
        "Get alarm trends",
        "Time-bucketed alarm metrics (hourly|daily|weekly) with an overall trend direction "
        "(increasing/decreasing/stable) comparing the first and second half of the window.",
    )
    async def get_alarm_trends(
        asset_ids: AssetIds = None,
        site: OptText = None,
        unit: OptText = None,
        start_time: StartTime = None,
        end_time: EndTime = None,
        lookback_days: Lookback = 30,
        bucket: Literal["hourly", "daily", "weekly"] = "daily",
        metrics: Annotated[list[m.Kpi], Field(min_length=1, max_length=4)] = ["alarm_count"],  # noqa: B006
        severity: Annotated[list[m.Severity] | None, Field(default=None, max_length=4)] = None,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.AlarmTrendResult:
        require_scope(asset_ids, site, unit)
        s, e = resolve_window(start_time, end_time, lookback_days)
        t0 = time.perf_counter()
        body = {
            "asset_ids": asset_ids,
            "site": site,
            "unit": unit,
            "time_range": {"start_time": s, "end_time": e},
            "bucket": bucket,
            "metrics": metrics,
            "severity": severity,
        }
        r = await rt.client.alarm_trends(trace, {k: v for k, v in body.items() if v is not None})
        return m.AlarmTrendResult(
            bucket=r.data["bucket"],
            buckets=r.data["buckets"],
            trend=r.data["trend"],
            time_range=r.data["time_range"],
            trace=make_trace("get_alarm_trends", trace, t0, [r]),
        )

    @register(
        "correlate_alarms",
        "Correlate alarms",
        "Find alarms that repeatedly occur together (A followed by B within lag_window_minutes) across the "
        "given assets and, by default, their related assets. Use to identify likely contributing causes.",
    )
    async def correlate_alarms(
        asset_ids: Annotated[list[Annotated[str, Field(pattern=ID_PATTERN)]], Field(min_length=1, max_length=20)],
        start_time: StartTime = None,
        end_time: EndTime = None,
        lookback_days: Lookback = 90,
        lag_window_minutes: Annotated[int, Field(ge=1, le=240)] = 15,
        severity_threshold: m.Severity = "medium",
        min_support: Annotated[int, Field(ge=1, le=1000)] = 2,
        include_related_assets: bool = True,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.CorrelationResult:
        s, e = resolve_window(start_time, end_time, lookback_days)
        t0 = time.perf_counter()
        r = await rt.client.alarm_correlation(
            trace,
            {
                "asset_ids": asset_ids,
                "time_range": {"start_time": s, "end_time": e},
                "correlation_method": "cooccurrence",
                "lag_window_minutes": lag_window_minutes,
                "severity_threshold": severity_threshold,
                "min_support": min_support,
                "include_related_assets": include_related_assets,
            },
        )
        d = r.data
        return m.CorrelationResult(
            method=d["method"],
            lag_window_minutes=d["lag_window_minutes"],
            events_considered=d["events_considered"],
            assets_considered=d["assets_considered"],
            pairs=d["pairs"],
            time_range=d["time_range"],
            trace=make_trace("correlate_alarms", trace, t0, [r]),
        )

    @register(
        "score_alarm_priority",
        "Score alarm priority",
        "Compute a 0-100 priority score and P1-P4 band for an alarm occurrence, with contributing factors "
        "(severity, asset criticality, safety impact, recurrence, unacknowledged state).",
    )
    async def score_alarm_priority(
        alarm_id: AlarmId, ctx: Context | None = None, *, trace: TraceContext
    ) -> m.PriorityResult:
        t0 = time.perf_counter()
        r = await rt.client.priority_score(trace, alarm_id)
        return m.PriorityResult(**r.data, trace=make_trace("score_alarm_priority", trace, t0, [r]))

    @register(
        "get_operator_recommendations",
        "Get operator recommendations",
        "Return ranked operator actions for an alarm occurrence from the recommendation engine, optionally "
        "with related alarms, asset context and 90-day historical pattern (common precursors). "
        "Recommendations must be cross-checked against operating procedures.",
    )
    async def get_operator_recommendations(
        alarm_id: AlarmId,
        include_related: bool = True,
        include_asset_context: bool = True,
        include_historical_pattern: bool = True,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.RecommendationResult:
        t0 = time.perf_counter()
        r = await rt.client.operator_recommendations(
            trace,
            {
                "alarm_id": alarm_id,
                "include_related": include_related,
                "include_asset_context": include_asset_context,
                "include_historical_pattern": include_historical_pattern,
            },
        )
        return m.RecommendationResult(**r.data, trace=make_trace("get_operator_recommendations", trace, t0, [r]))

    @register(
        "analyze_alarm_flood",
        "Analyze alarm floods",
        "Detect alarm-flood windows (>= threshold_count alarms within rolling_window_minutes) for a site/unit.",
    )
    async def analyze_alarm_flood(
        site: OptText = None,
        unit: OptText = None,
        start_time: StartTime = None,
        end_time: EndTime = None,
        lookback_days: Lookback = 30,
        threshold_count: Annotated[int, Field(ge=2, le=1000)] = 10,
        rolling_window_minutes: Annotated[int, Field(ge=1, le=1440)] = 10,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.FloodResult:
        require_scope(None, site, unit)
        s, e = resolve_window(start_time, end_time, lookback_days)
        t0 = time.perf_counter()
        body = {
            "site": site,
            "unit": unit,
            "time_range": {"start_time": s, "end_time": e},
            "threshold_count": threshold_count,
            "rolling_window_minutes": rolling_window_minutes,
        }
        r = await rt.client.flood_analysis(trace, {k: v for k, v in body.items() if v is not None})
        return m.FloodResult(**r.data, trace=make_trace("analyze_alarm_flood", trace, t0, [r]))

    @register(
        "find_rationalization_candidates",
        "Find rationalization candidates",
        "List frequent, chattering or stale alarms that are candidates for rationalization/suppression.",
    )
    async def find_rationalization_candidates(
        asset_ids: AssetIds = None,
        site: OptText = None,
        unit: OptText = None,
        start_time: StartTime = None,
        end_time: EndTime = None,
        lookback_days: Lookback = 90,
        recurrence_threshold: Annotated[int, Field(ge=1, le=10000)] = 5,
        stale_minutes_threshold: Annotated[int, Field(ge=1, le=100000)] = 180,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.RationalizationResult:
        require_scope(asset_ids, site, unit)
        s, e = resolve_window(start_time, end_time, lookback_days)
        t0 = time.perf_counter()
        body = {
            "asset_ids": asset_ids,
            "site": site,
            "unit": unit,
            "time_range": {"start_time": s, "end_time": e},
            "recurrence_threshold": recurrence_threshold,
            "stale_minutes_threshold": stale_minutes_threshold,
        }
        r = await rt.client.rationalization_candidates(trace, {k: v for k, v in body.items() if v is not None})
        return m.RationalizationResult(**r.data, trace=make_trace("find_rationalization_candidates", trace, t0, [r]))

    @register(
        "calculate_kpi",
        "Calculate alarm KPI",
        "Compute an alarm-management KPI (alarm_flood_index, critical_alarm_density, "
        "operator_response_efficiency, nuisance_alarm_score). Chains the API's generate and execute steps.",
    )
    async def calculate_kpi(
        calculation_type: m.CalculationType,
        site: OptText = None,
        unit: OptText = None,
        asset_ids: AssetIds = None,
        start_time: StartTime = None,
        end_time: EndTime = None,
        lookback_days: Lookback = 30,
        ctx: Context | None = None,
        *,
        trace: TraceContext,
    ) -> m.KpiCalculationResult:
        require_scope(asset_ids, site, unit)
        s, e = resolve_window(start_time, end_time, lookback_days)
        filters = {
            k: v
            for k, v in {"site": site, "unit": unit, "asset_ids": asset_ids, "start_time": s, "end_time": e}.items()
            if v is not None
        }
        t0 = time.perf_counter()
        gen = await rt.client.generate_calculation(trace, {"calculation_type": calculation_type, "filters": filters})
        exe = await rt.client.execute_calculation(
            trace, {"calculation_id": gen.data["calculation_id"], "filters": filters}
        )
        return m.KpiCalculationResult(
            calculation_id=gen.data["calculation_id"],
            calculation_type=calculation_type,
            description=gen.data.get("description", ""),
            filters=exe.data["filters"],
            result=exe.data["result"],
            trace=make_trace("calculate_kpi", trace, t0, [gen, exe]),
        )

    @register("list_kpi_definitions", "List KPI definitions", "Return KPI and calculation-type definitions.")
    async def list_kpi_definitions(ctx: Context | None = None, *, trace: TraceContext) -> m.KpiDefinitionsResult:
        t0 = time.perf_counter()
        r = await rt.client.kpi_definitions(trace)
        return m.KpiDefinitionsResult(**r.data, trace=make_trace("list_kpi_definitions", trace, t0, [r]))

    mcp.runtime = rt  # type: ignore[attr-defined]
    return mcp
