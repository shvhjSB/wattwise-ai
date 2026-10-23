import pytest
from pydantic import ValidationError

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
