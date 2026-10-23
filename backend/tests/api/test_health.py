from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient

from wattwise import __version__
from wattwise.api.main import create_app
from wattwise.core.config import get_settings


def test_health_reports_liveness(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "wattwise-api",
        "version": __version__,
        "environment": "test",
    }


def test_reported_version_is_the_installed_package_version() -> None:
    assert __version__ == version("wattwise")


def test_health_is_documented_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/health" in schema["paths"]
    assert schema["info"]["version"] == __version__


def test_unknown_route_returns_json_404(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_app_reads_settings_from_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATTWISE_ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/health")
    finally:
        get_settings.cache_clear()

    assert response.json()["environment"] == "production"
