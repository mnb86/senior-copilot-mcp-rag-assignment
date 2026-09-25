```text
Subject: Senior Software Engineer Copilot Assignment Submission

Repository:
https://github.com/mnb86/senior-copilot-mcp-rag-assignment

Selected use case:
Alarm Investigation and Procedure Guidance Copilot

MCP server:
"alarm-management" - 13 typed, read-only tools over the Alarm Management API (asset search, metadata, alarms,
summary, trends, correlation, priority scoring, operator recommendations, flood, rationalization, KPIs) with input
validation, bearer auth, timeout/retry, error mapping and trace propagation. Streamable HTTP or stdio. A second server, "document-knowledge" (3 tools), exposes the
document corpus to any MCP client.
Start: PYTHONPATH=.:mcp-servers/alarm-management ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token python -m alarm_mcp

Document RAG:
10 SOPs/manuals/troubleshooting/safety/philosophy documents (md, txt, html, pdf) in rag/documents.
Ingestion: python -m rag.ingestion --docs rag/documents --index rag/retrieval/.index
Retrieval: hybrid BM25 + LSA dense vectors, metadata filters derived from MCP results, multi-query fusion,
low-confidence handling, prompt-injection quarantine, citations.

Run instructions:
docker compose up --build   (GUI: http://localhost:3000)

Test instructions:
make test   (146 tests; make lint typecheck coverage postman smoke structure)

Demo:
docs/screenshots/ (9 screenshots) and the README

Demo video (up to 10 minutes):
<link>

Known limitations:
Rule-based intent detection by default (LLM optional); corpus-local LSA embeddings; in-memory conversation store;
no end-user auth; read-only scope (no ticketing).

Estimated implementation time:
<hours>
```
