"""T017 signature rules on crafted event hours, each with positive and negative cases."""

import json
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest

from wattwise.data.quality import QualityThresholds
from wattwise.ml.detection import calibrate, detect
from wattwise.ml.signatures import (
    DESCRIPTIONS,
    PRECEDENCE,
    EventHours,
    Signature,
    SignatureConfig,
    classify,
    classify_event,
    data_fault,
    drift,
    flatline,
    overnight_excess,
    spike,
    sustained,
)

CONFIG = SignatureConfig()
START = pd.Timestamp("2017-10-02T12:00Z")  # a Monday noon (UTC = local in these tests)


def event(
    values: npt.ArrayLike,
    baseline: float | Sequence[float] = 100.0,
    direction: str = "high",
    start: pd.Timestamp = START,
    score: Sequence[float] | None = None,
) -> EventHours:
    value = np.asarray(values, dtype=float)
    times = pd.date_range(start, periods=len(value), freq="h")
    base = np.broadcast_to(np.asarray(baseline, dtype=float), value.shape).astype(float)
    sign = 1.0 if direction == "high" else -1.0
    scores = np.asarray(score, dtype=float) if score is not None else sign * (value - base) / 5
    return EventHours(
        direction=direction,
        times=times,
        local_hours=np.asarray(times.hour, dtype=np.int64),
        value=value,
        baseline=base,
        score=scores,
        z_off=2.0,
    )


def labels(e: EventHours) -> tuple[str, str]:
    result = classify_event(e)
    return result["signature"], result["signatures"]


# ---------------------------------------------------------------------------
# Rules, positive and negative
# ---------------------------------------------------------------------------


def test_data_fault_flags_negative_readings() -> None:
    hit, evidence = data_fault(event([150, -3, 150, 150]), CONFIG)
    assert hit and evidence["reasons"] == ["negative_readings"]
    assert not data_fault(event([150, 3, 150, 150]), CONFIG)[0]


def test_data_fault_flags_a_long_zero_run_only_from_the_quality_length() -> None:
    long_run = data_fault(event([0.0] * 24, direction="low"), CONFIG)
    short_run = data_fault(event([0.0] * 23, direction="low"), CONFIG)
    assert long_run[0] and long_run[1]["longest_zero_run_hours"] == 24
    assert not short_run[0]


def test_data_fault_flags_mostly_missing_events() -> None:
    nan = float("nan")
    assert data_fault(event([150, nan, nan, nan, 150]), CONFIG)[0]  # 60% missing
    assert not data_fault(event([150, nan, nan, 150, 150]), CONFIG)[0]  # 40%


def test_data_fault_flags_implausibly_large_deviations() -> None:
    assert data_fault(event([150] * 4, score=[3, 60, 3, 3]), CONFIG)[0]
    assert not data_fault(event([150] * 4, score=[3, 49, 3, 3]), CONFIG)[0]


def test_flatline_needs_a_long_constant_nonzero_run_covering_the_event() -> None:
    stuck = [140.0] + [155.5] * 10 + [140.0]
    hit, evidence = flatline(event(stuck), CONFIG)
    assert hit and evidence["longest_constant_run_hours"] == 10
    assert not flatline(event([140.0] + [155.5] * 5 + [141, 142]), CONFIG)[0]
    assert not flatline(event([155.5] * 6 + list(range(160, 174))), CONFIG)[0]  # 6 of 20 hours
    assert not flatline(event([0.0] * 12, direction="low"), CONFIG)[0]  # zeros: a data fault


def test_spike_is_short() -> None:
    assert spike(event([180, 190, 180]), CONFIG)[0]
    assert not spike(event([180, 190, 180, 170]), CONFIG)[0]


def test_overnight_excess_is_high_and_concentrated_at_night() -> None:
    night_start = pd.Timestamp("2017-10-02T21:00Z")
    # 21:00-06:00: excess of 50 from 22:00 to 05:00, 10 at 21:00 and 06:00
    night = [110] + [150] * 8 + [110]
    hit, evidence = overnight_excess(event(night, start=night_start), CONFIG)
    assert hit and evidence["night_share_of_excess"] == pytest.approx(400 / 420, abs=1e-3)
    assert not overnight_excess(event([150] * 10), CONFIG)[0]  # daytime (12:00-21:00)
    low = event([50] * 10, start=night_start, direction="low")
    assert not overnight_excess(low, CONFIG)[0]  # low events have no excess


def test_drift_grows_steadily_through_a_long_event() -> None:
    rising = 100 + np.linspace(5, 60, 90)
    hit, evidence = drift(event(rising), CONFIG)
    assert hit and evidence["growth"] > 0.5
    assert not drift(event([140.0] * 90), CONFIG)[0]  # constant deviation
    assert not drift(event(100 + np.linspace(5, 60, 48)), CONFIG)[0]  # too short
    falling = 100 - np.linspace(5, 60, 90)
    assert drift(event(falling, direction="low"), CONFIG)[0]  # deepening drop


def test_sustained_needs_a_day_with_most_hours_flagged() -> None:
    assert sustained(event([150.0] * 30), CONFIG)[0]
    half = [150.0, 105.0] * 15  # every other hour below z_off
    assert not sustained(event(half), CONFIG)[0]
    assert not sustained(event([150.0] * 20), CONFIG)[0]


# ---------------------------------------------------------------------------
# Precedence, outputs and configuration
# ---------------------------------------------------------------------------


def test_meter_problems_take_precedence_over_consumption_patterns() -> None:
    assert labels(event([150, -1, 150])) == ("data_fault", "data_fault;spike")
    stuck = [155.5] * 30
    assert labels(event(stuck)) == ("flatline", "flatline;sustained")
    assert list(PRECEDENCE)[:2] == [Signature.DATA_FAULT, Signature.FLATLINE]


def test_an_event_matching_no_rule_is_unclassified() -> None:
    result = classify_event(event([150, 160, 150, 145, 151, 158, 149, 152, 150, 157]))

    assert (result["signature"], result["signatures"]) == ("unclassified", "unclassified")
    assert result["description"] == DESCRIPTIONS[Signature.UNCLASSIFIED]


def test_evidence_is_valid_json_with_every_rule_and_null_for_the_unmeasurable() -> None:
    nan = float("nan")
    result = classify_event(event([nan, nan, nan], score=[nan, nan, nan]))
    evidence = json.loads(result["evidence"])

    assert set(evidence) == {s.value for s in Signature if s is not Signature.UNCLASSIFIED}
    assert evidence["data_fault"]["peak_z"] is None
    assert evidence["data_fault"]["matched"] is True  # all missing
    assert all("matched" in rule for rule in evidence.values())


def test_flatline_and_zero_run_lengths_follow_the_quality_engine() -> None:
    quality = QualityThresholds()

    assert CONFIG.flatline_min_hours == quality.flatline_min_intervals
    assert CONFIG.zero_run_min_hours == quality.zero_run_min_intervals
    assert CONFIG.flatline_tolerance == quality.flatline_tolerance


def test_descriptions_name_patterns_not_causes() -> None:
    for text in DESCRIPTIONS.values():
        lowered = text.lower()
        assert not any(word in lowered for word in ("because", "caused", "due to", "waste"))


# ---------------------------------------------------------------------------
# With the detector
# ---------------------------------------------------------------------------


def test_classify_labels_detected_events_in_local_time() -> None:
    """A meter in New York with a night-time excess (local 22:00-05:00) and a short spike. (A
    perfectly constant excess would rightly be labelled a flatline: a stuck meter.)"""
    times = pd.date_range("2017-09-04T00:00Z", periods=8 * 168, freq="h").as_unit("us")
    noise = np.where(np.arange(len(times)) % 2 == 0, 1.0, -1.0)
    value = 100.0 + noise
    detection_rows = times >= pd.Timestamp("2017-10-02T00:00Z")
    value[detection_rows] = 100.0
    local = times.tz_convert("America/New_York")
    night = detection_rows & (local.day == 10) & np.isin(local.hour, [22, 23])
    night |= detection_rows & (local.day == 11) & (local.hour <= 5)
    value[night] += 40.0 + np.arange(int(night.sum()))  # varying, or it would look stuck
    value[times == pd.Timestamp("2017-10-20T15:00Z")] += 60.0
    readings = pd.DataFrame(
        {"timestamp": times, "meter_id": "m", "building_id": "NY", "value": value}
    )
    expected = pd.Series(100.0, index=readings.index)
    buildings = pd.DataFrame({"building_id": ["NY"], "timezone": ["America/New_York"]})

    calibration = calibrate(readings, expected, ~detection_rows)
    detected = detect(readings, expected, calibration, detection_rows)
    labelled = classify(detected, buildings, z_off=2.0)

    assert labelled["signature"].tolist() == ["overnight_excess", "spike"]
    assert labelled.columns[-4:].tolist() == ["signature", "signatures", "description", "evidence"]
    assert len(detected.hours) == labelled["duration_hours"].sum()
    assert detected.hours["event"].unique().tolist() == [0, 1]


def test_the_detection_doc_lists_every_signature() -> None:
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[3] / "docs" / "DETECTION.md").read_text("utf-8")

    for signature in Signature:
        assert f"| `{signature.value}` |" in doc
