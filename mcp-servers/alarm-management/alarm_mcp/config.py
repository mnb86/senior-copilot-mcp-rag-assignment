"""Configuration for the Alarm Management MCP server (environment variables only)."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", populate_by_name=False, case_sensitive=True)

    # Alarm Management API (source system)
    alarm_api_base_url: str = Field("http://localhost:8000", alias="ALARM_API_BASE_URL")
    alarm_api_token: SecretStr = Field(SecretStr(""), alias="ALARM_API_TOKEN")
    alarm_api_timeout_seconds: float = Field(10.0, alias="ALARM_API_TIMEOUT_SECONDS", gt=0, le=120)
    alarm_api_max_retries: int = Field(2, alias="ALARM_API_MAX_RETRIES", ge=0, le=5)
    alarm_api_backoff_seconds: float = Field(0.25, alias="ALARM_API_BACKOFF_SECONDS", ge=0, le=10)

    # MCP transport
    host: str = Field("0.0.0.0", alias="MCP_HOST")
    port: int = Field(9000, alias="MCP_PORT")
    path: str = Field("/mcp", alias="MCP_PATH")
    auth_token: SecretStr = Field(SecretStr(""), alias="MCP_SERVER_TOKEN")
    allowed_hosts: str = Field("", alias="MCP_ALLOWED_HOSTS")  # comma separated, enables DNS-rebinding guard
    enabled_tools: str = Field("", alias="MCP_ENABLED_TOOLS")  # comma separated allow-list; empty = all
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    def enabled_tool_set(self) -> set[str] | None:
        names = {t.strip() for t in self.enabled_tools.split(",") if t.strip()}
        return names or None
