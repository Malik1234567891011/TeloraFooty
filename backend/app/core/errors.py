"""Application error types and a standard API response envelope.

All API responses follow the shape described in docs/bestpractices.md:

    {"status": "...", "data": {...} | null, "error": {...} | null}

Routes should raise ``AppError`` (or a subclass) for expected failures; a
global handler converts them into clean JSON without leaking stack traces.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, client-facing errors."""

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class InvalidVideoError(AppError):
    status_code = 400
    code = "INVALID_VIDEO"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class ProcessingError(AppError):
    status_code = 500
    code = "PROCESSING_ERROR"


def success_response(data: Any, status: str = "completed") -> dict[str, Any]:
    """Wrap a successful payload in the standard envelope."""
    return {"status": status, "data": data, "error": None}


def error_response(message: str, code: str = "ERROR") -> dict[str, Any]:
    """Wrap an error in the standard envelope."""
    return {"status": "failed", "data": None, "error": {"message": message, "code": code}}
