"""T066: GET /api/v1/buildings/{id}/machines over a real (test) database."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.factory_data import (
    BUILDING,
    FACTORY_INFO,
    MAIN,
    PRESS,
    PUMP,
    WATER,
    factory_tables,
)
from wattwise.api.main import create_app
from wattwise.core.config import Settings
from wattwise.data.contracts import BUILDINGS, READINGS
from wattwise.data.validation import to_canonical
from wattwise.db.load import load_dataset

API = "/api/v1"


@pytest.fixture
def factory_client(sample_engine: Engine) -> Iterator[TestClient]:
    buildings, readings = factory_tables()
    with sample_engine.begin() as connection:
        load_dataset(
            connection,
            FACTORY_INFO,
            to_canonical(buildings, BUILDINGS),
            to_canonical(readings, READINGS),
        )
    app = create_app(Settings(environment="test", database_url=None), engine=sample_engine)
    with TestClient(app) as client:
        yield client


def machines(client: TestClient, building: str = BUILDING, **params: str) -> dict[str, object]:
    response = client.get(f"{API}/buildings/{building}/machines", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def test_a_building_s_meters_are_compared_against_its_main_meter(
    factory_client: TestClient,
) -> None:
    body = machines(factory_client)

    assert body["available"] is True and body["data_kind"] == "synthetic"
    assert body["dataset_name"] == FACTORY_INFO.name and body["timezone"] == "Europe/Berlin"
    assert (body["open_days"], body["open_from"], body["open_to"]) == ([0, 1, 2, 3, 4], 6, 18)
    main = body["main"]
    assert isinstance(main, dict)
    assert main["meter_id"] == MAIN and main["chosen"] is False
    assert main["energy_kwh"] == 24784.0 and main["closed_kwh"] == 13904.0
    rows = body["machines"]
    assert isinstance(rows, list)
    assert [r["meter_id"] for r in rows] == [PRESS, PUMP]
    press = rows[0]
    assert press["energy_kwh"] == 3280.0 and press["running_hours"] == 164
    assert press["closed_kwh"] == 80.0 and press["events"] == 1
    assert press["share_of_main"] == pytest.approx(3280 / 24784)
    assert body["unmetered_kwh"] == pytest.approx(20160.0)
    assert body["not_compared"] == [WATER]  # water is not electricity
    assert body["first_reading"] == "2016-10-03T00:00:00Z"  # UTC, whatever the session zone
    caveats = " ".join(str(c) for c in body["caveats"])  # type: ignore[attr-defined]
    assert "not confirmed waste" in caveats and "cannot be split" in caveats


def test_the_main_meter_and_opening_hours_can_be_chosen(factory_client: TestClient) -> None:
    body = machines(
        factory_client, main_meter_id=PRESS, open_days="0,1,2,3,4,5,6", open_from="0", open_to="24"
    )

    main = body["main"]
    assert isinstance(main, dict)
    assert main["meter_id"] == PRESS and main["chosen"] is True
    assert main["closed_kwh"] == 0.0  # always open: nothing is used while closed


@pytest.mark.parametrize(
    "params",
    [
        {"main_meter_id": WATER},  # not electricity
        {"main_meter_id": "elsewhere"},
        {"open_days": "7"},
        {"open_days": "mon"},
        {"open_from": "18", "open_to": "6"},
        {"open_to": "25"},
    ],
)
def test_bad_input_is_refused(factory_client: TestClient, params: dict[str, str]) -> None:
    response = factory_client.get(f"{API}/buildings/{BUILDING}/machines", params=params)

    assert response.status_code == 422


def test_a_building_with_one_meter_says_why_there_is_no_comparison(
    factory_client: TestClient,
) -> None:
    body = machines(factory_client, building="syn-office-a")

    assert body["available"] is False and body["main"] is None and body["machines"] == []
    assert "at least two electricity meters" in str(body["message"])
    assert factory_client.get(f"{API}/buildings/nowhere/machines").status_code == 404
