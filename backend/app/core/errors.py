"""Domain exceptions and their HTTP mapping.

Services raise these; the API layer converts them into consistent JSON errors
(``{"error": {"code", "message", "details"}}``). Unexpected exceptions become a
generic 500 with a correlation id - stack traces are logged, never returned.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger("app.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class UnsupportedImage(AppError):
    status_code = 415
    code = "unsupported_image"


class CorruptedFile(AppError):
    status_code = 422
    code = "corrupted_file"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class InsufficientCapacity(AppError):
    status_code = 422
    code = "insufficient_capacity"


class NoPayloadFound(AppError):
    status_code = 422
    code = "no_payload_found"


class IntegrityFailure(AppError):
    status_code = 422
    code = "integrity_failure"


class DecryptionFailure(AppError):
    status_code = 422
    code = "decryption_failed"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ModelUnavailable(AppError):
    status_code = 503
    code = "model_unavailable"


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {}
        if isinstance(exc, RateLimited) and "retry_after" in exc.details:
            headers["Retry-After"] = str(exc.details["retry_after"])
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in err.get("loc", []) if p != "body"), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_failed", "Request validation failed", {"fields": fields}), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(error_body("http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        incident = uuid.uuid4().hex[:12]
        log.exception("Unhandled error on %s %s [incident=%s]", request.method, request.url.path, incident)
        return JSONResponse(
            error_body("internal_error", "An internal error occurred. Reference this incident id.", {"incident": incident}),
            status_code=500,
        )
