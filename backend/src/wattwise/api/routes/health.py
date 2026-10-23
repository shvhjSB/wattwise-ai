"""Liveness endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from wattwise import __version__
from wattwise.api.dependencies import get_app_settings
from wattwise.api.schemas.health import HealthResponse
from wattwise.core.config import Settings

SERVICE_NAME = "wattwise-api"

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
def health(settings: Annotated[Settings, Depends(get_app_settings)]) -> HealthResponse:
    """Report that the API process is running and able to serve requests.

    This is a liveness check only: it does not verify downstream dependencies.
    """
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=__version__,
        environment=settings.environment,
    )
