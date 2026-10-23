"""Shared FastAPI dependencies."""

from fastapi import Request

from wattwise.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Return the settings the running application was created with."""
    settings: Settings = request.app.state.settings
    return settings
