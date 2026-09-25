"""Shared fixtures.

Async tests are supported without extra plugins: coroutine test functions are executed with
``asyncio.run`` by the ``pytest_pyfunc_call`` hook below. Fixtures stay synchronous.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from alarm_mcp.config import ServerSettings
from alarm_mcp.server import create_server
from alarm_simulator.app import SimSettings, create_app
from alarm_simulator.store import parse_time
from connectors.alarm_api import AlarmApiClient, AlarmApiSettings
from copilot.mcp_client import ToolOutcome, ToolSpec, parse_tool_error
from rag.ingestion import ingest

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "rag" / "documents"
ANCHOR = "2026-07-01T00:00:00Z"
TOKEN = "test-api-token"


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        kwargs = {a: pyfuncitem.funcargs[a] for a in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**kwargs))
        return True
    return None


async def _no_sleep(_: float) -> None:
    return None


# ---------------------------------------------------------------------------- simulator
def make_sim(**overrides: Any) -> Any:
    s = SimSettings(token=TOKEN, anchor=parse_time(ANCHOR), seed=42)
    for k, v in overrides.items():
        setattr(s, k, v)
    return create_app(s)


@pytest.fixture(scope="session")
def sim_app() -> Any:
    return make_sim()


@pytest.fixture(scope="session")
def sim_app_faulty() -> Any:
    return make_sim(faults={"POST /alarms/correlation": (503, 1)})


def api_client_for(app: Any, **settings: Any) -> AlarmApiClient:
    cfg = {"base_url": "http://sim", "token": TOKEN, "max_retries": 2, "backoff_base_seconds": 0.0, **settings}
    return AlarmApiClient(AlarmApiSettings(**cfg), transport=httpx.ASGITransport(app=app), sleep=_no_sleep)


# ---------------------------------------------------------------------------- MCP server (in-process)
def make_mcp(app: Any, enabled_tools: str = "") -> Any:
    settings = ServerSettings(MCP_ENABLED_TOOLS=enabled_tools)
    return create_server(settings, api_client_for(app))


class InProcessSession:
    """ToolSession adapter that calls a FastMCP server in-process (no transport) for orchestration tests."""

    server_name = "alarm-management"

    def __init__(self, mcp: Any) -> None:
        self.mcp = mcp
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def list_tools(self) -> list[ToolSpec]:
        tools = await self.mcp.list_tools()
        return [
            ToolSpec(
                name=t.name,
                title=t.title,
                description=t.description or "",
                input_schema=t.inputSchema,
                output_schema=t.outputSchema,
                read_only=bool(t.annotations and t.annotations.readOnlyHint),
            )
            for t in tools
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], meta: dict[str, Any], confirmed: bool = False
    ) -> ToolOutcome:
        self.calls.append((name, arguments, meta))
        try:
            result = await self.mcp.call_tool(name, arguments)
        except Exception as exc:
            return ToolOutcome(ok=False, error=parse_tool_error(str(exc)))
        data = result[1] if isinstance(result, tuple) else result
        return ToolOutcome(ok=True, data=data)


class InProcessGateway:
    server_name = "alarm-management"

    def __init__(self, mcp: Any) -> None:
        self.session_obj = InProcessSession(mcp)

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[InProcessSession]:
        yield self.session_obj


# ---------------------------------------------------------------------------- RAG
@pytest.fixture(scope="session")
def rag_index_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("rag_index")
    report = ingest(DOCS, out, force=True)
    assert report.documents >= 9 and not report.errors
    return out


# ---------------------------------------------------------------------------- live servers (real HTTP)
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class LiveServer:
    def __init__(self, app: Any) -> None:
        self.port = free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> LiveServer:
        self.thread.start()
        deadline = time.time() + 15
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture(scope="session")
def live_stack() -> Iterator[dict[str, str]]:
    """Simulator + MCP server over real HTTP (streamable HTTP transport with bearer auth)."""
    from alarm_mcp.app import create_asgi_app

    sim = make_sim(faults={"POST /alarms/correlation": (503, 1)})
    with LiveServer(sim) as sim_srv:
        settings = ServerSettings(
            ALARM_API_BASE_URL=sim_srv.url,
            ALARM_API_TOKEN=TOKEN,
            MCP_SERVER_TOKEN="mcp-test-token",
            ALARM_API_BACKOFF_SECONDS=0.01,
        )
        with LiveServer(create_asgi_app(settings)) as mcp_srv:
            yield {
                "sim_url": sim_srv.url,
                "mcp_url": f"{mcp_srv.url}/mcp",
                "mcp_base": mcp_srv.url,
                "mcp_token": "mcp-test-token",
            }
