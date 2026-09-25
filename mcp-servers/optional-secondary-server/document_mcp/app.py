"""ASGI application for the Document Knowledge MCP server: streamable HTTP + bearer auth + health."""

from __future__ import annotations

import contextlib
import hmac
from collections.abc import AsyncIterator
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import DocServerSettings
from .server import SERVER_NAME, create_server


class BearerAuthMiddleware:
    """Require ``Authorization: Bearer <DOCS_MCP_SERVER_TOKEN>`` on the MCP endpoint (if a token is configured)."""

    def __init__(self, app: ASGIApp, token: str, exempt: tuple[str, ...] = ("/healthz",)) -> None:
        self.app = app
        self.token = token
        self.exempt = exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.token or scope.get("path") in self.exempt:
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        scheme, _, supplied = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip(), self.token):
            resp = JSONResponse(
                {"error": {"code": "UNAUTHORIZED", "message": "Invalid MCP bearer token"}},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_asgi_app(settings: DocServerSettings | None = None, mcp: FastMCP | None = None) -> Starlette:
    settings = settings or DocServerSettings()
    mcp = mcp or create_server(settings)
    mcp_app = mcp.streamable_http_app()

    async def healthz(request: Request) -> JSONResponse:
        tools = await mcp.list_tools()
        return JSONResponse({"status": "ok", "server": SERVER_NAME, "tools": len(tools)})

    @contextlib.asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=[Route("/healthz", healthz), Mount("/", app=mcp_app)], lifespan=lifespan)
    app.add_middleware(BearerAuthMiddleware, token=settings.auth_token.get_secret_value())
    app.state.mcp = mcp
    return app
