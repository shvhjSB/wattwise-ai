"""Application settings, loaded from environment variables prefixed with ``WATTWISE_``."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    #: The largest CSV file the API accepts, in bytes (T026). Larger uploads answer 413.
    max_upload_bytes: int = Field(default=10_000_000, gt=0, le=100_000_000)
    cors_origins: tuple[str, ...] = ()
    max_request_bytes: int = Field(default=32_000_000, gt=0, le=320_000_000)
    request_timeout_seconds: float = Field(default=60, gt=0, le=300, allow_inf_nan=False)
    max_concurrent_requests: int = Field(default=16, gt=0, le=128)
    #: The model registry `/inference/analyze` loads the promoted (`CURRENT`) model from.
    registry_root: Path = Path("../artifacts/models")
    evaluation_root: Path = Path("../data/processed/evaluation/fullscale/test")
    model_data_kind: Literal["observed", "synthetic"] = "observed"
    #: The public demo (T046): refuse every API request that is not GET, HEAD or OPTIONS.
    read_only: bool = False
    #: A built frontend to serve on the same origin as the API (the single-service deployment).
    static_dir: Path | None = None

    @field_validator("cors_origins")
    @classmethod
    def _explicit_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or origin != f"{parsed.scheme}://{parsed.netloc}"
                or "\\" in origin
                or parsed.netloc.endswith(":")
                or "*" in origin
                or any(character.isspace() for character in origin)
            ):
                raise ValueError("cors_origins must contain explicit HTTP(S) origins without paths")
            _ = parsed.port
        return origins

    @field_validator("database_url")
    @classmethod
    def _postgresql_psycopg_only(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(DATABASE_DRIVER_PREFIX):
            raise ValueError(f"database_url must start with {DATABASE_DRIVER_PREFIX}")
        return value

    @model_validator(mode="after")
    def _explicit_model_label_in_production(self) -> "Settings":
        # The label decides whether the model's metrics are presented as real-world (observed) or
        # synthetic results. In production it is never assumed (T053): a synthetic model must not
        # be labelled observed because a deployment forgot to say so.
        if self.environment == "production" and "model_data_kind" not in self.model_fields_set:
            raise ValueError(
                "set WATTWISE_MODEL_DATA_KIND to observed or synthetic explicitly in production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    directory = os.environ.get("WATTWISE_SECRETS_DIR")
    if directory is None:
        return Settings()
    root = Path(directory)
    if not root.is_dir() or not (root / "WATTWISE_DATABASE_URL").is_file():
        raise ValueError("The configured secrets directory must contain WATTWISE_DATABASE_URL")
    if "WATTWISE_DATABASE_URL" in os.environ:
        raise ValueError(
            "Configure the database URL through either environment or secrets, not both"
        )
    return Settings(_secrets_dir=root)
