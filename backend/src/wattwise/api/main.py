"""FastAPI application factory."""

from fastapi import FastAPI

from wattwise import __version__
from wattwise.api.routes import health
from wattwise.core.config import Settings, get_settings

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application.

    Run locally with ``uvicorn wattwise.api.main:create_app --factory``. Tests pass explicit
    settings so they never depend on the developer's environment.
    """
    app = FastAPI(
        title="WattWise AI API",
        version=__version__,
        description="Explainable energy-waste detection for commercial buildings.",
    )
    app.state.settings = settings or get_settings()
    app.include_router(health.router, prefix=API_V1_PREFIX)
    return app
