"""Shared FastAPI dependencies."""

from fastapi import Request
from sqlalchemy import Engine

from wattwise.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Return the settings the running application was created with."""
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine | None:
    """Return the application's database engine, or None when no database is configured."""
    engine: Engine | None = request.app.state.engine
    return engine
