"""API connector (source-system client): payloads, auth, trace headers, retries, timeouts, pagination."""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import TOKEN, _no_sleep, api_client_for
from connectors.alarm_api import (
    AlarmApiClient,
    AlarmApiSettings,
    AuthenticationError,
    ConnectionFailedError,
    InvalidRequestError,
    NotFoundError,
    TraceContext,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)


def mock_client(handler, **settings) -> AlarmApiClient:
    cfg = {"base_url": "http://api", "token": "s3cr3t", "max_retries": 2, "backoff_base_seconds": 0.0, **settings}
    return AlarmApiClient(AlarmApiSettings(**cfg), transport=httpx.MockTransport(handler), sleep=_no_sleep)


async def test_auth_and_trace_headers_and_payload():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"groups": [], "totals": {}, "group_count": 0})

    c = mock_client(handler)
    trace = TraceContext(trace_id="trace-abc", client_id="copilot", metadata_tag="demo")
    await c.alarm_summary(trace, {"asset_ids": ["AST-1"], "time_range": {"start_time": "a", "end_time": "b"}})
    req = seen[0]
    assert req.headers["authorization"] == "Bearer s3cr3t"
    assert req.headers["trace_id"] == "trace-abc"
    assert req.headers["x-client-id"] == "copilot"
    assert req.headers["x-metadata-tag"] == "demo"
    assert req.headers["x-request-id"]
    assert json.loads(req.content)["asset_ids"] == ["AST-1"]
    assert req.url.path == "/alarms/summary"


async def test_none_query_params_are_dropped_and_path_segments_encoded():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"results": []})

    c = mock_client(handler)
    await c.search_assets(TraceContext(), "pump", limit=3, site=None)
    assert "site" not in seen[0].url.params and seen[0].url.params["limit"] == "3"
    await c.asset_metadata(TraceContext(), "../admin")
    assert seen[1].url.raw_path == b"/assets/..%2Fadmin/metadata"


async def test_retries_transient_503_then_succeeds():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"code": "BUSY", "message": "busy"}})
        return httpx.Response(200, json={"ok": True})

    res = await mock_client(handler).request("GET", "/x", trace=TraceContext())
    assert res.data == {"ok": True} and res.retries == 2
    assert [a.outcome for a in res.attempts] == ["retry", "retry", "ok"]


async def test_exhausted_retries_raise_upstream_unavailable_with_attempts():
    c = mock_client(lambda req: httpx.Response(503, json={"error": {"code": "DOWN", "message": "down"}}))
    with pytest.raises(UpstreamUnavailableError) as ei:
        await c.request("GET", "/x", trace=TraceContext(trace_id="t-1"))
    err = ei.value
    assert err.attempts == 3 and err.retryable and err.trace_id == "t-1" and err.upstream_code == "DOWN"
    assert len(err.details["http_attempts"]) == 3


@pytest.mark.parametrize("status,exc", [(401, AuthenticationError), (404, NotFoundError), (422, InvalidRequestError)])
async def test_non_retryable_errors_fail_fast(status, exc):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, json={"error": {"code": "X", "message": "nope"}})

    with pytest.raises(exc):
        await mock_client(handler).request("GET", "/x", trace=TraceContext())
    assert calls["n"] == 1


async def test_timeout_and_connection_errors_are_mapped_and_retried():
    calls = {"n": 0}

    def timeout(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(UpstreamTimeoutError) as ei:
        await mock_client(timeout, max_retries=1).request("GET", "/x", trace=TraceContext())
    assert calls["n"] == 2 and ei.value.attempts == 2

    def refused(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(ConnectionFailedError):
        await mock_client(refused, max_retries=0).request("GET", "/x", trace=TraceContext())


async def test_backoff_honours_retry_after():
    delays: list[float] = []

    async def record(d: float) -> None:
        delays.append(d)

    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "1"}) if calls["n"] == 1 else httpx.Response(200, json={})

    c = AlarmApiClient(
        AlarmApiSettings(base_url="http://api", token="t", backoff_max_seconds=4),
        transport=httpx.MockTransport(handler),
        sleep=record,
    )
    await c.request("GET", "/x", trace=TraceContext())
    assert delays == [1.0]


async def test_token_never_leaks_into_repr_or_attempt_records():
    c = mock_client(lambda req: httpx.Response(200, json={}))
    res = await c.request("GET", "/x", trace=TraceContext())
    assert "s3cr3t" not in repr(c.settings)
    assert "s3cr3t" not in json.dumps([a.to_dict() for a in res.attempts])


async def test_pagination_follows_has_next(sim_app):
    c = api_client_for(sim_app)
    res = await c.list_alarms_all_pages(TraceContext(), {"asset_id": "AST-BFP-101", "page_size": 20}, max_pages=3)
    assert len(res.data["data"]) == 60
    assert res.data["pagination"]["pages_fetched"] == 3 and res.data["pagination"]["truncated"] is True
    ids = [a["alarm_id"] for a in res.data["data"]]
    assert len(ids) == len(set(ids))


async def test_real_simulator_auth_failure(sim_app):
    c = api_client_for(sim_app, token="wrong")
    with pytest.raises(AuthenticationError):
        await c.search_assets(TraceContext(), "pump")
    assert TOKEN != "wrong"
