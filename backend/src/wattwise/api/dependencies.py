"""Shared FastAPI dependencies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from wattwise.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Return the settings the running application was created with."""
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine | None:
    """Return the application's database engine, or None when no database is configured."""
    engine: Engine | None = request.app.state.engine
    return engine


def get_session(engine: Annotated[Engine | None, Depends(get_engine)]) -> Iterator[Session]:
    """A database session for one request; 503 when no database is configured."""
    if engine is None:
        raise HTTPException(status_code=503, detail={"database": "not_configured"})
    with Session(engine) as session:
        yield session
