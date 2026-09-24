"""Reusable connector for the Alarm Management API."""

from .client import AlarmApiClient, AlarmApiSettings, ApiResult, HttpAttempt, TraceContext
from .errors import (
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
