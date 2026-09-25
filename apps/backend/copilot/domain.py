"""Domain and API response models for the copilot."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

IntentName = Literal[
    "investigate",
    "site_priority",
    "related_assets",
    "procedure_lookup",
    "recommendation_check",
    "alarm_kpi",
    "general_question",
]
StepStatus = Literal["pending", "ok", "error", "skipped"]


class TimeWindow(BaseModel):
    days: int = 90
    start_time: str
    end_time: str
    label: str


class Entities(BaseModel):
    asset_query: str | None = None
    asset_is_specific: bool = False
    equipment_type: str | None = None
    site: str | None = None
    unit: str | None = None
    alarm_keywords: list[str] = Field(default_factory=list)
    severities: list[str] | None = None
    status: Literal["active", "cleared"] | None = None
    lookback_days: int | None = None
    refers_to_context: bool = False


class Intent(BaseModel):
    name: IntentName
    confidence: float
    rationale: str
    entities: Entities
    source: Literal["rules", "llm"] = "rules"


class PlanStep(BaseModel):
    id: str
    kind: Literal["mcp", "rag"] = "mcp"
    tool: str
    purpose: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    optional: bool = False
    foreach: dict[str, Any] | None = None


class ToolCallRecord(BaseModel):
    step_id: str
    kind: Literal["mcp", "rag"] = "mcp"
    server: str | None = None
    tool: str
    purpose: str
    status: StepStatus
    wave: int = 0
    arguments: dict[str, Any] = Field(default_factory=dict)
    request: dict[str, Any] | None = None
    response: Any = None
    error: dict[str, Any] | None = None
    duration_ms: float = 0.0
    retries: int = 0
    api_calls: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None
    iteration: int | None = None


class Citation(BaseModel):
    id: str
    chunk_id: str
    doc_id: str
    title: str
    section: str
    doc_type: str
    revision: str | None = None
    source_path: str
    score: float
    confidence: float
    snippet: str
    trust_level: str = "controlled"


class Evidence(BaseModel):
    kind: Literal["tool", "document"]
    ref: str
    detail: str


class CauseFinding(BaseModel):
    cause: str
    confidence: Literal["high", "medium", "low"]
    evidence: list[Evidence] = Field(default_factory=list)


class RecommendationAssessment(BaseModel):
    action: str
    source: Literal["api", "document"]
    urgency: str | None = None
    status: Literal["consistent", "conflict", "not_covered", "document_guidance"]
    explanation: str
    citations: list[str] = Field(default_factory=list)


class AlarmRow(BaseModel):
    alarm_id: str
    asset_name: str
    alarm_name: str
    severity: str
    status: str
    start_time: str
    acknowledged: bool = False
    priority_score: float | None = None
    priority_band: str | None = None


class AlarmSummaryPanel(BaseModel):
    asset: dict[str, Any] | None = None
    scope_label: str
    window: TimeWindow | None = None
    total_alarms: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    active_alarms: list[AlarmRow] = Field(default_factory=list)
    top_alarm_groups: list[dict[str, Any]] = Field(default_factory=list)
    trend: dict[str, Any] | None = None
    primary_alarm: AlarmRow | None = None
    priority_rationale: str | None = None
    related_assets: list[dict[str, Any]] = Field(default_factory=list)
    kpis: dict[str, Any] = Field(default_factory=dict)


class RetrievalInfo(BaseModel):
    query: str
    filters: dict[str, Any]
    low_confidence: bool
    top_confidence: float
    fallback_used: bool
    results: list[dict[str, Any]] = Field(default_factory=list)
    quarantined: list[dict[str, Any]] = Field(default_factory=list)


class Answer(BaseModel):
    markdown: str
    confidence: Literal["high", "medium", "low"]
    grounded: bool
    generator: str
    safety_flags: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class InvestigationResponse(BaseModel):
    conversation_id: str
    request_id: str
    trace_id: str
    intent: Intent
    plan: list[PlanStep]
    answer: Answer
    alarm_summary: AlarmSummaryPanel | None = None
    likely_causes: list[CauseFinding] = Field(default_factory=list)
    recommendations: list[RecommendationAssessment] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    retrieval: RetrievalInfo | None = None
    tool_trace: list[ToolCallRecord] = Field(default_factory=list)
    discovered_tools: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
