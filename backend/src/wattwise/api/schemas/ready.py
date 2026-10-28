"""Schemas for the readiness endpoint."""

from typing import Literal

from pydantic import BaseModel, Field


class ReadyResponse(BaseModel):
    """The API can serve requests that need the database."""

    status: Literal["ready"] = Field(description="Always 'ready' on a 200 response.")
    database: Literal["ok"] = Field(description="Reachable, and migrated to the head revision.")


class NotReadyResponse(BaseModel):
    """The API is running but cannot serve requests that need the database."""

    status: Literal["unavailable"] = Field(description="Always 'unavailable' on a 503 response.")
    database: Literal["not_configured", "unreachable", "schema_outdated"] = Field(
        description="Why: no database URL is set, it cannot be reached, or it is not migrated."
    )
