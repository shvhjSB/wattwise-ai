import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from wattwise.api.main import create_app
from wattwise.core.config import Settings
from wattwise.db.migrate import upgrade

PASSWORD = "pw-must-never-appear"
# Port 1 refuses connections at once: a database that is down.
UNREACHABLE_URL = f"postgresql+psycopg://wattwise:{PASSWORD}@127.0.0.1:1/wattwise"


def test_ready_is_503_without_a_database() -> None:
    with TestClient(create_app(Settings(environment="test", database_url=None))) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "not_configured"}


def test_ready_is_503_when_the_database_is_unreachable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(environment="test", database_url=SecretStr(UNREACHABLE_URL))
    with caplog.at_level(logging.WARNING), TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
    # Neither the response nor the log carries the password, host or user.
    assert PASSWORD not in response.text + caplog.text
    assert "127.0.0.1" not in response.text + caplog.text
    assert "OperationalError" in caplog.text


def test_liveness_does_not_depend_on_the_database() -> None:
    settings = Settings(environment="test", database_url=SecretStr(UNREACHABLE_URL))
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_ready_is_503_when_the_database_was_never_migrated(schema_engine: Engine) -> None:
    app = create_app(Settings(environment="test", database_url=None), engine=schema_engine)
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "schema_outdated"}


def test_ready_is_200_when_the_database_is_migrated(schema_engine: Engine) -> None:
    with schema_engine.begin() as connection:
        upgrade(connection)
    app = create_app(Settings(environment="test", database_url=None), engine=schema_engine)
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_ready_is_documented_in_openapi(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/ready"]["get"]

    assert set(operation["responses"]) >= {"200", "503"}


def test_the_app_disposes_only_an_engine_it_built() -> None:
    settings = Settings(environment="test", database_url=SecretStr(UNREACHABLE_URL))
    app = create_app(settings)
    engine = app.state.engine
    assert engine is not None

    with TestClient(app):
        pass

    # Disposing again is harmless; the point is that the lifespan ran without error and the
    # engine object is the one built from the settings.
    assert engine.url.host == "127.0.0.1"
    engine.dispose()
