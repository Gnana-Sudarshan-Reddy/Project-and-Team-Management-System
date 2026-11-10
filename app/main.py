"""Create and configure the FastAPI application and its middleware."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.base import Base
from app.db.init_db import init_db
from app.db.session import SessionLocal, engine

setup_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Optionally create tables, seed required data, and manage app startup."""
    if settings.AUTO_CREATE_TABLES:
        import app.models  # noqa: F401  (register models)
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        init_db(db)  # seeds roles + first admin (tables must exist: run `alembic upgrade head`)
    logger.info("%s started (%s)", settings.APP_NAME, settings.ENVIRONMENT)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    debug=settings.DEBUG,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
register_exception_handlers(app)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    """Add a request ID and elapsed-time header, then write a request log entry."""
    request_id = uuid.uuid4().hex[:8]
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.1f}"
    logger.info(
        "[%s] %s %s -> %s (%.1fms)",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.get("/health", tags=["Health"])
def health():
    """Return a lightweight status response for health checks."""
    return {"status": "ok", "version": settings.APP_VERSION}


app.include_router(api_router, prefix=settings.API_V1_PREFIX)
