"""Application settings, loaded from environment variables prefixed with ``WATTWISE_``."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]

DATABASE_DRIVER_PREFIX = "postgresql+psycopg://"


class Settings(BaseSettings):
    """Runtime configuration. Each field can be set with ``WATTWISE_<FIELD_NAME>``."""

    # hide_input_in_errors: a rejected database URL carries a password and must not be echoed.
    model_config = SettingsConfigDict(
        env_prefix="WATTWISE_", extra="ignore", frozen=True, hide_input_in_errors=True
    )

    environment: Environment = "development"
    #: ``postgresql+psycopg://user:password@host:port/database``. Unset means no database:
    #: the API still serves liveness, and ``/ready`` reports "not_configured".
    database_url: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _postgresql_psycopg_only(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(DATABASE_DRIVER_PREFIX):
            raise ValueError(f"database_url must start with {DATABASE_DRIVER_PREFIX}")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    return Settings()
