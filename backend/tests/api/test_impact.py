from fastapi.testclient import TestClient
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from wattwise.db.models import Building

API = "/api/v1"


def test_impact_without_configuration_reports_kwh_and_not_configured_carbon(
    alert_client: TestClient,
) -> None:
    response = alert_client.get(f"{API}/impact/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "potential" and body["tariff"] is None
    synthetic = body["by_kind"][0]
    assert synthetic["kind"] == "synthetic"
    assert synthetic["events"] == 5
    assert synthetic["events_counted"] == 4
    assert synthetic["meter_problem_events"] == 1
    assert synthetic["total_potential_excess_kwh"] == 2320.0
    assert synthetic["total_potential_carbon_kg"] is None
    assert synthetic["carbon_unconfigured_events"] == 4
    assert synthetic["total_cost"] is None


def test_impact_uses_sourced_carbon_and_an_explicit_tariff_only_for_its_geography(
    alert_engine: Engine, alert_client: TestClient
) -> None:
    with Session(alert_engine) as session:
        session.execute(
            update(Building).where(Building.building_id == "syn-office-a").values(site_id="Hog")
        )
        session.commit()

    response = alert_client.get(
        f"{API}/impact/summary",
        params={"tariff_geography": "US-MN", "currency": "usd", "rate_per_kwh": 0.1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tariff"] == {
        "geography": "US-MN",
        "currency": "USD",
        "rate_per_kwh": 0.1,
    }
    synthetic = body["by_kind"][0]
    assert synthetic["total_cost"] == {"value": 152.0, "currency": "USD", "events": 2}
    hog = next(group for group in synthetic["by_geography"] if group["tariff_geography"] == "US-MN")
    assert hog["carbon_geography"] == "US-MROW"
    assert hog["potential_excess_kwh"] == 1520.0
    assert hog["potential_carbon_kg"] == 860.051
    assert hog["cost"] == {"value": 152.0, "currency": "USD", "events": 2}
    assert hog["carbon_factors"][0]["source_name"].startswith("EPA eGRID2016")
    assert hog["carbon_factors"][0]["requested_year"] == 2016
    assert hog["price_references"][0]["rate_per_kwh"] == 0.0986
    assert hog["price_references"][0]["source_name"].startswith("EIA")


def test_tariff_parameters_are_all_required_together(alert_client: TestClient) -> None:
    response = alert_client.get(f"{API}/impact/summary", params={"currency": "USD"})

    assert response.status_code == 422
    assert "must be supplied together" in response.json()["detail"]


def test_empty_database_has_no_invented_impact(migrated_client: TestClient) -> None:
    body = migrated_client.get(f"{API}/impact/summary").json()

    assert body["by_kind"] == []
    assert body["tariff"] is None
