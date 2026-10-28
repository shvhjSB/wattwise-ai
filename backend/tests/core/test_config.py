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
