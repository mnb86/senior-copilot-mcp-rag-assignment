"""Configuration for the Document Knowledge MCP server (environment variables only)."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DocServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", populate_by_name=False, case_sensitive=True)

    # RAG corpus and index (shared with the ingestion pipeline)
    document_path: str = Field("rag/documents", alias="DOCUMENT_PATH")
    index_path: str = Field("rag/retrieval/.index", alias="RAG_INDEX_PATH")
    embedder: str = Field("lsa", alias="EMBEDDING_PROVIDER")
    auto_ingest: bool = Field(True, alias="DOCS_MCP_AUTO_INGEST")  # build/refresh the index on first use
    low_confidence_threshold: float = Field(0.30, alias="RAG_LOW_CONFIDENCE_THRESHOLD", ge=0, le=1)

    # MCP transport
    host: str = Field("0.0.0.0", alias="DOCS_MCP_HOST")
    port: int = Field(9100, alias="DOCS_MCP_PORT")
    path: str = Field("/mcp", alias="DOCS_MCP_PATH")
    auth_token: SecretStr = Field(SecretStr(""), alias="DOCS_MCP_SERVER_TOKEN")
    allowed_hosts: str = Field("", alias="DOCS_MCP_ALLOWED_HOSTS")  # comma separated, enables DNS-rebinding guard
    log_level: str = Field("INFO", alias="LOG_LEVEL")
