"""Copilot backend configuration (environment variables; secrets as SecretStr)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", populate_by_name=False, case_sensitive=True)

    # MCP
    mcp_server_url: str = Field("http://localhost:9000/mcp", alias="MCP_SERVER_URL")
    mcp_server_token: SecretStr = Field(SecretStr(""), alias="MCP_SERVER_TOKEN")
    mcp_timeout_seconds: float = Field(30.0, alias="MCP_TIMEOUT_SECONDS", gt=0, le=300)
    mcp_client_id: str = Field("alarm-copilot", alias="MCP_CLIENT_ID")
    tool_cache_seconds: float = Field(60.0, alias="MCP_TOOL_CACHE_SECONDS", ge=0)

    # RAG
    document_path: str = Field("rag/documents", alias="DOCUMENT_PATH")
    rag_index_path: str = Field("rag/retrieval/.index", alias="RAG_INDEX_PATH")
    embedding_provider: str = Field("lsa", alias="EMBEDDING_PROVIDER")
    rag_auto_ingest: bool = Field(True, alias="RAG_AUTO_INGEST")
    rag_top_k: int = Field(5, alias="RAG_TOP_K", ge=1, le=20)
    rag_low_confidence_threshold: float = Field(0.30, alias="RAG_LOW_CONFIDENCE_THRESHOLD", ge=0, le=1)

    # LLM (replaceable provider; "offline" = deterministic rules + templates, no network)
    llm_provider: str = Field("offline", alias="LLM_PROVIDER")
    llm_api_key: SecretStr = Field(SecretStr(""), alias="LLM_API_KEY")
    llm_model: str = Field("", alias="LLM_MODEL")
    llm_base_url: str = Field("", alias="LLM_BASE_URL")
    llm_timeout_seconds: float = Field(45.0, alias="LLM_TIMEOUT_SECONDS", gt=0)

    # Service
    host: str = Field("0.0.0.0", alias="COPILOT_HOST")
    port: int = Field(8080, alias="COPILOT_PORT")
    cors_origins: str = Field("http://localhost:5173,http://localhost:3000", alias="CORS_ORIGINS")
    default_lookback_days: int = Field(90, alias="DEFAULT_LOOKBACK_DAYS", ge=1, le=365)
    reference_time: str = Field("", alias="COPILOT_REFERENCE_TIME")  # optional fixed "now" for demos/tests
    log_level: str = Field("INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
