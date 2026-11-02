from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.conftest import SYNTHETIC_SAMPLE
from wattwise.api.main import create_app
from wattwise.core.config import Settings
from wattwise.db.migrate import downgrade
from wattwise.demo import build_artifacts, initialize_demo
from wattwise.ml.registry import versions


def test_demo_restart_preserves_model_readings_and_feedback(
    schema_engine: Engine, tmp_path: Path
) -> None:
    first = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)
    assert first.seeded is True
    assert first.readings == 5376 and first.alerts > 0
    settings = Settings(
        environment="test",
        database_url=None,
        registry_root=tmp_path / "models",
        evaluation_root=tmp_path / "evaluation",
        model_data_kind="synthetic",
    )
    with TestClient(create_app(settings, engine=schema_engine)) as client:
        alert_id = client.get("/api/v1/alerts").json()["items"][0]["alert_id"]
        response = client.post(
            f"/api/v1/alerts/{alert_id}/feedback",
            json={"label": "needs_investigation", "note": "Keep this review across demo restarts"},
        )
        assert response.status_code == 201
        again = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)
        assert again.seeded is False
        assert again.model_version == first.model_version
        assert again.readings == first.readings and again.alerts == first.alerts
        assert versions(tmp_path / "models") == [first.model_version]
        detail = client.get(f"/api/v1/alerts/{alert_id}").json()
        assert detail["feedback"][0]["note"] == "Keep this review across demo restarts"
        assert client.get("/api/v1/models/evaluation").json()["available"] is True
        assert client.get("/api/v1/models/metrics").json()["data_label"] == "synthetic"


def test_demo_refuses_mismatched_artifacts_without_deleting_data(
    schema_engine: Engine, tmp_path: Path
) -> None:
    first = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)
    (tmp_path / "demo.json").rename(tmp_path / "saved-demo.json")
    with pytest.raises(ValueError, match="artifact checkpoint"):
        initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)
    settings = Settings(environment="test", database_url=None)
    with TestClient(create_app(settings, engine=schema_engine)) as client:
        assert client.get("/api/v1/dashboard/summary").json()["readings"] == first.readings


def test_demo_can_restore_a_fresh_database_from_its_existing_model(
    schema_engine: Engine, tmp_path: Path
) -> None:
    first = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)
    with schema_engine.begin() as connection:
        downgrade(connection)
    restored = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)
    assert restored.seeded is True
    assert restored.model_version == first.model_version
    assert restored.readings == first.readings
    assert versions(tmp_path / "models") == [first.model_version]


def test_a_model_built_without_a_database_seeds_it_without_training(
    schema_engine: Engine, tmp_path: Path
) -> None:
    checkpoint = build_artifacts(SYNTHETIC_SAMPLE, tmp_path)
    assert (tmp_path / "evaluation" / "chosen.json").exists()  # baked into the image (T046)

    seeded = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path)

    assert seeded.seeded is True
    assert seeded.model_version == checkpoint.model_version
    assert versions(tmp_path / "models") == [checkpoint.model_version]
    assert build_artifacts(SYNTHETIC_SAMPLE, tmp_path) == checkpoint  # kept, not retrained


def test_the_public_demo_replaces_a_demo_made_with_another_model(
    schema_engine: Engine, tmp_path: Path
) -> None:
    old = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path / "old")
    new = build_artifacts(SYNTHETIC_SAMPLE, tmp_path / "new")
    assert new.model_version != old.model_version

    kept = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path / "new")
    assert kept.seeded is False  # without the flag, existing data is never replaced

    replaced = initialize_demo(
        schema_engine, SYNTHETIC_SAMPLE, tmp_path / "new", replace_stale=True
    )
    assert replaced.seeded is True
    assert replaced.model_version == new.model_version
    again = initialize_demo(schema_engine, SYNTHETIC_SAMPLE, tmp_path / "new", replace_stale=True)
    assert again.seeded is False  # up to date: a restart changes nothing
