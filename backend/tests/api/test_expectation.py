from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from wattwise.db.models import Expectation, ExpectationSet

API = "/api/v1"
METER = "syn-office-a:electricity"
START = datetime(2016, 1, 20, tzinfo=UTC)
HOURS = 96
FIRST_INTERVAL = START + timedelta(hours=24)  # the first day has an expectation but no interval


def expected_at(hour: int) -> float:
    return 100.0 + hour


@pytest.fixture
def expectation_client(sample_client: TestClient, sample_engine: Engine) -> TestClient:
    """The synthetic sample with stored expectations for one meter over four days."""
    with Session(sample_engine) as session:
        session.add(
            ExpectationSet(
                dataset_id="synthetic-sample",
                model_version="test-model",
                interval_nominal=0.9,
                measured_coverage=0.88,
                window_start=START,
                window_end=START + timedelta(hours=HOURS),
                detection_start=START + timedelta(hours=48),
                row_count=HOURS,
            )
        )
        session.flush()
        for hour in range(HOURS):
            has_interval = hour >= 24
            session.add(
                Expectation(
                    meter_id=METER,
                    timestamp=START + timedelta(hours=hour),
                    expected=expected_at(hour),
                    lower=expected_at(hour) - 10 if has_interval else None,
                    upper=expected_at(hour) + 10 if has_interval else None,
                )
            )
        session.commit()
    return sample_client


def get(client: TestClient, meter: str = METER, **params: Any) -> dict[str, Any]:
    response = client.get(f"{API}/meters/{meter}/expectation", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_readings_come_with_the_expectation_and_interval(expectation_client: TestClient) -> None:
    body = get(expectation_client, start="2016-01-20T00:00:00Z", end="2016-01-21T12:00:00Z")

    assert body["available"] is True
    assert (body["unit"], body["data_kind"]) == ("kWh", "synthetic")
    assert len(body["points"]) == 36
    first, later = body["points"][0], body["points"][30]
    assert first["timestamp"] == "2016-01-20T00:00:00Z"
    assert first["observed"] is not None  # the reading itself
    assert (first["expected"], first["lower"], first["upper"]) == (100.0, None, None)
    assert (later["expected"], later["lower"], later["upper"]) == (130.0, 120.0, 140.0)


def test_the_meta_says_what_produced_it_and_where_the_interval_begins(
    expectation_client: TestClient,
) -> None:
    meta = get(expectation_client)["meta"]

    assert meta["model_version"] == "test-model"
    assert meta["interval_nominal"] == 0.9
    assert meta["measured_coverage"] == 0.88
    assert meta["window_start"] == "2016-01-20T00:00:00Z"
    assert meta["window_end"] == "2016-01-24T00:00:00Z"
    assert meta["detection_start"] == "2016-01-22T00:00:00Z"
    assert (
        meta["first_interval"] == "2016-01-21T00:00:00Z" == f"{FIRST_INTERVAL:%Y-%m-%dT%H:%M:%SZ}"
    )


def test_without_a_range_the_whole_window_is_returned(expectation_client: TestClient) -> None:
    body = get(expectation_client)

    assert len(body["points"]) == HOURS
    assert body["truncated"] is False


def test_the_range_is_clipped_to_the_window(expectation_client: TestClient) -> None:
    body = get(expectation_client, start="2016-01-01T00:00:00Z", end="2016-02-20T00:00:00Z")

    assert len(body["points"]) == HOURS
    assert body["points"][0]["timestamp"] == "2016-01-20T00:00:00Z"
    assert body["points"][-1]["timestamp"] == "2016-01-23T23:00:00Z"


def test_a_range_outside_the_window_is_unavailable_with_the_window(
    expectation_client: TestClient,
) -> None:
    body = get(expectation_client, start="2016-02-01T00:00:00Z", end="2016-02-05T00:00:00Z")

    assert body["available"] is False
    assert body["reason"] == "outside_evaluation_window"
    assert "2016-01-20" in body["message"]
    assert body["points"] == []
    assert body["meta"]["window_start"] == "2016-01-20T00:00:00Z"


def test_a_meter_with_no_stored_expectation_has_readings_but_no_expectation(
    expectation_client: TestClient,
) -> None:
    body = get(expectation_client, meter="syn-lab-c:electricity")

    assert body["available"] is True  # the dataset has an expectation set
    assert all(p["expected"] is None for p in body["points"])
    assert body["meta"]["first_interval"] is None
    assert len(body["points"]) == HOURS


def test_a_dataset_without_expectations_says_so(sample_client: TestClient) -> None:
    body = get(sample_client)

    assert body["available"] is False
    assert body["reason"] == "no_expectation_stored"
    assert body["points"] == [] and body["meta"] is None
    assert "No model expectation" in body["message"]


def test_missing_readings_stay_null_while_the_expectation_remains(
    expectation_client: TestClient, sample_engine: Engine
) -> None:
    from sqlalchemy import update

    from wattwise.db.models import Reading

    gap = START + timedelta(hours=5)
    with sample_engine.begin() as connection:
        connection.execute(
            update(Reading)
            .where(Reading.meter_id == METER, Reading.timestamp == gap)
            .values(value=None)
        )

    point = get(expectation_client, start="2016-01-20T05:00:00Z", end="2016-01-20T06:00:00Z")[
        "points"
    ][0]

    assert point["observed"] is None  # not measured: never zero
    assert point["expected"] == 105.0


def test_the_series_is_truncated_at_the_limit_and_says_so(expectation_client: TestClient) -> None:
    body = get(expectation_client, limit=10)

    assert len(body["points"]) == 10
    assert body["truncated"] is True


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2016-01-20T00:00:00"},
        {"start": "2016-01-21T00:00:00Z", "end": "2016-01-20T00:00:00Z"},
        {"limit": 0},
    ],
)
def test_bad_requests_are_validation_errors(
    expectation_client: TestClient, params: dict[str, str]
) -> None:
    response = expectation_client.get(f"{API}/meters/{METER}/expectation", params=params)

    assert response.status_code == 422


def test_an_unknown_meter_is_404(expectation_client: TestClient) -> None:
    assert expectation_client.get(f"{API}/meters/nope/expectation").status_code == 404


def test_caveats_come_with_the_answer(expectation_client: TestClient) -> None:
    caveats = get(expectation_client)["caveats"]

    assert any("not a target" in c for c in caveats)
    assert any("not confirmed waste" in c for c in caveats)


def test_the_endpoint_needs_a_database(client: TestClient) -> None:
    assert client.get(f"{API}/meters/x/expectation").status_code == 503


# -- building search -----------------------------------------------------------------------------


def ids(client: TestClient, **params: str) -> list[str]:
    body = client.get(f"{API}/buildings", params=params).json()
    return [b["building_id"] for b in body["items"]]


def test_buildings_are_found_by_part_of_their_id(sample_client: TestClient) -> None:
    assert ids(sample_client, q="office") == ["syn-office-a", "syn-office-d"]
    assert ids(sample_client, q="OFFICE") == ["syn-office-a", "syn-office-d"]  # any case


def test_buildings_are_found_by_primary_use(sample_client: TestClient) -> None:
    assert ids(sample_client, q="Laborat") == ["syn-lab-c"]


def test_search_wildcards_are_taken_literally(sample_client: TestClient) -> None:
    assert ids(sample_client, q="%") == []
    assert ids(sample_client, q="_") == []
    assert ids(sample_client, q="syn_lab") == []  # an underscore is not "any character"
    assert ids(sample_client, q="syn-lab") == ["syn-lab-c"]


def test_search_combines_with_the_other_filters(sample_client: TestClient) -> None:
    assert ids(sample_client, q="office", site_id="syn-site-uk") == ["syn-office-a"]


def test_the_search_text_is_limited(sample_client: TestClient) -> None:
    assert sample_client.get(f"{API}/buildings", params={"q": "x" * 101}).status_code == 422
