"""Typed errors raised by the Alarm Management API connector."""

from __future__ import annotations

from typing import Any


class AlarmApiError(Exception):
    """Base class. ``code`` is a stable machine-readable identifier used by the MCP error mapping."""

    code = "ALARM_API_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        upstream_code: str | None = None,
        details: Any = None,
        attempts: int = 1,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.upstream_code = upstream_code
        self.details = details
        self.attempts = attempts
        self.trace_id = trace_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "http_status": self.status,
            "upstream_code": self.upstream_code,
            "retryable": self.retryable,
            "attempts": self.attempts,
            "trace_id": self.trace_id,
            "details": self.details,
        }


class AuthenticationError(AlarmApiError):
    code = "AUTHENTICATION_FAILED"


class NotFoundError(AlarmApiError):
    code = "NOT_FOUND"


class InvalidRequestError(AlarmApiError):
    code = "INVALID_REQUEST"


class RateLimitedError(AlarmApiError):
    code = "RATE_LIMITED"
    retryable = True


class UpstreamUnavailableError(AlarmApiError):
    code = "UPSTREAM_UNAVAILABLE"
    retryable = True


class UpstreamTimeoutError(AlarmApiError):
    code = "UPSTREAM_TIMEOUT"
    retryable = True


class ConnectionFailedError(AlarmApiError):
    code = "CONNECTION_FAILED"
    retryable = True


class UnexpectedResponseError(AlarmApiError):
    code = "UNEXPECTED_RESPONSE"


def error_for_status(status: int) -> type[AlarmApiError]:
    if status in (401, 403):
        return AuthenticationError
    if status == 404:
        return NotFoundError
    if status in (400, 409, 422):
        return InvalidRequestError
    if status == 429:
        return RateLimitedError
    if status == 504:
        return UpstreamTimeoutError
    if status >= 500:
        return UpstreamUnavailableError
    return UnexpectedResponseError
