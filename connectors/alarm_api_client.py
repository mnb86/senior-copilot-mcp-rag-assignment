"""Async HTTP connector for the Alarm Management API.

Responsibilities (kept out of the MCP layer so the connector is reusable):
  * bearer authentication (token never logged or returned),
  * trace metadata propagation (``trace_id``, ``x-client-id``, ``x-metadata-tag``, ``x-request-id``),
  * per-request timeout, bounded retries with exponential backoff + jitter for retryable failures,
  * mapping HTTP failures to typed :mod:`connectors.alarm_api_errors`,
  * pagination helpers,
  * an auditable record of every HTTP attempt (for the MCP execution trace).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .alarm_api_errors import (
    AlarmApiError,
    ConnectionFailedError,
    UnexpectedResponseError,
    UpstreamTimeoutError,
    error_for_status,
)

log = logging.getLogger("connectors.alarm_api_client")

RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
MAX_RECORDED_BODY = 4000


@dataclass(frozen=True)
class AlarmApiSettings:
    base_url: str = "http://localhost:8000"
    token: str = ""
    timeout_seconds: float = 10.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.25
    backoff_max_seconds: float = 4.0
    client_id: str = "alarm-mcp-server"

    def __repr__(self) -> str:  # never leak the token via repr/logging
        return (
            f"AlarmApiSettings(base_url={self.base_url!r}, token='***', timeout_seconds={self.timeout_seconds}, "
            f"max_retries={self.max_retries})"
        )


@dataclass
class TraceContext:
    trace_id: str = field(default_factory=lambda: f"trace-{uuid.uuid4().hex[:16]}")
    client_id: str | None = None
    metadata_tag: str | None = None
    conversation_id: str | None = None

    def headers(self, default_client_id: str) -> dict[str, str]:
        h = {"trace_id": self.trace_id, "x-client-id": self.client_id or default_client_id}
        if self.metadata_tag:
            h["x-metadata-tag"] = self.metadata_tag
        return h


@dataclass
class HttpAttempt:
    method: str
    path: str
    params: dict[str, Any] | None
    body: Any
    attempt: int
    status: int | None
    duration_ms: float
    outcome: str  # ok | retry | error
    error: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "params": self.params,
            "body": self.body,
            "attempt": self.attempt,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "outcome": self.outcome,
            "error": self.error,
            "request_id": self.request_id,
        }


@dataclass
class ApiResult:
    data: Any
    status: int
    attempts: list[HttpAttempt]

    @property
    def retries(self) -> int:
        return max(0, len(self.attempts) - 1)


Sleep = Callable[[float], Awaitable[None]]


def _truncate(value: Any) -> Any:
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return "<unserializable>"
    if len(text) <= MAX_RECORDED_BODY:
        return value
    return {"_truncated": True, "preview": text[:MAX_RECORDED_BODY]}


class AlarmApiClient:
    def __init__(
        self,
        settings: AlarmApiSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.timeout_seconds),
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "alarm-mcp-connector/1.0"},
        )
        self._sleep = sleep
        self._rng = rng or random.Random()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AlarmApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ core
    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.settings.backoff_max_seconds)
            except ValueError:
                pass
        base = self.settings.backoff_base_seconds * (2 ** (attempt - 1))
        return float(min(self.settings.backoff_max_seconds, base * (0.5 + self._rng.random())))

    async def request(
        self,
        method: str,
        path: str,
        *,
        trace: TraceContext,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> ApiResult:
        params = {k: v for k, v in (params or {}).items() if v is not None} or None
        headers = trace.headers(self.settings.client_id)
        headers["Authorization"] = f"Bearer {self.settings.token}"
        attempts: list[HttpAttempt] = []
        max_attempts = 1 + max(0, self.settings.max_retries)
        last_exc: AlarmApiError | None = None

        for attempt in range(1, max_attempts + 1):
            request_id = uuid.uuid4().hex[:16]
            headers["x-request-id"] = request_id
            started = time.perf_counter()
            try:
                resp = await self._client.request(method, path, params=params, json=json_body, headers=headers)
            except httpx.TimeoutException as exc:
                dur = round((time.perf_counter() - started) * 1000, 1)
                last_exc = UpstreamTimeoutError(
                    f"Alarm API did not respond within {self.settings.timeout_seconds}s ({method} {path})",
                    trace_id=trace.trace_id,
                )
                attempts.append(
                    HttpAttempt(
                        method,
                        path,
                        params,
                        _truncate(json_body),
                        attempt,
                        None,
                        dur,
                        "retry" if attempt < max_attempts else "error",
                        type(exc).__name__,
                        request_id,
                    )
                )
            except httpx.TransportError as exc:
                dur = round((time.perf_counter() - started) * 1000, 1)
                last_exc = ConnectionFailedError(
                    f"Could not connect to Alarm API ({type(exc).__name__})", trace_id=trace.trace_id
                )
                attempts.append(
                    HttpAttempt(
                        method,
                        path,
                        params,
                        _truncate(json_body),
                        attempt,
                        None,
                        dur,
                        "retry" if attempt < max_attempts else "error",
                        type(exc).__name__,
                        request_id,
                    )
                )
            else:
                dur = round((time.perf_counter() - started) * 1000, 1)
                if resp.status_code < 400:
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        attempts.append(
                            HttpAttempt(
                                method,
                                path,
                                params,
                                _truncate(json_body),
                                attempt,
                                resp.status_code,
                                dur,
                                "error",
                                "invalid JSON",
                                request_id,
                            )
                        )
                        raise UnexpectedResponseError(
                            "Alarm API returned a non-JSON body",
                            status=resp.status_code,
                            attempts=attempt,
                            trace_id=trace.trace_id,
                        ) from exc
                    attempts.append(
                        HttpAttempt(
                            method,
                            path,
                            params,
                            _truncate(json_body),
                            attempt,
                            resp.status_code,
                            dur,
                            "ok",
                            None,
                            request_id,
                        )
                    )
                    self._log(method, path, resp.status_code, dur, attempt, trace)
                    return ApiResult(data=data, status=resp.status_code, attempts=attempts)

                upstream = _error_payload(resp)
                cls = error_for_status(resp.status_code)
                last_exc = cls(
                    upstream.get("message") or f"Alarm API returned HTTP {resp.status_code}",
                    status=resp.status_code,
                    upstream_code=upstream.get("code"),
                    details=upstream.get("details"),
                    trace_id=trace.trace_id,
                )
                retry = resp.status_code in RETRYABLE_STATUS and attempt < max_attempts
                attempts.append(
                    HttpAttempt(
                        method,
                        path,
                        params,
                        _truncate(json_body),
                        attempt,
                        resp.status_code,
                        dur,
                        "retry" if retry else "error",
                        last_exc.upstream_code,
                        request_id,
                    )
                )
                self._log(method, path, resp.status_code, dur, attempt, trace)
                if not retry:
                    last_exc.attempts = attempt
                    last_exc.details = {"upstream": last_exc.details, "http_attempts": [a.to_dict() for a in attempts]}
                    raise last_exc
                await self._sleep(self._backoff(attempt, resp.headers.get("retry-after")))
                continue

            if attempt < max_attempts:
                await self._sleep(self._backoff(attempt, None))

        assert last_exc is not None
        last_exc.attempts = len(attempts)
        last_exc.details = {"http_attempts": [a.to_dict() for a in attempts]}
        raise last_exc

    def _log(self, method: str, path: str, status: int, dur: float, attempt: int, trace: TraceContext) -> None:
        log.info(
            json.dumps(
                {
                    "event": "alarm_api_call",
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": dur,
                    "attempt": attempt,
                    "trace_id": trace.trace_id,
                }
            )
        )

    # ------------------------------------------------------------------ endpoints
    async def health(self, trace: TraceContext) -> ApiResult:
        return await self.request("GET", "/health", trace=trace)

    async def search_assets(
        self, trace: TraceContext, query: str, limit: int = 10, site: str | None = None, unit: str | None = None
    ) -> ApiResult:
        return await self.request(
            "GET", "/assets/search", trace=trace, params={"query": query, "limit": limit, "site": site, "unit": unit}
        )

    async def asset_metadata(self, trace: TraceContext, asset_id: str) -> ApiResult:
        return await self.request("GET", f"/assets/{_seg(asset_id)}/metadata", trace=trace)

    async def list_alarms(self, trace: TraceContext, params: dict[str, Any]) -> ApiResult:
        return await self.request("GET", "/alarms", trace=trace, params=params)

    async def list_alarms_all_pages(self, trace: TraceContext, params: dict[str, Any], max_pages: int) -> ApiResult:
        """Follow ``pagination.has_next`` up to ``max_pages`` pages and merge ``data``."""
        page = int(params.get("page", 1))
        merged: list[Any] = []
        attempts: list[HttpAttempt] = []
        last: dict[str, Any] = {}
        for _ in range(max_pages):
            res = await self.list_alarms(trace, {**params, "page": page})
            attempts.extend(res.attempts)
            merged.extend(res.data.get("data", []))
            last = res.data.get("pagination", {})
            if not last.get("has_next"):
                break
            page += 1
        pagination = {
            **last,
            "pages_fetched": len({a.params.get("page") for a in attempts if a.params}),
            "truncated": bool(last.get("has_next")),
        }
        return ApiResult(data={"data": merged, "pagination": pagination}, status=200, attempts=attempts)

    async def get_alarm(self, trace: TraceContext, alarm_id: str) -> ApiResult:
        return await self.request("GET", f"/alarms/{_seg(alarm_id)}", trace=trace)

    async def alarm_summary(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/summary", trace=trace, json_body=body)

    async def alarm_trends(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/trends", trace=trace, json_body=body)

    async def alarm_correlation(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/correlation", trace=trace, json_body=body)

    async def flood_analysis(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/flood-analysis", trace=trace, json_body=body)

    async def rationalization_candidates(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/alarms/rationalization-candidates", trace=trace, json_body=body)

    async def priority_score(self, trace: TraceContext, alarm_id: str) -> ApiResult:
        return await self.request("POST", "/alarms/priority-score", trace=trace, json_body={"alarm_id": alarm_id})

    async def operator_recommendations(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/recommendations/operator-actions", trace=trace, json_body=body)

    async def generate_calculation(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/calculation-code/generate", trace=trace, json_body=body)

    async def execute_calculation(self, trace: TraceContext, body: dict[str, Any]) -> ApiResult:
        return await self.request("POST", "/calculation-code/execute", trace=trace, json_body=body)

    async def kpi_definitions(self, trace: TraceContext) -> ApiResult:
        return await self.request("GET", "/analytics/kpi-definitions", trace=trace)


def _seg(value: str) -> str:
    """Encode a path segment so identifiers cannot traverse or inject paths."""
    from urllib.parse import quote

    return quote(value, safe="")


def _error_payload(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        return {}
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return dict(body["error"])
    return {}
