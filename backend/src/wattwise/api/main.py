"""FastAPI application factory."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from wattwise import __version__
from wattwise.api.routes import alerts, catalog, dashboard, health, ready, uploads
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
    app.add_exception_handler(OperationalError, _database_unavailable)
    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(ready.router, prefix=API_V1_PREFIX)
    app.include_router(catalog.router, prefix=API_V1_PREFIX)
    app.include_router(dashboard.router, prefix=API_V1_PREFIX)
    app.include_router(alerts.router, prefix=API_V1_PREFIX)
    app.include_router(uploads.router, prefix=API_V1_PREFIX)
    return app


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """A lost database answers 503 with the reason only, never the connection details."""
    logger.warning("database unavailable during %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": {"database": "unreachable"}})
