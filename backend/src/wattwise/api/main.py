"""FastAPI application factory."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from starlette.middleware.cors import CORSMiddleware

from wattwise import __version__
from wattwise.api.public import ReadOnlyMiddleware, SecurityHeadersMiddleware, mount_frontend
from wattwise.api.routes import (
    alerts,
    catalog,
    dashboard,
    health,
    impact,
    models,
    quality,
    ready,
    uploads,
)
from wattwise.api.security import RequestLimitsMiddleware, configure_access_logging
from wattwise.core.config import Settings, get_settings
from wattwise.db.engine import create_db_engine

API_V1_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Build the API application.

    Run locally with ``uvicorn wattwise.api.main:create_app --factory``. Tests pass explicit
    settings so they never depend on the developer's environment. The database engine is built
    from ``settings.database_url`` (it connects lazily); a caller may pass its own `engine`
    instead, and then keeps ownership of it.
    """
    settings = settings or get_settings()
    owned = engine is None and settings.database_url is not None
    if engine is None and settings.database_url is not None:
        engine = create_db_engine(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        if owned and engine is not None:
            engine.dispose()

    app = FastAPI(
        title="WattWise AI API",
        version=__version__,
        description="Explainable energy-waste detection for commercial buildings.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    configure_access_logging()
    app.add_exception_handler(OperationalError, _database_unavailable)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_middleware(
        RequestLimitsMiddleware,
        max_bytes=settings.max_request_bytes,
        timeout_seconds=settings.request_timeout_seconds,
        max_concurrent=settings.max_concurrent_requests,
    )
    if settings.read_only:
        app.add_middleware(ReadOnlyMiddleware)
    if settings.static_dir is not None:
        app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )
    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(ready.router, prefix=API_V1_PREFIX)
    app.include_router(catalog.router, prefix=API_V1_PREFIX)
    app.include_router(dashboard.router, prefix=API_V1_PREFIX)
    app.include_router(alerts.router, prefix=API_V1_PREFIX)
    app.include_router(impact.router, prefix=API_V1_PREFIX)
    app.include_router(uploads.router, prefix=API_V1_PREFIX)
    app.include_router(models.router, prefix=API_V1_PREFIX)
    app.include_router(quality.router, prefix=API_V1_PREFIX)
    if settings.static_dir is not None:
        mount_frontend(app, settings.static_dir)
    return app


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """A lost database answers 503 with the reason only, never the connection details."""
    logger.warning("database unavailable: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": {"database": "unreachable"}})


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """Do not reflect raw submitted values or validator exception messages."""
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content={
            "detail": [{"loc": error["loc"], "type": error["type"]} for error in exc.errors()]
        },
    )
