"""Secondary MCP server (document-knowledge): discovery, schemas, retrieval, citations, quarantine, auth."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp.exceptions import ToolError

from conftest import LiveServer
from document_mcp.app import create_asgi_app
from document_mcp.config import DocServerSettings
from document_mcp.server import create_server

EXPECTED_TOOLS = {"search_documents", "get_document_section", "list_documents"}


def err_payload(exc: Exception) -> dict:
    text = str(exc)
    return json.loads(text[text.index("{") :])["error"]


@pytest.fixture(scope="module")
def doc_settings(rag_index_dir) -> DocServerSettings:
    return DocServerSettings(RAG_INDEX_PATH=str(rag_index_dir), DOCS_MCP_AUTO_INGEST=False)


@pytest.fixture(scope="module")
def doc_mcp(doc_settings):
    return create_server(doc_settings)


async def call(mcp, name, args):
    _, structured = await mcp.call_tool(name, args)
    return structured


async def test_tool_registration_and_typed_schemas(doc_mcp):
    tools = {t.name: t for t in await doc_mcp.list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    for t in tools.values():
        assert t.description and len(t.description) > 30
        assert t.outputSchema and "trace" in t.outputSchema["properties"]
        assert t.annotations.readOnlyHint is True and t.annotations.destructiveHint is False
    search = tools["search_documents"].inputSchema
    assert search["required"] == ["query"]
    assert search["properties"]["top_k"]["maximum"] == 10
    assert "operating_procedure" in json.dumps(search["properties"]["doc_types"])


async def test_search_returns_ranked_cited_passages(doc_mcp):
    out = await call(
        doc_mcp,
        "search_documents",
        {"query": "restart pump after low suction pressure trip", "doc_types": ["operating_procedure"]},
    )
    assert not out["low_confidence"] and out["results"]
    top = out["results"][0]
    assert top["rank"] == 1 and top["citation"]["doc_id"] == "SOP-BFP-001"
    assert top["citation"]["label"].startswith("SOP-BFP-001") and "§" in top["citation"]["label"]
    assert "/" in top["citation"]["source_path"] and "\\" not in top["citation"]["source_path"]
    assert all(p["citation"]["doc_type"] == "operating_procedure" for p in out["results"])
    assert out["trace"]["tool"] == "search_documents" and out["trace"]["index_version"]


async def test_low_confidence_for_off_topic_query(doc_mcp):
    out = await call(doc_mcp, "search_documents", {"query": "quarterly marketing budget for the cafeteria"})
    assert out["low_confidence"] is True


async def test_invalid_arguments_are_rejected(doc_mcp):
    with pytest.raises(ToolError):
        await call(doc_mcp, "search_documents", {"query": ""})
    with pytest.raises(ToolError):
        await call(doc_mcp, "search_documents", {"query": "pump", "doc_types": ["recipe"]})
    with pytest.raises(ToolError):
        await call(doc_mcp, "search_documents", {"query": "pump", "top_k": 50})


async def test_get_document_section_and_not_found(doc_mcp):
    hit = (await call(doc_mcp, "search_documents", {"query": "cavitation diagnosis"}))["results"][0]
    section = await call(doc_mcp, "get_document_section", {"chunk_id": hit["chunk_id"]})
    assert section["chunk_id"] == hit["chunk_id"] and section["citation"] == hit["citation"]
    with pytest.raises(ToolError) as ei:
        await call(doc_mcp, "get_document_section", {"chunk_id": "NOPE-000#missing"})
    assert err_payload(ei.value)["code"] == "NOT_FOUND"


async def test_quarantined_section_is_never_returned(doc_mcp):
    chunks = doc_mcp.runtime.retriever.index.chunks
    flagged = next(c for c in chunks if c.injection_suspected)
    with pytest.raises(ToolError) as ei:
        await call(doc_mcp, "get_document_section", {"chunk_id": flagged.chunk_id})
    assert err_payload(ei.value)["code"] == "QUARANTINED"
    out = await call(doc_mcp, "search_documents", {"query": flagged.text[:200], "top_k": 10})
    assert flagged.chunk_id not in {p["chunk_id"] for p in out["results"]}


async def test_list_documents_and_filter(doc_mcp):
    out = await call(doc_mcp, "list_documents", {})
    assert out["document_count"] >= 9 and len(out["documents"]) == out["document_count"]
    sops = await call(doc_mcp, "list_documents", {"doc_type": "operating_procedure"})
    assert sops["documents"] and all(d["doc_type"] == "operating_procedure" for d in sops["documents"])


async def test_missing_index_maps_to_index_unavailable(tmp_path):
    mcp = create_server(DocServerSettings(RAG_INDEX_PATH=str(tmp_path / "none"), DOCS_MCP_AUTO_INGEST=False))
    with pytest.raises(ToolError) as ei:
        await call(mcp, "list_documents", {})
    assert err_payload(ei.value)["code"] == "INDEX_UNAVAILABLE"


async def test_streamable_http_with_auth_and_trace(rag_index_dir):
    settings = DocServerSettings(
        RAG_INDEX_PATH=str(rag_index_dir), DOCS_MCP_AUTO_INGEST=False, DOCS_MCP_SERVER_TOKEN="docs-test-token"
    )
    with LiveServer(create_asgi_app(settings)) as srv:
        async with httpx.AsyncClient() as http:
            assert (await http.get(f"{srv.url}/healthz")).json()["tools"] == 3
            denied = await http.post(f"{srv.url}/mcp", json={}, headers={"Authorization": "Bearer wrong"})
            assert denied.status_code == 401
        headers = {"Authorization": "Bearer docs-test-token"}
        async with (
            streamablehttp_client(f"{srv.url}/mcp", headers=headers) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            assert {t.name for t in (await session.list_tools()).tools} == EXPECTED_TOOLS
            result = await session.call_tool(
                "search_documents", {"query": "motor trip related assets"}, meta={"trace_id": "trace-docs-1"}
            )
            assert not result.isError
            assert result.structuredContent["trace"]["trace_id"] == "trace-docs-1"
