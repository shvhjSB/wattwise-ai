import copy
from datetime import UTC
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tests.alert_bundles import SAMPLE_BUNDLES, bundle
from tests.conftest import SAMPLE_INFO
from wattwise.db.alerts import AlertLoadSummary, load_alerts
from wattwise.db.models import Alert, AlertFeedback, FeedbackLabel
from wattwise.ml.prioritisation import prioritise, severity_of

DATASET = SAMPLE_INFO.dataset_id


def stored(engine: Engine) -> list[Alert]:
    with Session(engine) as session:
        return list(session.scalars(select(Alert).order_by(Alert.alert_id)))


def review(engine: Engine, alert_id: int) -> None:
    with Session(engine) as session:
        session.add(AlertFeedback(alert_id=alert_id, label=FeedbackLabel.CONFIRMED_WASTE.value))
        session.commit()


def load(engine: Engine, bundles: list[dict[str, Any]]) -> AlertLoadSummary:
    with engine.begin() as connection:
        return load_alerts(connection, DATASET, bundles)


def test_alerts_are_stored_with_the_t022_score_and_band(sample_engine: Engine) -> None:
    summary = load(sample_engine, SAMPLE_BUNDLES)

    alerts = stored(sample_engine)
    assert (summary.inserted, summary.updated, summary.deleted) == (5, 0, 0)
    expected = {(r["meter_id"], r["start"]): r["score"] for r in prioritise(SAMPLE_BUNDLES)}
    for alert in alerts:
        key = (alert.meter_id, f"{alert.start.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}")
        assert alert.priority_score == expected[key]
        assert alert.severity == severity_of(alert.priority_score)
        assert alert.review_status == "unreviewed"
        assert alert.superseded is False


def test_the_whole_bundle_is_kept_as_evidence(sample_engine: Engine) -> None:
    load(sample_engine, SAMPLE_BUNDLES[:1])

    (alert,) = stored(sample_engine)
    assert alert.evidence == SAMPLE_BUNDLES[0]


def test_a_meter_problem_has_no_potential_excess(sample_engine: Engine) -> None:
    load(sample_engine, SAMPLE_BUNDLES)

    flatline = next(a for a in stored(sample_engine) if a.signature == "flatline")
    assert flatline.kind == "meter_problem"
    assert flatline.potential_excess_kwh is None


def test_reloading_updates_in_place_and_keeps_ids(sample_engine: Engine) -> None:
    load(sample_engine, SAMPLE_BUNDLES)
    before = {(a.meter_id, a.start): a.alert_id for a in stored(sample_engine)}
    changed = copy.deepcopy(SAMPLE_BUNDLES)
    changed[0]["impact"]["potential_excess_kwh"] = 10.0

    summary = load(sample_engine, changed)

    after = stored(sample_engine)
    assert (summary.inserted, summary.updated) == (0, 5)
    assert {(a.meter_id, a.start): a.alert_id for a in after} == before
    assert after[0].potential_excess_kwh == 10.0  # the first alert, updated in place


def test_an_alert_no_longer_detected_is_deleted_unless_reviewed(sample_engine: Engine) -> None:
    load(sample_engine, SAMPLE_BUNDLES)
    alerts = stored(sample_engine)
    reviewed = next(a for a in alerts if a.meter_id == "syn-retail-b:electricity")
    review(sample_engine, reviewed.alert_id)
    dropped = ("syn-retail-b:electricity", "syn-lab-c:electricity")
    keep = [b for b in SAMPLE_BUNDLES if b["event"]["meter_id"] not in dropped]

    summary = load(sample_engine, keep)

    assert (summary.deleted, summary.superseded) == (1, 1)
    remaining = {a.alert_id: a for a in stored(sample_engine)}
    assert remaining[reviewed.alert_id].superseded is True
    assert len(remaining) == 4
    with Session(sample_engine) as session:
        assert session.scalar(select(AlertFeedback.alert_id)) == reviewed.alert_id


def test_a_superseded_alert_detected_again_is_current_again(sample_engine: Engine) -> None:
    load(sample_engine, SAMPLE_BUNDLES)
    reviewed = stored(sample_engine)[1]
    review(sample_engine, reviewed.alert_id)
    load(sample_engine, [b for i, b in enumerate(SAMPLE_BUNDLES) if i != 1])

    load(sample_engine, SAMPLE_BUNDLES)

    again = {a.alert_id: a for a in stored(sample_engine)}[reviewed.alert_id]
    assert again.superseded is False


def test_other_detectors_alerts_are_left_alone(sample_engine: Engine) -> None:
    load(sample_engine, SAMPLE_BUNDLES)
    model_alert = bundle(
        "syn-office-a:electricity", "2016-01-20T14:00:00+00:00", 3, detector="model"
    )

    load(sample_engine, [model_alert])

    assert len(stored(sample_engine)) == 6


def test_a_meter_outside_the_dataset_is_refused(sample_engine: Engine) -> None:
    with pytest.raises(ValueError, match="not in dataset"):
        load(sample_engine, [bundle("nope:electricity", "2016-01-20T00:00:00+00:00", 2)])

    assert stored(sample_engine) == []


def test_two_bundles_for_the_same_alert_are_refused(sample_engine: Engine) -> None:
    with pytest.raises(ValueError, match="same alert"):
        load(sample_engine, [SAMPLE_BUNDLES[0], SAMPLE_BUNDLES[0]])
