import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from tests.conftest import SYNTHETIC_SAMPLE
from wattwise.api.main import create_app
from wattwise.core.config import Settings
from wattwise.ml.registry import current

API = "/api/v1"


def app_client(root: Path, engine: Engine | None = None, **settings: Any) -> TestClient:
    config = Settings(environment="test", database_url=None, registry_root=root, **settings)
    return TestClient(create_app(config, engine=engine))


def metadata_file(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (root / current(root) / "metadata.json").read_text(encoding="utf-8")
    )
    return data


def broken_copy(root: Path, target: Path) -> Path:
    shutil.copytree(root, target)
    return target


# -- metadata and metrics -------------------------------------------------------------------------


def test_the_metadata_describes_the_promoted_model(model_root: Path) -> None:
    recorded = metadata_file(model_root)
    with app_client(model_root) as client:
        body = client.get(f"{API}/models/metadata").json()

    assert body["available"] is True
    assert body["version"] == current(model_root)
    assert body["model"]["name"] == recorded["model"]["name"]
    assert body["feature_columns"] == recorded["feature_columns"]
    assert body["training"]["data_fingerprint"] == recorded["training"]["data_fingerprint"]
    assert body["split"]["time"]["kind"] == "chronological"
    assert body["created_at"].endswith("Z")
    assert "inference/analyze" in body["serves"]


def test_the_metrics_are_exactly_the_recorded_ones(model_root: Path) -> None:
    recorded = metadata_file(model_root)
    with app_client(model_root) as client:
        body = client.get(f"{API}/models/metrics").json()

    assert body["available"] is True
    assert body["data_label"] == "observed"
    roles = {r["role"]: r for r in body["roles"]}
    assert set(roles) == {"validation", "test"}
    for role in roles:
        assert roles[role]["metrics"] == recorded["metrics"].get(role)
    time = recorded["training"]["split_config"]["time"]
    assert roles["test"]["window_start"] == time["test_start"]
    assert roles["test"]["window_end"] == time["test_end"]
    assert roles["validation"]["window_end"] == time["test_start"]
    assert set(body["definitions"]) >= {"mae", "rmse", "bias", "wape"}


def test_a_role_that_was_not_recorded_is_null(model_root: Path, tmp_path: Path) -> None:
    root = broken_copy(model_root, tmp_path / "models")
    path = root / current(root) / "metadata.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["metrics"].pop("validation", None)
    path.write_text(json.dumps(data), encoding="utf-8")

    with app_client(root) as client:
        roles = {r["role"]: r for r in client.get(f"{API}/models/metrics").json()["roles"]}

    assert roles["validation"]["metrics"] is None
    assert roles["test"]["metrics"] is not None


@pytest.mark.parametrize("path", ["/models/metadata", "/models/metrics"])
def test_without_a_model_the_answer_is_explicitly_unavailable(tmp_path: Path, path: str) -> None:
    with app_client(tmp_path) as client:
        response = client.get(f"{API}{path}")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "reason": "no_model_promoted",
        "message": "No model has been promoted.",
    }


def test_a_tampered_model_is_unavailable_not_served(model_root: Path, tmp_path: Path) -> None:
    root = broken_copy(model_root, tmp_path / "models")
    with (root / current(root) / "model.txt").open("a", encoding="utf-8") as model:
        model.write("tampered\n")

    with app_client(root) as client:
        body = client.get(f"{API}/models/metadata").json()

    assert body["available"] is False
    assert body["reason"] == "model_invalid"
    assert str(root) not in body["message"]  # no file paths in the answer


def test_an_incompatible_model_is_unavailable(model_root: Path, tmp_path: Path) -> None:
    root = broken_copy(model_root, tmp_path / "models")
    path = root / current(root) / "metadata.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["feature_set_version"] = "999"
    path.write_text(json.dumps(data), encoding="utf-8")

    with app_client(root) as client:
        body = client.get(f"{API}/models/metrics").json()

    assert (body["available"], body["reason"]) == (False, "model_incompatible")


# -- analysis-run records -------------------------------------------------------------------------


def analyze(client: TestClient) -> Any:
    files = {
        name: (f"{name}.csv", (SYNTHETIC_SAMPLE / f"{name}.csv").read_bytes(), "text/csv")
        for name in ("readings", "buildings", "weather")
    }
    response = client.post(f"{API}/inference/analyze", files=files)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def db_client(model_root: Path, migrated_engine: Engine) -> Iterator[TestClient]:
    with app_client(model_root, engine=migrated_engine) as client:
        yield client


def test_every_analysis_is_recorded(db_client: TestClient, model_root: Path) -> None:
    body = analyze(db_client)

    assert body["recorded"] is True
    runs = db_client.get(f"{API}/analysis-runs").json()
    assert runs["total"] == 1
    (run,) = runs["items"]
    assert run["run_id"] == body["run_id"]
    assert run["model_version"] == current(model_root) == body["model_version"]
    assert run["input_start"] == "2016-01-04T00:00:00Z"
    assert run["input_end"] == "2016-02-28T23:00:00Z"
    assert (run["meters"], run["readings"], run["missing_values"]) == (4, 5376, 6)
    assert run["predictions"] == sum(
        p["expected"] is not None for m in body["meters"] for p in m["points"]
    )
    assert run["alerts"] == len(body["alerts"])
    assert run["created_at"].endswith("Z")


def test_runs_are_listed_newest_first_and_filter_by_model(
    db_client: TestClient, model_root: Path
) -> None:
    first, second = analyze(db_client)["run_id"], analyze(db_client)["run_id"]

    runs = db_client.get(f"{API}/analysis-runs").json()
    assert [r["run_id"] for r in runs["items"]] == [second, first]
    version = current(model_root)
    assert (
        db_client.get(f"{API}/analysis-runs", params={"model_version": version}).json()["total"]
        == 2
    )
    assert db_client.get(f"{API}/analysis-runs", params={"model_version": "x"}).json()["total"] == 0


def test_a_run_without_a_model_is_recorded_with_no_version(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    with app_client(tmp_path, engine=migrated_engine) as client:
        body = analyze(client)
        (run,) = client.get(f"{API}/analysis-runs").json()["items"]

    assert body["recorded"] is True
    assert run["model_version"] is None
    assert run["predictions"] == 0


def test_without_a_database_the_analysis_is_unrecorded(model_root: Path) -> None:
    with app_client(model_root) as client:
        body = analyze(client)

    assert (body["recorded"], body["run_id"]) == (False, None)


def test_a_lost_database_does_not_fail_the_analysis(model_root: Path) -> None:
    url = SecretStr("postgresql+psycopg://wattwise:pw@127.0.0.1:1/wattwise")
    config = Settings(environment="test", database_url=url, registry_root=model_root)
    with TestClient(create_app(config)) as client:
        body = analyze(client)

    assert body["recorded"] is False
    assert body["alerts"]


def test_the_run_list_needs_a_database(client: TestClient) -> None:
    assert client.get(f"{API}/analysis-runs").status_code == 503


def test_the_model_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    for path in ("/models/metadata", "/models/metrics", "/analysis-runs"):
        assert "get" in paths[f"{API}{path}"]
