from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select

from tests.conftest import SAMPLE_INFO
from wattwise.api.main import create_app
from wattwise.core.config import Settings
from wattwise.data.quality import QualityCheck
from wattwise.db.models import DatasetQuality
from wattwise.db.quality import assess_stored

URL = f"/api/v1/datasets/{SAMPLE_INFO.dataset_id}/quality"


def test_loading_a_dataset_stores_its_audit(sample_engine: Engine) -> None:
    with sample_engine.connect() as connection:
        dataset_id, summary, meters = connection.execute(
            select(DatasetQuality.dataset_id, DatasetQuality.summary, DatasetQuality.meters)
        ).one()
    assert dataset_id == SAMPLE_INFO.dataset_id
    assert summary["meters"] == 4 and summary["rows"] == 5376
    assert len(meters) == 4


def test_the_audit_lists_every_check_and_the_meters(sample_client: TestClient) -> None:
    body = sample_client.get(URL).json()

    assert body["available"] is True
    assert body["data_kind"] == "synthetic"
    assert [c["check"] for c in body["checks"]] == [c.value for c in QualityCheck]
    assert all(c["definition"] for c in body["checks"])
    assert body["summary"]["meters"] == 4
    assert body["meters"]["total"] == 4
    assert "duplicate_key" in body["duplicates_note"]
    assert body["thresholds"]["min_coverage_pct"] == 95.0
    warnings = [m["warnings"] for m in body["meters"]["items"]]
    assert warnings == sorted(warnings, reverse=True)  # warnings first


def test_meters_can_be_filtered_and_paged(sample_client: TestClient) -> None:
    body = sample_client.get(URL).json()
    flagged = [c["check"] for c in body["checks"] if c["meters"] > 0]
    assert flagged, "the synthetic sample has injected data faults"

    by_check = sample_client.get(URL, params={"check": flagged[0]}).json()["meters"]
    assert by_check["total"] == next(
        c["meters"] for c in body["checks"] if c["check"] == flagged[0]
    )
    for meter in by_check["items"]:
        assert any(f["check"] == flagged[0] for f in meter["findings"])

    warned = sample_client.get(URL, params={"warnings_only": True}).json()["meters"]
    assert all(m["warnings"] > 0 for m in warned["items"])

    page = sample_client.get(URL, params={"limit": 1, "offset": 1}).json()["meters"]
    assert len(page["items"]) == 1 and page["total"] == 4 and page["offset"] == 1


def test_a_dataset_without_an_audit_says_how_to_make_one(sample_engine: Engine) -> None:
    with sample_engine.begin() as connection:
        connection.execute(delete(DatasetQuality))
    app = create_app(Settings(environment="test", database_url=None), engine=sample_engine)
    with TestClient(app) as client:
        body = client.get(URL).json()
        assert body["available"] is False
        assert "python -m wattwise.db.quality" in body["message"]

        with sample_engine.begin() as connection:
            report = assess_stored(connection, SAMPLE_INFO.dataset_id)
        assert report.summary is not None and report.summary.rows == 5376
        assert client.get(URL).json()["available"] is True


def test_unknown_datasets_and_checks_are_refused(sample_client: TestClient) -> None:
    assert sample_client.get("/api/v1/datasets/nope/quality").status_code == 404
    assert sample_client.get(URL, params={"check": "nope"}).status_code == 422
