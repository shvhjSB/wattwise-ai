from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.conftest import SYNTHETIC_SAMPLE
from wattwise.api.main import create_app
from wattwise.api.routes.uploads import safe_filename
from wattwise.core.config import Settings

API = "/api/v1"
LIMIT = 50_000  # bytes, small so the oversize tests stay quick
HISTORY = pd.Timedelta(hours=251)  # the model's lag features need this much history


def sample(name: str) -> bytes:
    return (SYNTHETIC_SAMPLE / f"{name}.csv").read_bytes()


def client_for(root: Path, limit: int = 10_000_000) -> TestClient:
    settings = Settings(
        environment="test", database_url=None, registry_root=root, max_upload_bytes=limit
    )
    return TestClient(create_app(settings))


@pytest.fixture
def client(model_root: Path) -> Iterator[TestClient]:
    with client_for(model_root) as test_client:
        yield test_client


def upload(client: TestClient, content: bytes, table: str = "readings", name: str = "r.csv") -> Any:
    return client.post(
        f"{API}/data/upload", params={"table": table}, files={"file": (name, content, "text/csv")}
    )


# -- upload ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("table", ["readings", "buildings", "weather"])
def test_a_valid_file_returns_its_report(client: TestClient, table: str) -> None:
    response = upload(client, sample(table), table, f"{table}.csv")

    assert response.status_code == 200
    report = response.json()
    assert report["valid"] is True
    assert report["table"] == table
    assert report["errors"] == []
    assert report["stored"] is False
    assert report["row_count"] == len(pd.read_csv(SYNTHETIC_SAMPLE / f"{table}.csv"))


def test_a_malformed_file_returns_a_useful_report(client: TestClient) -> None:
    bad = (
        b"timestamp,meter_id,building_id,meter_type,unit,value\n"
        b"2016-01-01T00:00:00Z,m1,b1,electricity,kWh,41.2\n"
        b"2016-01-01 01:00:00,m1,b1,electricity,kWh,39.8\n"
        b'2016-01-01T02:00:00Z,m1,b1,electricity,kwh,"1,204"\n'
    )

    response = upload(client, bad)

    assert response.status_code == 422
    report = response.json()
    assert report["valid"] is False
    codes = {e["code"] for e in report["errors"]}
    assert {"naive_timestamp", "unknown_unit", "non_numeric_value"} <= codes
    naive = next(e for e in report["errors"] if e["code"] == "naive_timestamp")
    assert naive["rows"] == [2]
    assert "offset" in naive["message"]


@pytest.mark.parametrize(
    "content",
    [
        b"",  # empty
        b"\xff\xfe\x00\x00not utf-8",  # wrong encoding
        b'timestamp,meter_id\n"unclosed,quote\n',  # broken CSV
        b"a,b,c\n1,2,3\n",  # wrong columns
    ],
)
def test_broken_files_are_rejected_with_a_report(client: TestClient, content: bytes) -> None:
    response = upload(client, content)

    assert response.status_code == 422
    assert response.json()["errors"]


def test_an_oversized_file_is_413(model_root: Path) -> None:
    with client_for(model_root, limit=LIMIT) as small:
        response = upload(small, sample("readings"))  # about 430 kB

    assert response.status_code == 413


def test_an_oversized_file_is_413_even_without_a_declared_size(model_root: Path) -> None:
    def chunks() -> Iterator[bytes]:
        boundary = b"--b\r\n"
        yield boundary
        yield b'Content-Disposition: form-data; name="file"; filename="r.csv"\r\n\r\n'
        yield sample("readings")
        yield b"\r\n--b--\r\n"

    with client_for(model_root, limit=LIMIT) as small:
        response = small.post(
            f"{API}/data/upload",
            content=chunks(),
            headers={"content-type": "multipart/form-data; boundary=b"},
        )

    assert response.status_code == 413


def test_an_unknown_table_is_422(client: TestClient) -> None:
    assert upload(client, sample("readings"), table="secrets").status_code == 422


def test_a_missing_file_is_422(client: TestClient) -> None:
    assert client.post(f"{API}/data/upload").status_code == 422


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("readings.csv", "readings.csv"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Windows\\system32\\x.csv", "x.csv"),
        ("my file (1).csv", "my_file__1_.csv"),
        ("..", None),
        ("", None),
        (None, None),
        ("a" * 300 + ".csv", "a" * 100),
    ],
)
def test_file_names_are_reduced_to_a_safe_display_name(
    name: str | None, expected: str | None
) -> None:
    assert safe_filename(name) == expected


def test_the_reported_name_is_safe(client: TestClient) -> None:
    response = upload(client, sample("buildings"), "buildings", "../../secret/buildings.csv")

    assert response.json()["filename"] == "buildings.csv"


# -- analyze --------------------------------------------------------------------------------------


def analyze(client: TestClient, weather: bool = True, **override: bytes) -> Any:
    files = {
        "readings": ("readings.csv", override.get("readings", sample("readings")), "text/csv"),
        "buildings": ("buildings.csv", override.get("buildings", sample("buildings")), "text/csv"),
    }
    if weather:
        files["weather"] = ("weather.csv", sample("weather"), "text/csv")
    return client.post(f"{API}/inference/analyze", files=files)


def test_analysis_returns_predictions_and_alerts(client: TestClient) -> None:
    response = analyze(client)

    assert response.status_code == 200, response.text
    body = response.json()
    readings = pd.read_csv(SYNTHETIC_SAMPLE / "readings.csv")
    assert [m["meter_id"] for m in body["meters"]] == sorted(readings["meter_id"].unique())
    assert sum(len(m["points"]) for m in body["meters"]) == len(readings)
    # The model's lag features need history: no expectation in a meter's first 251 hours, then
    # one for every reading.
    for meter in body["meters"]:
        first = pd.Timestamp(meter["points"][0]["timestamp"])
        later = [p for p in meter["points"] if pd.Timestamp(p["timestamp"]) >= first + HISTORY]
        assert later
        assert all(p["expected"] is not None for p in later)
    assert body["model_version"] is not None
    assert body["detector"] == "rolling-z"
    assert body["data_label"] == "uploaded"
    assert body["stored"] is False and body["retrained"] is False
    assert body["alerts"], "the sample's injected anomalies should raise alerts"
    assert all(a["start"].endswith("Z") for a in body["alerts"])


def test_the_injected_sustained_excess_is_found(client: TestClient) -> None:
    """Of the sample's six injected anomalies, the default detector finds the three-day sustained
    excess; it misses the 2-hour spike, overnight baseload, drift and flatline (D048)."""
    body = analyze(client).json()

    found = [
        a
        for a in body["alerts"]
        if a["meter_id"] == "syn-retail-b:electricity"
        and a["start"] < "2016-02-11T00:00:00Z"
        and a["end"] > "2016-02-08T00:00:00Z"
    ]
    assert [a["signature"] for a in found] == ["sustained"]


def test_observed_values_are_returned_unchanged(client: TestClient) -> None:
    body = analyze(client).json()

    readings = pd.read_csv(SYNTHETIC_SAMPLE / "readings.csv").sort_values(["meter_id", "timestamp"])
    observed = [p["observed"] for m in body["meters"] for p in m["points"]]
    assert observed == [None if pd.isna(v) else v for v in readings["value"]]


def test_analysis_works_without_weather(client: TestClient) -> None:
    assert analyze(client, weather=False).status_code == 200


def test_without_a_model_there_are_alerts_but_no_predictions(tmp_path: Path) -> None:
    with client_for(tmp_path) as no_model:
        body = analyze(no_model).json()

    assert body["model_version"] is None
    assert body["prediction_note"].startswith("No predictions: NoModelError")
    assert all(p["expected"] is None for m in body["meters"] for p in m["points"])
    assert body["alerts"]


def test_an_invalid_file_stops_the_analysis_with_its_report(client: TestClient) -> None:
    response = analyze(client, readings=b"timestamp,meter_id\n2016,x\n")

    assert response.status_code == 422
    reports = response.json()["detail"]
    assert reports[0]["table"] == "readings"
    assert reports[0]["valid"] is False


def test_readings_for_unknown_buildings_are_422(client: TestClient) -> None:
    one_building = b"building_id,site_id,timezone\nsyn-lab-c,syn-site-us,America/New_York\n"

    response = analyze(client, buildings=one_building)

    assert response.status_code == 422
    assert "not in the buildings file" in response.json()["detail"]


def test_too_many_meters_is_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wattwise.api.routes.uploads.MAX_ANALYSIS_METERS", 2)

    assert analyze(client).status_code == 413


def test_the_upload_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths[f"{API}/data/upload"]
    assert "post" in paths[f"{API}/inference/analyze"]
