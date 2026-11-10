"""Custom exceptions and global exception handlers."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base API error with the HTTP status and error code returned to clients."""

    status_code = 400
    code = "bad_request"

    def __init__(self, detail: str, status_code: int | None = None, code: str | None = None):
        """Set the response message and optionally override the default status and code."""
        self.detail = detail
        if status_code:
            self.status_code = status_code
        if code:
            self.code = code


class NotFoundError(AppError):
    """Raised when a requested database record does not exist."""

    status_code, code = 404, "not_found"


class ForbiddenError(AppError):
    """Raised when the authenticated user is not allowed to perform an action."""

    status_code, code = 403, "forbidden"


class ConflictError(AppError):
    """Raised when a request conflicts with existing data."""

    status_code, code = 409, "conflict"


class UnauthorizedError(AppError):
    """Raised when authentication credentials are missing or invalid."""

    status_code, code = 401, "unauthorized"


def _body(code: str, message: str, details=None) -> dict:
    """Build the consistent JSON error envelope returned by the API."""
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers that convert application and framework errors to JSON."""
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        """Return application errors using their declared status and error code."""
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_body(exc.code, exc.detail), status_code=exc.status_code, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        """Keep FastAPI and Starlette HTTP errors in the same JSON format."""
        return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        """Return invalid request fields in a client-readable error response."""
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(_body("validation_error", "Invalid request data", details), status_code=422)

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError):
        """Translate database constraint failures into a conflict response."""
        logger.warning("Integrity error: %s", exc.orig)
        return JSONResponse(_body("conflict", "Database constraint violated"), status_code=409)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        """Log unexpected failures and return a non-sensitive server error."""
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_body("internal_error", "Internal server error"), status_code=500)
