# Coverage summary

Line coverage measured with `scripts/coverage_lite.py` (sys.settrace over the full pytest suite). CI additionally publishes the canonical `pytest-cov` report as a build artifact.

**Total: 95.0%** (5815/6123 executable lines)

| File | Lines | Covered | % |
| --- | ---: | ---: | ---: |
| `apps/alarm-api-simulator/alarm_simulator/__init__.py` | 2 | 2 | 100% |
| `apps/alarm-api-simulator/alarm_simulator/analytics.py` | 559 | 543 | 97% |
| `apps/alarm-api-simulator/alarm_simulator/app.py` | 367 | 334 | 91% |
| `apps/alarm-api-simulator/alarm_simulator/catalog.py` | 612 | 612 | 100% |
| `apps/alarm-api-simulator/alarm_simulator/schemas.py` | 63 | 63 | 100% |
| `apps/alarm-api-simulator/alarm_simulator/store.py` | 211 | 207 | 98% |
| `apps/backend/copilot/__init__.py` | 2 | 2 | 100% |
| `apps/backend/copilot/api.py` | 125 | 106 | 85% |
| `apps/backend/copilot/composer.py` | 166 | 137 | 83% |
| `apps/backend/copilot/config.py` | 32 | 31 | 97% |
| `apps/backend/copilot/domain.py` | 140 | 140 | 100% |
| `apps/backend/copilot/executor.py` | 240 | 221 | 92% |
| `apps/backend/copilot/intent.py` | 143 | 140 | 98% |
| `apps/backend/copilot/llm.py` | 115 | 110 | 96% |
| `apps/backend/copilot/mcp_client.py` | 182 | 159 | 87% |
| `apps/backend/copilot/orchestrator.py` | 298 | 288 | 97% |
| `apps/backend/copilot/planner.py` | 508 | 461 | 91% |
| `apps/backend/copilot/reasoning.py` | 317 | 302 | 95% |
| `apps/backend/copilot/retrieval_service.py` | 81 | 77 | 95% |
| `connectors/__init__.py` | 1 | 1 | 100% |
| `connectors/alarm_api/__init__.py` | 4 | 4 | 100% |
| `connectors/alarm_api/client.py` | 299 | 271 | 91% |
| `connectors/alarm_api/errors.py` | 64 | 53 | 83% |
| `mcp-servers/alarm-management/alarm_mcp/__init__.py` | 2 | 2 | 100% |
| `mcp-servers/alarm-management/alarm_mcp/app.py` | 52 | 52 | 100% |
| `mcp-servers/alarm-management/alarm_mcp/config.py` | 21 | 21 | 100% |
| `mcp-servers/alarm-management/alarm_mcp/models.py` | 204 | 204 | 100% |
| `mcp-servers/alarm-management/alarm_mcp/server.py` | 471 | 466 | 99% |
| `rag/ingestion/__init__.py` | 3 | 3 | 100% |
| `rag/ingestion/chunker.py` | 74 | 66 | 89% |
| `rag/ingestion/extractors.py` | 210 | 206 | 98% |
| `rag/ingestion/pipeline.py` | 97 | 90 | 93% |
| `rag/models.py` | 58 | 58 | 100% |
| `rag/retrieval/__init__.py` | 4 | 4 | 100% |
| `rag/retrieval/bm25.py` | 60 | 59 | 98% |
| `rag/retrieval/embeddings.py` | 99 | 86 | 87% |
| `rag/retrieval/index.py` | 61 | 59 | 97% |
| `rag/retrieval/retriever.py` | 112 | 111 | 99% |
| `rag/retrieval/text.py` | 24 | 24 | 100% |
| `rag/security.py` | 40 | 40 | 100% |
