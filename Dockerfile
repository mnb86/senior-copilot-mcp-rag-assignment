# One Python image for the simulator, both MCP servers, RAG ingestion job and copilot backend.
# The service is selected by the compose `command`.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/apps/backend:/app/mcp-servers/alarm-management:/app/mcp-servers/optional-secondary-server

WORKDIR /app
COPY apps/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors ./connectors
COPY rag ./rag
COPY apps/backend ./apps/backend
COPY mcp-servers ./mcp-servers

# Run as an unprivileged user; the RAG index lives on a writable volume.
RUN useradd --create-home --uid 10001 app && mkdir -p /data/rag_index && chown -R app:app /data
USER app

EXPOSE 8000 9000 9100 8080
CMD ["python", "-m", "copilot"]
