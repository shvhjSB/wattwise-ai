from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.alert_bundles import SAMPLE_BUNDLES
from wattwise.ml.prioritisation import prioritise

API = "/api/v1"


def alerts(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get(f"{API}/alerts", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def first_id(client: TestClient, **params: Any) -> int:
    alert_id: int = alerts(client, **params)["items"][0]["alert_id"]
    return alert_id


# -- listing --------------------------------------------------------------------------------------


def test_alerts_are_listed_highest_priority_first(alert_client: TestClient) -> None:
    page = alerts(alert_client)

    scores = [a["priority_score"] for a in page["items"]]
    assert page["total"] == 5
    assert scores == sorted(scores, reverse=True)
    assert scores == [r["score"] for r in prioritise(SAMPLE_BUNDLES)]
    first = page["items"][0]
    assert first["data_kind"] == "synthetic"
    assert first["review_status"] == "unreviewed"
    assert first["feedback_count"] == 0
    assert first["start"].endswith("Z")


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"building_id": "syn-office-a"}, 2),
        ({"meter_id": "syn-lab-c:electricity"}, 1),
        ({"signature": "flatline"}, 1),
        ({"kind": "below_expected"}, 1),
        ({"kind": "meter_problem"}, 1),
        ({"dataset_id": "synthetic-sample"}, 5),
        ({"dataset_id": "other"}, 0),
        ({"review_status": "unreviewed"}, 5),
        ({"review_status": "confirmed_waste"}, 0),
        # Overlap with [start, end): the 2016-01-20 spike and the 72 h event from 2016-02-08.
        ({"start": "2016-01-20T15:00:00Z", "end": "2016-01-21T00:00:00Z"}, 1),
        ({"start": "2016-02-10T00:00:00Z"}, 2),
        ({"end": "2016-01-21T00:00:00+00:00"}, 1),
    ],
)
def test_alerts_filter(alert_client: TestClient, params: dict[str, str], expected: int) -> None:
    assert alerts(alert_client, **params)["total"] == expected


def test_alerts_filter_by_severity_band(alert_client: TestClient) -> None:
    every = alerts(alert_client)["items"]

    for band in ("high", "medium", "low"):
        page = alerts(alert_client, severity=band)
        assert page["total"] == sum(a["severity"] == band for a in every)
        assert all(a["severity"] == band for a in page["items"])


def test_alerts_paginate(alert_client: TestClient) -> None:
    every = [a["alert_id"] for a in alerts(alert_client)["items"]]
    first = alerts(alert_client, limit=2)
    rest = alerts(alert_client, limit=2, offset=2)

    assert [a["alert_id"] for a in first["items"] + rest["items"]] == every[:4]


@pytest.mark.parametrize(
    "params",
    [
        {"signature": "explosion"},
        {"severity": "critical"},
        {"review_status": "approved"},
        {"kind": "other"},
        {"start": "2016-01-20T00:00:00"},  # no time zone
        {"start": "2016-01-21T00:00:00Z", "end": "2016-01-20T00:00:00Z"},
        {"limit": 0},
    ],
)
def test_bad_alert_queries_are_validation_errors(
    alert_client: TestClient, params: dict[str, str]
) -> None:
    assert alert_client.get(f"{API}/alerts", params=params).status_code == 422


# -- detail ---------------------------------------------------------------------------------------


def test_an_alert_comes_with_its_evidence_and_caveats(alert_client: TestClient) -> None:
    alert_id = first_id(alert_client)

    detail = alert_client.get(f"{API}/alerts/{alert_id}").json()

    assert detail["evidence"]["event"]["meter_id"] == detail["meter_id"]
    assert detail["explanation"].endswith("an anomaly to investigate.")
    assert detail["feedback"] == []
    assert detail["retrained_from_feedback"] is False
    assert any("not confirmed waste" in c for c in detail["caveats"])
    assert any("not a verified saving" in c for c in detail["caveats"])
    assert detail["model_version"] == "test-model"


def test_a_missing_alert_is_404(alert_client: TestClient) -> None:
    assert alert_client.get(f"{API}/alerts/999999").status_code == 404
    assert alert_client.get(f"{API}/alerts/not-a-number").status_code == 422


# -- feedback -------------------------------------------------------------------------------------


def test_feedback_is_stored_and_sets_the_review_status(alert_client: TestClient) -> None:
    alert_id = first_id(alert_client)

    response = alert_client.post(
        f"{API}/alerts/{alert_id}/feedback",
        json={"label": "expected_behaviour", "note": "  Open day.  ", "reviewer": "ops-1"},
    )

    assert response.status_code == 201
    saved = response.json()
    assert saved["label"] == "expected_behaviour"
    assert saved["note"] == "Open day."  # surrounding whitespace is stripped
    assert saved["created_at"].endswith("Z")
    detail = alert_client.get(f"{API}/alerts/{alert_id}").json()
    assert detail["review_status"] == "expected_behaviour"
    assert detail["reviewed_at"] == saved["created_at"]
    assert detail["feedback_count"] == 1
    assert detail["retrained_from_feedback"] is False


def test_feedback_is_a_history_and_the_latest_label_wins(alert_client: TestClient) -> None:
    alert_id = first_id(alert_client)
    for label in ("needs_investigation", "confirmed_waste"):
        response = alert_client.post(f"{API}/alerts/{alert_id}/feedback", json={"label": label})
        assert response.status_code == 201

    detail = alert_client.get(f"{API}/alerts/{alert_id}").json()

    assert [f["label"] for f in detail["feedback"]] == ["needs_investigation", "confirmed_waste"]
    assert detail["review_status"] == "confirmed_waste"
    assert alerts(alert_client, review_status="confirmed_waste")["total"] == 1
    assert alerts(alert_client, review_status="unreviewed")["total"] == 4


@pytest.mark.parametrize(
    "body",
    [
        {},  # no label
        {"label": "useful"},  # not in the label set
        {"label": "CONFIRMED_WASTE"},
        {"label": "confirmed_waste", "note": "x" * 2001},
        {"label": "confirmed_waste", "reviewer": "x" * 101},
        {"label": "confirmed_waste", "reviewer": "   "},  # empty after stripping
        {"label": "confirmed_waste", "note": "bad\x00byte"},
        {"label": "confirmed_waste", "note": "bell\x07"},
        {"label": "confirmed_waste", "score": 5},  # unknown field
        {"label": "confirmed_waste", "note": 42},
    ],
)
def test_invalid_feedback_is_rejected_and_nothing_is_stored(
    alert_client: TestClient, body: dict[str, Any]
) -> None:
    alert_id = first_id(alert_client)

    response = alert_client.post(f"{API}/alerts/{alert_id}/feedback", json=body)

    assert response.status_code == 422
    assert alert_client.get(f"{API}/alerts/{alert_id}").json()["feedback_count"] == 0


def test_a_note_keeps_line_breaks_and_text_that_looks_like_sql(alert_client: TestClient) -> None:
    alert_id = first_id(alert_client)
    note = "Line one\nLine two\t'; DROP TABLE alerts; --"

    saved = alert_client.post(
        f"{API}/alerts/{alert_id}/feedback", json={"label": "needs_investigation", "note": note}
    ).json()

    assert saved["note"] == note
    assert alerts(alert_client)["total"] == 5  # stored as text, never executed


def test_feedback_for_a_missing_alert_is_404(alert_client: TestClient) -> None:
    response = alert_client.post(f"{API}/alerts/999999/feedback", json={"label": "confirmed_waste"})

    assert response.status_code == 404


# -- superseded alerts ----------------------------------------------------------------------------


def test_a_reviewed_alert_no_longer_detected_is_hidden_unless_asked_for(
    alert_client: TestClient, alert_engine: Any
) -> None:
    from tests.conftest import SAMPLE_INFO
    from wattwise.db.alerts import load_alerts

    reviewed = alerts(alert_client, meter_id="syn-retail-b:electricity")["items"][0]["alert_id"]
    alert_client.post(f"{API}/alerts/{reviewed}/feedback", json={"label": "confirmed_waste"})
    with alert_engine.begin() as connection:
        load_alerts(
            connection,
            SAMPLE_INFO.dataset_id,
            [b for b in SAMPLE_BUNDLES if b["event"]["meter_id"] != "syn-retail-b:electricity"],
        )

    assert alerts(alert_client)["total"] == 4
    shown = alerts(alert_client, include_superseded=True)
    assert shown["total"] == 5
    assert next(a for a in shown["items"] if a["alert_id"] == reviewed)["superseded"] is True
    assert alert_client.get(f"{API}/alerts/{reviewed}").json()["feedback_count"] == 1


# -- without a database ---------------------------------------------------------------------------


def test_alert_endpoints_are_503_without_a_database(client: TestClient) -> None:
    assert client.get(f"{API}/alerts").status_code == 503
    assert client.get(f"{API}/alerts/1").status_code == 503
    response = client.post(f"{API}/alerts/1/feedback", json={"label": "confirmed_waste"})
    assert response.status_code == 503


def test_the_alert_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths[f"{API}/alerts"]
    assert "get" in paths[f"{API}/alerts/{{alert_id}}"]
    assert "post" in paths[f"{API}/alerts/{{alert_id}}/feedback"]
