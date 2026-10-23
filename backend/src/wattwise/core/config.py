"""Application settings, loaded from environment variables prefixed with ``WATTWISE_``."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Runtime configuration. Each field can be set with ``WATTWISE_<FIELD_NAME>``."""

    model_config = SettingsConfigDict(env_prefix="WATTWISE_", extra="ignore", frozen=True)

    environment: Environment = "development"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    return Settings()
