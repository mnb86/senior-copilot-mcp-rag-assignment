```text
Subject: Senior Software Engineer Copilot Assignment Submission

Repository:
<GitHub repository URL>

Selected use case:
Alarm Investigation and Procedure Guidance Copilot

MCP server:
"alarm-management" - 13 typed, read-only tools over the Alarm Management API (asset search, metadata, alarms,
summary, trends, correlation, priority scoring, operator recommendations, flood, rationalization, KPIs) with input
validation, bearer auth, timeout/retry, error mapping and trace propagation. Streamable HTTP or stdio.
Start: PYTHONPATH=.:mcp-servers/alarm-management ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token python -m alarm_mcp

Document RAG:
10 SOPs/manuals/troubleshooting/safety/philosophy documents (md, txt, html, pdf) in rag/documents.
Ingestion: python -m rag.ingestion --docs rag/documents --index .rag_index
Retrieval: hybrid BM25 + LSA dense vectors, metadata filters derived from MCP results, multi-query fusion,
low-confidence handling, prompt-injection quarantine, citations.

Run instructions:
docker compose up --build   (GUI: http://localhost:3000)

Test instructions:
make test   (128 tests; make lint typecheck coverage postman)

Demo:
docs/screenshots/ and README

Demo video (up to 10 minutes):
<link>

Known limitations:
Rule-based intent detection by default (LLM optional); corpus-local LSA embeddings; in-memory conversation store;
no end-user auth; read-only scope (no ticketing).

Estimated implementation time:
<hours>
```
