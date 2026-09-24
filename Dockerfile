# One Python image for the simulator, MCP server, RAG ingestion job and copilot backend.
# The service is selected by the compose `command`.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/apps/backend:/app/apps/alarm-api-simulator:/app/mcp-servers/alarm-management

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors ./connectors
COPY rag ./rag
COPY apps/alarm-api-simulator ./apps/alarm-api-simulator
COPY apps/backend ./apps/backend
COPY mcp-servers ./mcp-servers

# Run as an unprivileged user; the RAG index lives on a writable volume.
RUN useradd --create-home --uid 10001 app && mkdir -p /data/rag_index && chown -R app:app /data
USER app

EXPOSE 8000 9000 8080
CMD ["python", "-m", "copilot"]
