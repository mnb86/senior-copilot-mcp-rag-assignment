"""MCP client integration: tool discovery, schema-aware invocation, policy and error mapping.

The orchestrator depends only on the :class:`ToolSession` protocol, so it can be exercised with an
in-memory fake in unit tests while production uses :class:`McpHttpGateway` (streamable HTTP).
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Protocol

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
except ImportError as exc:  # mcp 2.x changed the client API
    raise ImportError(
        'This project targets the MCP Python SDK v1 (FastMCP API). Install it with: pip install "mcp>=1.27,<2"'
    ) from exc
from pydantic import BaseModel

from .config import Settings

log = logging.getLogger("copilot.mcp")


class ToolSpec(BaseModel):
    name: str
    title: str | None = None
    description: str = ""
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    read_only: bool = False
    server: str = "alarm-management"


class ToolOutcome(BaseModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    duration_ms: float = 0.0
    output_schema_valid: bool | None = None


class McpClientError(Exception):
    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ToolSession(Protocol):
    server_name: str

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call_tool(
        self, name: str, arguments: dict[str, Any], meta: dict[str, Any], confirmed: bool = False
    ) -> ToolOutcome: ...


def parse_tool_error(text: str) -> dict[str, Any]:
    """Tool errors from the server are ``'Error executing tool X: {json}'`` or pydantic messages."""
    start = text.find("{")
    if start >= 0:
        try:
            payload = json.loads(text[start:])
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                return dict(payload["error"])
        except json.JSONDecodeError:
            pass
    if "validation error" in text.lower():
        return {"code": "INVALID_ARGUMENT", "message": text.split(":", 1)[-1].strip()[:500]}
    if "unknown tool" in text.lower():
        return {"code": "TOOL_NOT_FOUND", "message": text[:300]}
    return {"code": "TOOL_ERROR", "message": text[:500]}


class ValidatingSession:
    """Adds client-side schema validation and tool-authorization policy on top of a raw MCP session."""

    def __init__(
        self, session: ClientSession, server_name: str, timeout_s: float, tools: list[ToolSpec] | None = None
    ) -> None:
        self._session = session
        self.server_name = server_name
        self._timeout = timeout_s
        self._tools: dict[str, ToolSpec] | None = {t.name: t for t in tools} if tools else None

    async def list_tools(self) -> list[ToolSpec]:
        if self._tools is None:
            res = await self._session.list_tools()
            specs = []
            for t in res.tools:
                ann = t.annotations
                specs.append(
                    ToolSpec(
                        name=t.name,
                        title=t.title,
                        description=t.description or "",
                        input_schema=t.inputSchema,
                        output_schema=t.outputSchema,
                        read_only=bool(ann and ann.readOnlyHint),
                        server=self.server_name,
                    )
                )
            self._tools = {s.name: s for s in specs}
        return list(self._tools.values())

    async def call_tool(
        self, name: str, arguments: dict[str, Any], meta: dict[str, Any], confirmed: bool = False
    ) -> ToolOutcome:
        tools = {t.name: t for t in await self.list_tools()}
        spec = tools.get(name)
        if spec is None:
            raise McpClientError(
                "TOOL_NOT_FOUND",
                f"Tool '{name}' is not offered by MCP server '{self.server_name}'",
                {"available": sorted(tools)},
            )
        if not spec.read_only and not confirmed:
            raise McpClientError(
                "CONFIRMATION_REQUIRED", f"Tool '{name}' may modify state and requires explicit user confirmation"
            )
        errors = sorted(Draft202012Validator(spec.input_schema).iter_errors(arguments), key=lambda e: e.path)
        if errors:
            raise McpClientError(
                "INVALID_ARGUMENT",
                "Arguments do not match the tool input schema",
                [{"path": "/".join(str(p) for p in e.path), "message": e.message} for e in errors],
            )
        started = time.perf_counter()
        try:
            result = await self._session.call_tool(
                name, arguments, read_timeout_seconds=timedelta(seconds=self._timeout), meta=meta
            )
        except Exception as exc:  # transport-level failure
            raise McpClientError(
                "MCP_CALL_FAILED", f"MCP call to '{name}' failed: {type(exc).__name__}: {exc}"
            ) from exc
        duration = round((time.perf_counter() - started) * 1000, 1)
        if result.isError:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            return ToolOutcome(ok=False, error=parse_tool_error(text), duration_ms=duration)
        data = result.structuredContent
        if data is None:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {"text": text}
        valid: bool | None = None
        if spec.output_schema:
            try:
                Draft202012Validator(spec.output_schema).validate(data)
                valid = True
            except SchemaError:
                valid = False
        return ToolOutcome(ok=True, data=data, duration_ms=duration, output_schema_valid=valid)


class McpHttpGateway:
    """Opens MCP sessions over streamable HTTP and caches tool discovery."""

    def __init__(self, settings: Settings, server_name: str = "alarm-management") -> None:
        self.settings = settings
        self.server_name = server_name
        self._tool_cache: tuple[float, list[ToolSpec]] | None = None

    def _headers(self) -> dict[str, str]:
        h = {"x-client-id": self.settings.mcp_client_id}
        token = self.settings.mcp_server_token.get_secret_value()
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[ValidatingSession]:
        url = self.settings.mcp_server_url
        entered = False
        try:
            async with contextlib.AsyncExitStack() as stack:
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(url, headers=self._headers(), timeout=self.settings.mcp_timeout_seconds)
                )
                raw = await stack.enter_async_context(ClientSession(read, write))
                await raw.initialize()
                cached = None
                if self._tool_cache and time.monotonic() - self._tool_cache[0] < self.settings.tool_cache_seconds:
                    cached = self._tool_cache[1]
                vs = ValidatingSession(raw, self.server_name, self.settings.mcp_timeout_seconds, cached)
                tools = await vs.list_tools()
                self._tool_cache = (time.monotonic(), tools)
                entered = True
                yield vs
        except McpClientError:
            raise
        except BaseExceptionGroup as eg:  # anyio task-group errors from the transport
            if entered and not _is_transport_error(eg):
                raise
            raise McpClientError("MCP_UNAVAILABLE", _describe(eg), {"url": url}) from eg
        except (httpx.HTTPError, OSError, RuntimeError) as exc:
            if entered:
                raise
            raise McpClientError("MCP_UNAVAILABLE", _describe(exc), {"url": url}) from exc

    async def discover(self) -> list[ToolSpec]:
        async with self.session() as s:
            return await s.list_tools()


def _is_transport_error(eg: BaseExceptionGroup) -> bool:
    return all(isinstance(e, (httpx.HTTPError, OSError)) for e in eg.exceptions)


def _describe(exc: BaseException) -> str:
    leaf: BaseException = exc
    while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
        leaf = leaf.exceptions[0]
    msg = str(leaf)
    if "401" in msg:
        return "MCP server rejected the credentials (HTTP 401)"
    return f"MCP server unreachable: {type(leaf).__name__}: {msg[:200]}"
