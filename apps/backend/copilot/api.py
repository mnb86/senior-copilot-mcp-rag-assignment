"""HTTP API for the GUI (Starlette)."""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from rag.retrieval.models import RetrievalFilters

from .config import Settings, get_settings
from .domain import ChatRequest
from .llm import create_provider
from .mcp_client import McpClientError, McpHttpGateway
from .orchestrator import Copilot
from .retrieval_service import RetrievalService

log = logging.getLogger("copilot.api")
MAX_BODY = 16_384
_HERE = Path(__file__).resolve().parent


def gui_directory() -> Path | None:
    """GUI served at "/": COPILOT_GUI_DIR, else a fresh `npm run build` (apps/frontend/dist), else the pre-built
    bundle shipped in copilot/static - so the app works at http://localhost:8080 without Node.js."""
    candidates = [os.getenv("COPILOT_GUI_DIR", ""), str(_HERE.parents[1] / "frontend" / "dist"), str(_HERE / "static")]
    for c in candidates:
        if c and (Path(c) / "index.html").is_file():
            return Path(c)
    return None


def _err(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)


def create_app(settings: Settings | None = None, copilot: Copilot | None = None) -> Starlette:
    s = settings or get_settings()
    state: dict[str, Any] = {"copilot": copilot}

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if state["copilot"] is None:
            retrieval = None
            try:
                retrieval = RetrievalService(
                    s.rag_index_path,
                    s.document_path,
                    embedder=s.embedding_provider,
                    auto_ingest=s.rag_auto_ingest,
                    top_k=s.rag_top_k,
                    low_confidence_threshold=s.rag_low_confidence_threshold,
                )
            except Exception as exc:  # noqa: BLE001 - service still starts; answers degrade
                log.error("retrieval index unavailable: %s", exc)
            state["copilot"] = Copilot(s, McpHttpGateway(s), retrieval, create_provider(s))
        yield

    def cp() -> Copilot:
        c = state["copilot"]
        assert c is not None
        return c

    async def health(request: Request) -> JSONResponse:
        c = cp()
        rag = c.retrieval.manifest if c.retrieval is not None and hasattr(c.retrieval, "manifest") else {}
        return JSONResponse(
            {
                "status": "ok",
                "service": "copilot-backend",
                "llm_provider": c.llm.name if c.llm else "offline",
                "rag": {
                    "documents": rag.get("document_count"),
                    "chunks": rag.get("chunk_count"),
                    "embedder": rag.get("embedder"),
                    "created_at": rag.get("created_at"),
                },
                "mcp_server_url": s.mcp_server_url,
            }
        )

    async def tools(request: Request) -> JSONResponse:
        c = cp()
        if c.gateway is None:
            return _err(503, "MCP_NOT_CONFIGURED", "No MCP server configured")
        try:
            async with c.gateway.session() as session:
                specs = await session.list_tools()
        except McpClientError as exc:
            return _err(503, exc.code, exc.message, exc.details)
        return JSONResponse(
            {"server": c.gateway.server_name, "url": s.mcp_server_url, "tools": [t.model_dump() for t in specs]}
        )

    async def chat(request: Request) -> JSONResponse:
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return _err(413, "PAYLOAD_TOO_LARGE", "Request body too large")
        try:
            req = ChatRequest.model_validate(json.loads(raw or b"{}"))
        except (ValidationError, json.JSONDecodeError) as exc:
            details = exc.errors() if isinstance(exc, ValidationError) else str(exc)
            return _err(422, "INVALID_REQUEST", "Invalid chat request", json.loads(json.dumps(details, default=str)))
        try:
            resp = await cp().handle(req)
        except Exception:
            log.exception("chat request failed")
            return _err(500, "INTERNAL_ERROR", "The copilot failed to process the request")
        return JSONResponse(resp.model_dump(mode="json"))

    async def conversation(request: Request) -> JSONResponse:
        cid = request.path_params["cid"]
        return JSONResponse({"conversation_id": cid, "turns": cp().store.history(cid)})

    async def rag_search(request: Request) -> JSONResponse:
        c = cp()
        q = request.query_params.get("q", "")[:500]
        if c.retrieval is None or not hasattr(c.retrieval, "search"):
            return _err(503, "RETRIEVAL_UNAVAILABLE", "Retrieval index not loaded")
        doc_types = [d for d in request.query_params.get("doc_type", "").split(",") if d] or None
        res = c.retrieval.search(q, RetrievalFilters(doc_types=doc_types))
        return JSONResponse(res.model_dump(mode="json"))

    async def reindex(request: Request) -> JSONResponse:
        token = os.getenv("COPILOT_ADMIN_TOKEN", "")
        if not token or request.headers.get("x-admin-token") != token:
            return _err(403, "FORBIDDEN", "Re-indexing requires COPILOT_ADMIN_TOKEN")
        c = cp()
        if c.retrieval is None or not hasattr(c.retrieval, "reindex"):
            return _err(503, "RETRIEVAL_UNAVAILABLE", "Retrieval index not loaded")
        return JSONResponse(c.retrieval.reindex(force=True))

    routes: list[BaseRoute] = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/tools", tools, methods=["GET"]),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/conversations/{cid:str}", conversation, methods=["GET"]),
        Route("/api/rag/search", rag_search, methods=["GET"]),
        Route("/api/rag/reindex", reindex, methods=["POST"]),
    ]
    gui = gui_directory()
    if gui is not None:
        routes.append(Mount("/", app=StaticFiles(directory=gui, html=True), name="gui"))
    origins = [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    return Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_methods=["GET", "POST"],
                allow_headers=["content-type", "x-admin-token"],
            )
        ],
    )
