PY ?= python3
export PYTHONPATH := .:apps/backend:mcp-servers/alarm-management:mcp-servers/optional-secondary-server

.PHONY: help install install-frontend lint format typecheck test test-unit test-integration test-e2e coverage \
        ingest run-sim run-mcp run-mcp-stdio run-docs-mcp run-backend run-frontend postman smoke structure catalog screenshots up down logs clean

help:  ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install:  ## Install Python runtime + dev dependencies
	$(PY) -m pip install -r apps/backend/requirements-dev.txt

install-frontend:  ## Install frontend dependencies
	cd apps/frontend && npm install

lint:  ## Ruff lint + format check
	ruff check . && ruff format --check .

format:  ## Auto-format
	ruff format . && ruff check . --fix

typecheck:  ## Static type checking
	mypy apps/backend/copilot apps/backend/alarm_simulator mcp-servers/alarm-management/alarm_mcp \n	     mcp-servers/optional-secondary-server/document_mcp connectors rag

test:  ## Full test suite
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit rag/tests

test-integration:
	$(PY) -m pytest tests/integration

test-e2e:
	$(PY) -m pytest tests/e2e

coverage:  ## Tests with coverage (pytest-cov) -> htmlcov/ + coverage.xml
	$(PY) -m pytest --cov --cov-report=term-missing --cov-report=html --cov-report=xml

ingest:  ## Build / refresh the RAG index (idempotent; FORCE=1 to rebuild)
	$(PY) -m rag.ingestion --docs rag/documents --index rag/retrieval/.index $(if $(FORCE),--force,)

run-sim:  ## Alarm API simulator on :8000
	ALARM_API_TOKEN=demo-token SIM_FAULTS="POST /alarms/correlation=503x1" SIM_FAULT_CLIENTS=alarm-mcp-server,alarm-copilot $(PY) -m alarm_simulator

run-mcp:  ## MCP server (streamable HTTP) on :9000/mcp
	ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token MCP_SERVER_TOKEN=dev-mcp-token $(PY) -m alarm_mcp

run-mcp-stdio:  ## MCP server over stdio (for MCP Inspector / desktop clients)
	ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token $(PY) -m alarm_mcp --transport stdio

run-docs-mcp:  ## Secondary MCP server (document knowledge / RAG) on :9100/mcp
	DOCS_MCP_SERVER_TOKEN=dev-docs-mcp-token $(PY) -m document_mcp

run-backend:  ## Copilot backend on :8080
	MCP_SERVER_URL=http://localhost:9000/mcp MCP_SERVER_TOKEN=dev-mcp-token $(PY) -m copilot

run-frontend:  ## Vite dev server on :5173 (proxies /api to :8080)
	cd apps/frontend && npm run dev

postman:  ## Run the Postman contract collections against a running simulator
	node scripts/postman_runner.mjs test-data/postman/Alarm-API-Simulator.postman_collection.json http://localhost:8000 demo-token
	node scripts/postman_runner.mjs test-data/postman/chaining/Alarm-API-Chaining.postman_collection.json http://localhost:8000 demo-token
	node scripts/postman_runner.mjs test-data/postman/scenarios/Alarm-API-Scenarios.postman_collection.json http://localhost:8000 demo-token

smoke:  ## Call every API endpoint, MCP tool and copilot endpoint on a running stack
	$(PY) scripts/smoke_test.py

structure:  ## Check the repo against the assignment's required folder tree
	$(PY) scripts/check_structure.py

catalog:  ## Regenerate docs/mcp-tool-catalog.md from both MCP servers
	$(PY) scripts/generate_tool_catalog.py

screenshots:  ## Retake docs/screenshots from a running stack (headless Edge)
	node scripts/capture_screenshots.mjs docs/screenshots http://localhost:3000/

up:  ## docker compose up --build
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=100

clean:
	rm -rf rag/retrieval/.index htmlcov coverage.xml .pytest_cache .mypy_cache .ruff_cache apps/frontend/dist
