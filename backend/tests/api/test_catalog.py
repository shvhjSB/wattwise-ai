from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.conftest import SAMPLE_INFO, SYNTHETIC_SAMPLE
from wattwise.data.contracts import READINGS
from wattwise.db.load import read_table

API = "/api/v1"


@pytest.fixture(scope="module")
def readings() -> pd.DataFrame:
    return read_table(SYNTHETIC_SAMPLE, READINGS)


def ids(page: dict[str, Any], key: str) -> list[str]:
    return [item[key] for item in page["items"]]


# -- buildings ------------------------------------------------------------------------------------


def test_buildings_are_listed_in_order_with_their_label(sample_client: TestClient) -> None:
    page = sample_client.get(f"{API}/buildings").json()

    assert page["total"] == 4
    assert ids(page, "building_id") == [
        "syn-lab-c",
        "syn-office-a",
        "syn-office-d",
        "syn-retail-b",
    ]
    first = page["items"][0]
    assert first["data_kind"] == "synthetic"
    assert first["dataset_id"] == SAMPLE_INFO.dataset_id
    assert first["meter_count"] == 1
    assert first["latitude"] is None  # never invented


def test_buildings_filter_by_site(sample_client: TestClient) -> None:
    page = sample_client.get(f"{API}/buildings", params={"site_id": "syn-site-uk"}).json()

    assert ids(page, "building_id") == ["syn-office-a", "syn-retail-b"]
    assert page["total"] == 2


def test_buildings_paginate(sample_client: TestClient) -> None:
    first = sample_client.get(f"{API}/buildings", params={"limit": 3, "offset": 0}).json()
    second = sample_client.get(f"{API}/buildings", params={"limit": 3, "offset": 3}).json()

    assert len(first["items"]) == 3
    assert ids(second, "building_id") == ["syn-retail-b"]
    assert first["total"] == second["total"] == 4
    assert (first["limit"], first["offset"]) == (3, 0)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_bad_pagination_is_a_validation_error(
    sample_client: TestClient, params: dict[str, int]
) -> None:
    assert sample_client.get(f"{API}/buildings", params=params).status_code == 422


def test_one_building_and_a_missing_one(sample_client: TestClient) -> None:
    found = sample_client.get(f"{API}/buildings/syn-office-a")
    missing = sample_client.get(f"{API}/buildings/nope")

    assert found.status_code == 200
    assert found.json()["timezone"] == "Europe/London"
    assert missing.status_code == 404


# -- meters ---------------------------------------------------------------------------------------


def test_meters_filter_by_building_and_type(sample_client: TestClient) -> None:
    by_building = sample_client.get(f"{API}/meters", params={"building_id": "syn-lab-c"}).json()
    electricity = sample_client.get(f"{API}/meters", params={"meter_type": "electricity"}).json()
    gas = sample_client.get(f"{API}/meters", params={"meter_type": "gas"}).json()

    assert ids(by_building, "meter_id") == ["syn-lab-c:electricity"]
    assert electricity["total"] == 4
    assert gas == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_an_unknown_meter_type_is_a_validation_error(sample_client: TestClient) -> None:
    assert sample_client.get(f"{API}/meters", params={"meter_type": "plutonium"}).status_code == 422


def test_one_meter_and_a_missing_one(sample_client: TestClient) -> None:
    meter = sample_client.get(f"{API}/meters/syn-lab-c:electricity").json()

    assert meter["unit"] == "kWh"
    assert meter["data_kind"] == "synthetic"
    assert sample_client.get(f"{API}/meters/nope").status_code == 404


# -- series ---------------------------------------------------------------------------------------


def test_a_series_in_a_range_equals_the_source(
    sample_client: TestClient, readings: pd.DataFrame
) -> None:
    meter = "syn-office-a:electricity"
    params = {"start": "2016-01-20T00:00:00Z", "end": "2016-01-21T00:00:00+00:00"}

    series = sample_client.get(f"{API}/meters/{meter}/series", params=params).json()

    source = readings[
        (readings["meter_id"] == meter)
        & (readings["timestamp"] >= pd.Timestamp("2016-01-20", tz="UTC"))
        & (readings["timestamp"] < pd.Timestamp("2016-01-21", tz="UTC"))
    ]
    assert len(series["points"]) == len(source) == 24
    assert [pd.Timestamp(p["timestamp"]) for p in series["points"]] == list(source["timestamp"])
    assert [p["value"] for p in series["points"]] == pytest.approx(source["value"].tolist())
    assert series["truncated"] is False
    assert series["unit"] == "kWh"
    assert series["data_kind"] == "synthetic"


def test_an_offset_is_honoured(sample_client: TestClient) -> None:
    meter = "syn-office-a:electricity"
    utc = sample_client.get(
        f"{API}/meters/{meter}/series",
        params={"start": "2016-01-20T00:00:00Z", "end": "2016-01-20T03:00:00Z"},
    ).json()
    shifted = sample_client.get(
        f"{API}/meters/{meter}/series",
        params={"start": "2016-01-20T01:00:00+01:00", "end": "2016-01-20T04:00:00+01:00"},
    ).json()

    assert utc["points"] == shifted["points"]
    assert len(utc["points"]) == 3
    # Returned in UTC, though the test session's time zone is Asia/Kolkata and the request's +01:00.
    assert shifted["start"] == "2016-01-20T00:00:00Z"
    assert [p["timestamp"] for p in shifted["points"]] == [
        "2016-01-20T00:00:00Z",
        "2016-01-20T01:00:00Z",
        "2016-01-20T02:00:00Z",
    ]


def test_missing_readings_come_back_as_null_not_zero(
    sample_client: TestClient, readings: pd.DataFrame
) -> None:
    gaps = readings[readings["value"].isna()]
    if gaps.empty:
        pytest.skip("the sample has no missing readings")
    gap = gaps.iloc[0]
    hour = gap["timestamp"]

    series = sample_client.get(
        f"{API}/meters/{gap['meter_id']}/series",
        params={
            "start": hour.isoformat(),
            "end": (hour + pd.Timedelta(hours=1)).isoformat(),
        },
    ).json()

    assert series["points"] == [{"timestamp": series["points"][0]["timestamp"], "value": None}]


def test_a_series_is_truncated_at_the_limit_and_says_so(sample_client: TestClient) -> None:
    series = sample_client.get(
        f"{API}/meters/syn-lab-c:electricity/series", params={"limit": 10}
    ).json()

    assert len(series["points"]) == 10
    assert series["truncated"] is True
    assert series["start"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2016-01-20T00:00:00"},  # no time zone
        {"start": "2016-01-21T00:00:00Z", "end": "2016-01-20T00:00:00Z"},  # start after end
        {"start": "2016-01-20T00:00:00Z", "end": "2016-01-20T00:00:00Z"},  # empty range
        {"start": "yesterday"},
        {"limit": 0},
        {"limit": 50_001},
    ],
)
def test_bad_series_requests_are_validation_errors(
    sample_client: TestClient, params: dict[str, Any]
) -> None:
    response = sample_client.get(f"{API}/meters/syn-lab-c:electricity/series", params=params)

    assert response.status_code == 422


def test_the_series_of_a_missing_meter_is_404(sample_client: TestClient) -> None:
    assert sample_client.get(f"{API}/meters/nope/series").status_code == 404


# -- dashboard summary ----------------------------------------------------------------------------


def test_the_summary_counts_what_is_stored(
    sample_client: TestClient, readings: pd.DataFrame
) -> None:
    summary = sample_client.get(f"{API}/dashboard/summary").json()

    assert summary["data_kinds"] == ["synthetic"]
    assert summary["buildings"] == 4
    assert summary["meters"] == 4
    assert summary["meters_by_type"] == {"electricity": 4}
    assert summary["readings"] == len(readings)
    assert summary["missing_values"] == int(readings["value"].isna().sum())
    assert pd.Timestamp(summary["first_reading"]) == readings["timestamp"].min()
    assert summary["first_reading"] == "2016-01-04T00:00:00Z"
    assert pd.Timestamp(summary["last_reading"]) == readings["timestamp"].max()
    (dataset,) = summary["datasets"]
    assert dataset["dataset_id"] == SAMPLE_INFO.dataset_id
    assert dataset["kind"] == "synthetic"
    assert dataset["readings"] == len(readings)
    kwh = readings["value"].sum()  # all four sample meters are kWh meters
    assert dataset["measured_kwh"] == pytest.approx(kwh)
    (kind,) = summary["by_kind"]
    assert kind["kind"] == "synthetic"
    assert kind["measured_kwh"] == pytest.approx(kwh)
    assert kind["missing_share"] == pytest.approx(6 / len(readings))
    assert kind["alerts"]["alerts"] == 0  # no alerts loaded


def test_the_summary_never_scans_the_readings(
    sample_client: TestClient, sample_engine: Engine
) -> None:
    """At 20 million readings an aggregate took 11 s per request, on every page. The totals are
    stored when a dataset is loaded; the summary must work with the readings gone."""
    from sqlalchemy import text

    with sample_engine.begin() as connection:
        connection.execute(text("TRUNCATE readings"))

    summary = sample_client.get(f"{API}/dashboard/summary").json()

    assert summary["readings"] == 5376  # from the stored totals, not from the table


def test_the_summary_of_an_empty_database(migrated_client: TestClient) -> None:
    summary = migrated_client.get(f"{API}/dashboard/summary").json()

    assert summary == {
        "datasets": [],
        "data_kinds": [],
        "by_kind": [],
        "buildings": 0,
        "meters": 0,
        "meters_by_type": {},
        "readings": 0,
        "missing_values": 0,
        "first_reading": None,
        "last_reading": None,
    }


# -- without a database ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/buildings",
        "/buildings/x",
        "/meters",
        "/meters/x",
        "/meters/x/series",
        "/dashboard/summary",
    ],
)
def test_every_data_endpoint_is_503_without_a_database(client: TestClient, path: str) -> None:
    response = client.get(f"{API}{path}")

    assert response.status_code == 503
    assert response.json() == {"detail": {"database": "not_configured"}}


def test_a_lost_database_is_503_without_details() -> None:
    from pydantic import SecretStr

    from wattwise.api.main import create_app
    from wattwise.core.config import Settings

    url = "postgresql+psycopg://wattwise:pw-secret@127.0.0.1:1/wattwise"
    app = create_app(Settings(environment="test", database_url=SecretStr(url)))
    with TestClient(app) as lost:
        response = lost.get(f"{API}/buildings")

    assert response.status_code == 503
    assert response.json() == {"detail": {"database": "unreachable"}}
    assert "pw-secret" not in response.text


def test_the_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    for path in [
        "/buildings",
        "/buildings/{building_id}",
        "/meters",
        "/meters/{meter_id}",
        "/meters/{meter_id}/series",
        "/dashboard/summary",
    ]:
        assert f"{API}{path}" in paths
