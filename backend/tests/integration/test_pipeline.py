"""Synthetic fixture → preparation → model → detection → PostgreSQL → API (T034)."""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect

from tests.conftest import SAMPLE_INFO, SYNTHETIC_SAMPLE
from wattwise.api.main import create_app
from wattwise.core.config import Settings
from wattwise.data.contracts import BUILDINGS, READINGS, WEATHER
from wattwise.db.alerts import load_alerts
from wattwise.db.expectations import compute_expectations, store_expectations
from wattwise.db.load import load_dataset, read_table
from wattwise.db.migrate import current_revision, head_revision, upgrade
from wattwise.ml.detection import Detector, run_detection
from wattwise.ml.explanations import explain
from wattwise.ml.registry import load, promote, read_inputs, save, train
from wattwise.ml.splits import Chronological, SplitConfig

API = "/api/v1"
WINDOW = Chronological(
    train_start=datetime(2016, 1, 4, tzinfo=UTC),
    validation_start=datetime(2016, 1, 25, tzinfo=UTC),
    test_start=datetime(2016, 2, 8, tzinfo=UTC),
    test_end=datetime(2016, 2, 29, tzinfo=UTC),
)


def test_fixture_to_persisted_analysis_and_api(schema_engine: Engine, tmp_path: Path) -> None:
    with schema_engine.begin() as connection:
        assert inspect(connection).get_table_names() == []
        assert current_revision(connection) is None
        upgrade(connection)
        assert current_revision(connection) == head_revision()

    prepared = tmp_path / "prepared"
    prepared.mkdir()
    for contract in (BUILDINGS, READINGS, WEATHER):
        canonical = read_table(SYNTHETIC_SAMPLE, contract)
        canonical.to_parquet(prepared / f"{contract.name}.parquet", index=False)
    readings, buildings, features = read_inputs(prepared, None)
    assert len(readings) == 5376
    assert readings["value"].isna().sum() == 6

    root = tmp_path / "models"
    trained = train(readings, buildings, features, SplitConfig(time=WINDOW))
    version = save(trained, root)
    promote(version, root)
    restored = load(features, root=root)
    assert WINDOW.validation_start is not None
    assert pd.Timestamp(restored.metadata.training.last) < WINDOW.validation_start
    np.testing.assert_allclose(
        restored.model.predict(readings.drop(columns="value"), readings),
        trained.model.predict(readings.drop(columns="value"), readings),
        equal_nan=True,
    )

    detected = run_detection(readings, buildings, features, root)
    assert detected.detector is Detector.ROLLING_Z
    assert detected.detection_window == (WINDOW.test_start, WINDOW.test_end)
    bundles = explain(detected, readings, features, top=0)
    assert bundles
    labels = pd.read_csv(SYNTHETIC_SAMPLE / "anomaly_labels.csv")
    injected = labels[labels["event_id"] == "syn-e2"].iloc[0]
    assert any(
        bundle["event"]["meter_id"] == injected["meter_id"]
        and pd.Timestamp(bundle["event"]["start"]) < pd.Timestamp(injected["end"])
        and pd.Timestamp(bundle["event"]["end"]) > pd.Timestamp(injected["start"])
        for bundle in bundles
    )
    expectation, expectation_info = compute_expectations(prepared, None, None, root)
    assert expectation_info.model_version == version
    assert expectation["lower"].notna().any()

    with schema_engine.begin() as connection:
        loaded = load_dataset(connection, SAMPLE_INFO, buildings, readings)
        alerts = load_alerts(connection, SAMPLE_INFO.dataset_id, bundles)
        stored = store_expectations(
            connection, SAMPLE_INFO.dataset_id, expectation, expectation_info
        )
    assert loaded.readings == len(readings)
    assert alerts.inserted == len(bundles)
    assert stored.rows > 0

    settings = Settings(environment="test", database_url=None, registry_root=root)
    with TestClient(create_app(settings, engine=schema_engine)) as client:
        assert client.get(f"{API}/ready").status_code == 200
        summary = client.get(f"{API}/dashboard/summary").json()
        assert summary["data_kinds"] == ["synthetic"]
        assert summary["readings"] == len(readings)
        assert summary["missing_values"] == 6
        assert summary["by_kind"][0]["alerts"]["alerts"] == len(bundles)
        assert summary["by_kind"][0]["measured_kwh"] == pytest.approx(readings["value"].sum())
        assert client.get(f"{API}/buildings").json()["total"] == len(buildings)
        assert client.get(f"{API}/meters").json()["total"] == readings["meter_id"].nunique()

        metadata = client.get(f"{API}/models/metadata").json()
        assert metadata["version"] == version
        metrics = client.get(f"{API}/models/metrics").json()
        assert {role["role"]: role["metrics"] for role in metrics["roles"]} == trained.metrics

        queue = client.get(
            f"{API}/alerts", params={"dataset_id": SAMPLE_INFO.dataset_id, "limit": 200}
        ).json()
        assert queue["total"] == len(queue["items"]) == len(bundles)
        assert all(item["data_kind"] == "synthetic" for item in queue["items"])
        assert [item["priority_score"] for item in queue["items"]] == sorted(
            (item["priority_score"] for item in queue["items"]), reverse=True
        )
        bundle_by_key = {
            (bundle["event"]["meter_id"], bundle["event"]["start"]): bundle for bundle in bundles
        }
        for item in queue["items"]:
            detail = client.get(f"{API}/alerts/{item['alert_id']}").json()
            bundle = bundle_by_key[(detail["meter_id"], detail["start"])]
            assert detail["evidence"] == bundle
            assert detail["explanation"] == bundle["explanation"]
            assert detail["model_version"] == version

        meter_id = str(injected["meter_id"])
        series = client.get(f"{API}/meters/{meter_id}/expectation", params={"limit": 5000}).json()
        assert series["available"] is True
        assert series["meta"]["model_version"] == version
        assert series["data_kind"] == "synthetic"
        assert series["truncated"] is False
        expected_meter = expectation[
            (expectation["meter_id"] == meter_id)
            & (expectation["timestamp"] >= WINDOW.validation_start)
            & (expectation["timestamp"] < WINDOW.test_end)
        ].sort_values("timestamp")
        assert len(series["points"]) == len(expected_meter)
        for column in ("expected", "lower", "upper"):
            np.testing.assert_allclose(
                [
                    point[column] if point[column] is not None else np.nan
                    for point in series["points"]
                ],
                expected_meter[column].to_numpy(dtype=float),
                rtol=1e-6,
                equal_nan=True,
            )
        assert all(point["timestamp"].endswith("Z") for point in series["points"])

        missing = readings[readings["value"].isna()].iloc[0]
        missing_series = client.get(
            f"{API}/meters/{missing['meter_id']}/series",
            params={
                "start": missing["timestamp"].isoformat(),
                "end": (missing["timestamp"] + pd.Timedelta(hours=1)).isoformat(),
            },
        ).json()
        assert len(missing_series["points"]) == 1
        assert missing_series["points"][0]["value"] is None

        alert_id = queue["items"][0]["alert_id"]
        review = client.post(
            f"{API}/alerts/{alert_id}/feedback",
            json={"label": "needs_investigation", "note": "Synthetic pipeline test"},
        )
        assert review.status_code == 201
        with schema_engine.begin() as connection:
            reloaded = load_alerts(connection, SAMPLE_INFO.dataset_id, bundles)
        assert reloaded.inserted == 0
        assert reloaded.updated == len(bundles)
        reviewed = client.get(f"{API}/alerts/{alert_id}").json()
        assert reviewed["review_status"] == "needs_investigation"
        assert len(reviewed["feedback"]) == 1
        assert reviewed["feedback"][0]["note"] == "Synthetic pipeline test"
        assert client.get(f"{API}/alerts").json()["total"] == len(bundles)
