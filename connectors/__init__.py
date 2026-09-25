"""Source-system connectors: reusable Alarm Management API client (auth, retry, errors, pagination)."""

from .alarm_api_client import AlarmApiClient, AlarmApiSettings, ApiResult, HttpAttempt, TraceContext
from .alarm_api_errors import (
    AlarmApiError,
    AuthenticationError,
    ConnectionFailedError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    UnexpectedResponseError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

__all__ = [
    "AlarmApiClient",
    "AlarmApiError",
    "AlarmApiSettings",
    "ApiResult",
    "AuthenticationError",
    "ConnectionFailedError",
    "HttpAttempt",
    "InvalidRequestError",
    "NotFoundError",
    "RateLimitedError",
    "TraceContext",
    "UnexpectedResponseError",
    "UpstreamTimeoutError",
    "UpstreamUnavailableError",
]
