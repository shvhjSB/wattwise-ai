from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from wattwise.core.config import Settings, get_settings


def test_environment_defaults_to_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WATTWISE_ENVIRONMENT", raising=False)

    assert Settings().environment == "development"


def test_environment_variable_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATTWISE_ENVIRONMENT", "production")

    assert Settings().environment == "production"


def test_invalid_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATTWISE_ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_are_immutable() -> None:
    settings = Settings(environment="test")

    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]


def test_get_settings_returns_a_cached_instance() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_the_database_url_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WATTWISE_DATABASE_URL", raising=False)

    assert Settings().database_url is None


def test_the_database_url_is_read_from_the_environment_and_kept_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WATTWISE_DATABASE_URL", "postgresql+psycopg://u:hunter2@db:5432/w")

    settings = Settings()

    assert settings.database_url == SecretStr("postgresql+psycopg://u:hunter2@db:5432/w")
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings)


def test_a_database_url_for_another_driver_is_rejected_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WATTWISE_DATABASE_URL", "mysql://u:hunter2@db/w")

    with pytest.raises(ValidationError, match=r"postgresql\+psycopg") as raised:
        Settings()

    assert "hunter2" not in str(raised.value)


def test_database_url_can_come_from_a_mounted_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WATTWISE_DATABASE_URL", raising=False)
    monkeypatch.setenv("WATTWISE_SECRETS_DIR", str(tmp_path))
    (tmp_path / "WATTWISE_DATABASE_URL").write_text(
        "postgresql+psycopg://u:private-test-value@db/w\n",
        encoding="utf-8",
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.database_url == SecretStr("postgresql+psycopg://u:private-test-value@db/w")
        assert "private-test-value" not in repr(settings)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("existing_directory", [True, False])
def test_configured_missing_secret_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_directory: bool,
) -> None:
    monkeypatch.setenv(
        "WATTWISE_SECRETS_DIR", str(tmp_path if existing_directory else tmp_path / "missing")
    )
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="must contain"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_environment_and_secret_database_urls_cannot_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WATTWISE_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("WATTWISE_DATABASE_URL", "postgresql+psycopg://u:environment-password@db/w")
    (tmp_path / "WATTWISE_DATABASE_URL").write_text("unused-private-value", encoding="utf-8")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="not both") as raised:
            get_settings()
        assert "password" not in str(raised.value)
        assert "unused-private-value" not in str(raised.value)
    finally:
        get_settings.cache_clear()
