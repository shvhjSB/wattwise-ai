"""Readiness endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from wattwise.api.dependencies import get_engine
from wattwise.api.schemas.ready import NotReadyResponse, ReadyResponse
from wattwise.db.engine import DatabaseStatus, check_database

router = APIRouter(tags=["health"])


@router.get(
    "/ready",
    summary="Readiness check",
    response_model=ReadyResponse,
    responses={503: {"model": NotReadyResponse, "description": "The database cannot serve."}},
)
def ready(engine: Annotated[Engine | None, Depends(get_engine)]) -> ReadyResponse | JSONResponse:
    """Report whether the API can serve requests that need the database: it is configured,
    reachable and migrated to the head revision.

    Unlike `/health` (liveness), this checks the dependency. A failing check answers 503 and
    names the reason without the connection details."""
    status = check_database(engine)
    if status is DatabaseStatus.OK:
        return ReadyResponse(status="ready", database="ok")
    body = NotReadyResponse.model_validate({"status": "unavailable", "database": status.value})
    return JSONResponse(status_code=503, content=body.model_dump())
