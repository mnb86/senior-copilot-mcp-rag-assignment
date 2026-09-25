"""Typed output contracts for the Alarm Management MCP tools.

Every model is exported to MCP clients as the tool's ``outputSchema`` and validated by
FastMCP before the result leaves the server. ``extra="allow"`` is used only on nested
upstream records so that additive API fields do not break the contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["low", "medium", "high", "critical"]
AlarmStatus = Literal["active", "cleared", "shelved"]
AlarmType = Literal["process", "safety", "device", "system"]
GroupBy = Literal["alarm_name", "asset_id", "asset_name", "severity", "alarm_type", "site", "unit", "status", "tag"]
Kpi = Literal[
    "alarm_count",
    "recurring_rate",
    "avg_ack_delay",
    "critical_count",
    "suppression_candidate_rate",
    "active_count",
    "avg_duration_minutes",
]
CalculationType = Literal[
    "alarm_flood_index", "critical_alarm_density", "operator_response_efficiency", "nuisance_alarm_score"
]


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class ApiCall(BaseModel):
    method: str
    path: str
    params: dict[str, Any] | None = None
    body: Any = None
    attempt: int
    status: int | None = None
    duration_ms: float
    outcome: str
    error: str | None = None
    request_id: str | None = None


class ToolTrace(BaseModel):
    """Execution metadata returned with every tool result (no secrets)."""

    trace_id: str
    server: str = "alarm-management"
    tool: str
    duration_ms: float
    retries: int = 0
    api_calls: list[ApiCall] = Field(default_factory=list)


# ---------------------------------------------------------------------------- assets
class AssetRef(_Open):
    asset_id: str
    asset_name: str
    asset_type: str
    site: str
    unit: str
    criticality: str | None = None
    match_score: float | None = None


class AssetSearchResult(BaseModel):
    query: str
    total: int
    results: list[AssetRef]
    trace: ToolTrace


class RelatedAsset(_Open):
    asset_id: str
    asset_name: str
    asset_type: str | None = None
    relationship: str


class AssetMetadata(_Open):
    asset_id: str
    asset_name: str
    asset_type: str
    site: str
    unit: str
    criticality: str
    manufacturer: str | None = None
    model: str | None = None
    description: str | None = None
    standby_asset_id: str | None = None
    operating_limits: dict[str, str] = Field(default_factory=dict)
    configured_alarms: list[dict[str, Any]] = Field(default_factory=list)
    related_assets: list[RelatedAsset] = Field(default_factory=list)


class AssetMetadataResult(BaseModel):
    asset: AssetMetadata
    trace: ToolTrace


# ---------------------------------------------------------------------------- alarms
class Alarm(_Open):
    alarm_id: str
    asset_id: str
    asset_name: str
    alarm_name: str
    severity: Severity
    status: AlarmStatus
    alarm_type: str
    start_time: str
    end_time: str | None = None
    acknowledged: bool = False
    ack_delay_seconds: float | None = None
    duration_minutes: float | None = None
    site: str | None = None
    unit: str | None = None
    tag: str | None = None
    message: str | None = None


class Pagination(_Open):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    pages_fetched: int | None = None
    truncated: bool | None = None


class AlarmListResult(BaseModel):
    alarms: list[Alarm]
    pagination: Pagination
    trace: ToolTrace


class AlarmDetailResult(BaseModel):
    alarm: Alarm
    trace: ToolTrace


class TimeRange(BaseModel):
    start_time: str
    end_time: str


class SummaryGroup(_Open):
    group: dict[str, Any]
    alarm_count: int | None = None
    recurring_rate: float | None = None
    avg_ack_delay: float | None = None
    critical_count: int | None = None
    suppression_candidate_rate: float | None = None
    first_occurrence: str | None = None
    last_occurrence: str | None = None


class AlarmSummaryResult(BaseModel):
    groups: list[SummaryGroup]
    totals: dict[str, Any]
    group_count: int
    time_range: TimeRange
    trace: ToolTrace


class TrendInfo(BaseModel):
    direction: Literal["increasing", "decreasing", "stable"]
    first_half_count: int
    second_half_count: int


class AlarmTrendResult(BaseModel):
    bucket: str
    buckets: list[dict[str, Any]]
    trend: TrendInfo
    time_range: TimeRange
    trace: ToolTrace


class CorrelationEndpoint(_Open):
    asset_id: str
    asset_name: str
    alarm_name: str
    occurrences: int


class CorrelationPair(_Open):
    source: CorrelationEndpoint
    target: CorrelationEndpoint
    support: int
    confidence: float
    lift: float
    avg_lag_minutes: float


class CorrelationResult(BaseModel):
    method: str
    lag_window_minutes: int
    events_considered: int
    assets_considered: list[str] | None = None
    pairs: list[CorrelationPair]
    time_range: TimeRange
    trace: ToolTrace


class PriorityResult(BaseModel):
    alarm_id: str
    asset_id: str
    alarm_name: str
    priority_score: float = Field(ge=0, le=100)
    priority_band: Literal["P1", "P2", "P3", "P4"]
    factors: dict[str, float]
    rationale: str
    trace: ToolTrace


class Recommendation(_Open):
    rank: int
    action_id: str
    action: str
    rationale: str
    urgency: Literal["immediate", "soon", "planned"]
    category: str
    confidence: float


class RecommendationResult(BaseModel):
    alarm_id: str
    asset_id: str
    alarm_name: str
    severity: Severity
    recommendations: list[Recommendation]
    related_alarms: list[dict[str, Any]] | None = None
    asset_context: dict[str, Any] | None = None
    historical_pattern: dict[str, Any] | None = None
    generated_by: str | None = None
    trace: ToolTrace


class FloodResult(BaseModel):
    flood_windows: list[dict[str, Any]]
    flood_window_count: int
    flood_percentage: float
    total_alarms: int
    threshold_count: int
    rolling_window_minutes: int
    trace: ToolTrace


class RationalizationResult(BaseModel):
    candidates: list[dict[str, Any]]
    candidate_count: int
    criteria: dict[str, Any]
    trace: ToolTrace


class KpiValue(BaseModel):
    value: float
    unit: str
    details: dict[str, Any] = Field(default_factory=dict)


class KpiCalculationResult(BaseModel):
    calculation_id: str
    calculation_type: CalculationType
    description: str
    filters: dict[str, Any]
    result: KpiValue
    trace: ToolTrace


class KpiDefinitionsResult(BaseModel):
    kpis: list[dict[str, Any]]
    calculation_types: list[dict[str, Any]]
    trace: ToolTrace
