import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.test_models import app_client, metadata_file


def reports(root: Path, output: Path) -> dict[str, Any]:
    metadata = metadata_file(root)
    metrics = {
        **metadata["metrics"]["test"],
        "missing_actual": 0,
        "total_actual": 1000.0,
        "wape_note": None,
    }
    report = {
        "evaluation_version": "1",
        "forecaster": {
            "name": metadata["model"]["name"],
            "params": {
                **metadata["model"]["settings"],
                "family": metadata["model"]["family"],
                "variant": metadata["model"]["variant"],
            },
        },
        "code": {"package_version": "0.1.0"},
        "data": {
            "fingerprint": metadata["training"]["data_fingerprint"],
            "rows": 100,
            "meters": 2,
            "first": None,
            "last": None,
        },
        "thresholds": {"wape_min_total": 1},
        "split": {"config_sha256": metadata["training"]["split_config_sha256"]},
        "scores": [
            {
                "fold": "chronological",
                "role": "test",
                "unit": "kWh",
                "overall": metrics,
                "macro": {
                    "meters": 2,
                    "mae": 1,
                    "rmse": 2,
                    "bias": 0,
                    "wape": 0.1,
                    "wape_meters": 2,
                },
                "per_meter": [],
                "per_building": [
                    {"building_id": name, "meters": 1, "metrics": metrics}
                    for name in ("Beta", "Alpha")
                ],
            }
        ],
        "fold_summaries": [],
    }
    output.mkdir()
    (output / "chosen.json").write_text(json.dumps(report), encoding="utf-8")
    baseline = {**report, "forecaster": {"name": "seasonal-naive-1w", "params": {}}}
    (output / "seasonal-naive-1w.json").write_text(json.dumps(baseline), encoding="utf-8")
    return report


def test_evaluation_filters_and_paginates_recorded_building_scores(
    model_root: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "reports"
    report = reports(model_root, folder)
    with app_client(model_root, evaluation_root=folder) as client:
        response = client.get("/api/v1/models/evaluation?limit=1&offset=1")
        body = response.json()
        assert response.status_code == 200
        assert body["available"] is True
        assert body["total"] == 2
        assert [item["building_id"] for item in body["buildings"]] == ["Beta"]
        assert body["model_metrics"] == report["scores"][0]["overall"]
        filtered = client.get("/api/v1/models/evaluation?q=ALP").json()
        assert filtered["total"] == 1
        assert filtered["buildings"][0]["building_id"] == "Alpha"
        assert client.get("/api/v1/models/evaluation?offset=-1").status_code == 422


@pytest.mark.parametrize("change", ["fingerprint", "split", "model", "metrics", "invalid"])
def test_evaluation_refuses_stale_or_invalid_reports(
    model_root: Path, tmp_path: Path, change: str
) -> None:
    folder = tmp_path / "reports"
    report = reports(model_root, folder)
    if change == "fingerprint":
        report["data"]["fingerprint"] = "another dataset"
    elif change == "split":
        report["split"]["config_sha256"] = "another split"
    elif change == "model":
        report["forecaster"]["params"]["family"] = "another model"
    elif change == "metrics":
        report["scores"][0]["overall"]["mae"] = 123456
    (folder / "chosen.json").write_text(
        "broken" if change == "invalid" else json.dumps(report), encoding="utf-8"
    )
    with app_client(model_root, evaluation_root=folder) as client:
        body = client.get("/api/v1/models/evaluation").json()
    assert body["available"] is False
    assert body["buildings"] == []
    assert body["baseline_metrics"] is None
    assert str(folder) not in body["message"]


def test_missing_reports_are_explicit(model_root: Path, tmp_path: Path) -> None:
    with app_client(model_root, evaluation_root=tmp_path) as client:
        body = client.get("/api/v1/models/evaluation").json()
    assert body["available"] is False
    assert "unavailable" in body["message"]


def test_evaluation_is_documented_without_a_database(client: TestClient) -> None:
    assert "/api/v1/models/evaluation" in client.get("/openapi.json").json()["paths"]
