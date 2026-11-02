from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from wattwise.db.models import Expectation, ExpectationSet, Reading

URL = "/api/v1/models/drift"
WINDOW_START = datetime(2016, 2, 1, tzinfo=UTC)  # a Monday
WINDOW_END = datetime(2016, 2, 29, tzinfo=UTC)
TOO_HIGH, EXACT = "syn-office-a:electricity", "syn-retail-b:electricity"


def readings(engine: Engine) -> pd.DataFrame:
    with Session(engine) as session:
        rows = session.execute(
            select(Reading.meter_id, Reading.timestamp, Reading.value).where(
                Reading.meter_id.in_([TOO_HIGH, EXACT])
            )
        ).all()
    frame = pd.DataFrame(rows, columns=["meter_id", "timestamp", "value"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


@pytest.fixture
def drift(sample_client: TestClient, sample_engine: Engine) -> tuple[TestClient, pd.DataFrame]:
    """Stored expectations for February: TOO_HIGH is expected 10 % above its readings with an
    interval that never contains them; EXACT is expected exactly, inside its interval."""
    frame = readings(sample_engine)
    window = frame[(frame["timestamp"] >= WINDOW_START) & (frame["timestamp"] < WINDOW_END)]
    with Session(sample_engine) as session:
        session.add(
            ExpectationSet(
                dataset_id="synthetic-sample",
                model_version="drift-test",
                interval_nominal=0.9,
                measured_coverage=None,
                window_start=WINDOW_START,
                window_end=WINDOW_END,
                detection_start=WINDOW_START,
                row_count=len(window),
            )
        )
        session.flush()
        meters: list[str] = window["meter_id"].astype(str).tolist()
        stamps: list[datetime] = [t.to_pydatetime() for t in pd.DatetimeIndex(window["timestamp"])]
        values: list[float] = window["value"].fillna(0.0).astype(float).tolist()
        for meter_id, stamp, value in zip(meters, stamps, values, strict=True):
            if meter_id == TOO_HIGH:
                expected, lower, upper = value * 1.1, value * 1.05, value * 1.2
            else:
                expected, lower, upper = value, value - 1.0, value + 1.0
            session.add(
                Expectation(
                    meter_id=meter_id,
                    timestamp=stamp,
                    expected=expected,
                    lower=lower,
                    upper=upper,
                )
            )
        session.commit()
    return sample_client, frame


def get(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_weekly_drift_matches_the_stored_rows(drift: tuple[TestClient, pd.DataFrame]) -> None:
    client, frame = drift
    body = get(client)

    assert body["available"] is True
    assert body["period"] == "week"  # a four-week window
    assert body["model_version"] == "drift-test"
    assert [p["start"][:10] for p in body["periods"]] == [
        "2016-02-01",
        "2016-02-08",
        "2016-02-15",
        "2016-02-22",
    ]
    present = frame.dropna(subset=["value"])
    reference = present[present["timestamp"] < WINDOW_START].groupby("meter_id")["value"].mean()
    first = present[
        (present["timestamp"] >= WINDOW_START)
        & (present["timestamp"] < datetime(2016, 2, 8, tzinfo=UTC))
    ]
    week = body["periods"][0]
    assert week["readings"] == len(first)
    assert week["meters"] == 2
    # TOO_HIGH is never inside its interval, EXACT always is
    inside = (first["meter_id"] == EXACT).sum()
    assert week["coverage"] == pytest.approx(inside / len(first), abs=1e-4)
    errors = (first["meter_id"] == TOO_HIGH) * first["value"].abs() * 0.1
    assert week["wape"] == pytest.approx(errors.sum() / first["value"].abs().sum(), abs=1e-3)
    ratios = first.groupby("meter_id")["value"].mean() / reference
    assert week["median_level_ratio"] == pytest.approx(ratios.median(), abs=1e-3)
    assert week["bias"] > 0  # the model expected more than was used


def test_the_latest_period_ranks_meters_by_level_change(
    drift: tuple[TestClient, pd.DataFrame],
) -> None:
    client, _ = drift
    body = get(client)

    meters = body["meters"]["items"]
    assert body["latest_period"][:10] == "2016-02-22"
    assert {m["meter_id"] for m in meters} == {TOO_HIGH, EXACT}
    changes = [abs(m["level_ratio"] - 1) for m in meters]
    assert changes == sorted(changes, reverse=True)
    by_meter = {m["meter_id"]: m for m in meters}
    assert by_meter[EXACT]["coverage"] == 1.0 and by_meter[EXACT]["wape"] == 0.0
    assert by_meter[TOO_HIGH]["coverage"] == 0.0
    assert by_meter[TOO_HIGH]["wape"] == pytest.approx(0.1, abs=1e-3)
    assert "not failure" in body["note"]


def test_months_can_be_chosen(drift: tuple[TestClient, pd.DataFrame]) -> None:
    client, _ = drift
    body = get(client, period="month")

    assert body["period"] == "month"
    assert [p["start"][:7] for p in body["periods"]] == ["2016-02"]


def test_without_stored_expectations_drift_is_unavailable(sample_client: TestClient) -> None:
    body = get(sample_client)
    assert body["available"] is False and body["datasets"] == []

    named = get(sample_client, dataset_id="synthetic-sample")
    assert named["available"] is False
    assert sample_client.get(URL, params={"dataset_id": "nope"}).status_code == 404
    assert sample_client.get(URL, params={"period": "day"}).status_code == 422
