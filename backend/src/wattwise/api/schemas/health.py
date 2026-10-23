"""Schemas for the health endpoint."""

from typing import Literal

from pydantic import BaseModel, Field

from wattwise.core.config import Environment


class HealthResponse(BaseModel):
    """Liveness status of the API process."""

    status: Literal["ok"] = Field(description="Always 'ok' when the process can serve requests.")
    service: str = Field(description="Service identifier.")
    version: str = Field(description="Installed wattwise package version.")
    environment: Environment = Field(description="Deployment environment (WATTWISE_ENVIRONMENT).")
