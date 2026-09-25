"""Request schemas for the simulator (mirrors the Postman collection bodies)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["low", "medium", "high", "critical"]


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str
    end_time: str


class _Scoped(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] | None = None
    site: str | None = None
    unit: str | None = None
    time_range: TimeRange


class SummaryRequest(_Scoped):
    severity: list[Severity] | None = None
    alarm_types: list[Literal["process", "safety", "device", "system"]] | None = None
    group_by: list[str] = Field(default_factory=lambda: ["alarm_name"], max_length=4)
    kpis: list[str] = Field(default_factory=lambda: ["alarm_count"], min_length=1)


class TrendsRequest(_Scoped):
    severity: list[Severity] | None = None
    bucket: Literal["hourly", "daily", "weekly"] = "daily"
    metrics: list[str] = Field(default_factory=lambda: ["alarm_count"], min_length=1)


class CorrelationRequest(_Scoped):
    correlation_method: Literal["cooccurrence"] = "cooccurrence"
    lag_window_minutes: int = Field(15, ge=1, le=240)
    severity_threshold: Severity = "low"
    min_support: int = Field(1, ge=1, le=1000)
    include_related_assets: bool = True

    @model_validator(mode="after")
    def _need_scope(self) -> CorrelationRequest:
        if not self.asset_ids and not self.site and not self.unit:
            raise ValueError("one of asset_ids, site or unit is required")
        return self


class FloodRequest(_Scoped):
    threshold_count: int = Field(10, ge=2, le=1000)
    rolling_window_minutes: int = Field(10, ge=1, le=1440)


class RationalizationRequest(_Scoped):
    recurrence_threshold: int = Field(5, ge=1, le=10000)
    stale_minutes_threshold: int = Field(180, ge=1, le=100000)


class AlarmRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alarm_id: str = Field(min_length=1, max_length=64)


class RecommendationRequest(AlarmRef):
    include_related: bool = False
    include_asset_context: bool = False
    include_historical_pattern: bool = False


class CalcFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site: str | None = None
    unit: str | None = None
    asset_ids: list[str] | None = None
    start_time: str
    end_time: str


class CalcGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calculation_type: str
    filters: CalcFilters


class CalcExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calculation_id: str
    filters: CalcFilters
