"""T018b scoring against human labels: crafted labels and events, and a run on the synthetic load
with a labelled surge (not real performance)."""

from collections.abc import Set as AbstractSet
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, synthetic
from wattwise.ml.lead_check import (
    LABEL,
    Inputs,
    flagged_hours,
    main,
    run_check,
    score,
    segments,
)

T0 = pd.Timestamp("2016-07-04T00:00Z")


def labels(
    meter: str,
    anomalies: AbstractSet[int],
    hours: int = 48,
    untrusted: AbstractSet[int] = frozenset(),
) -> pd.DataFrame:
    times = pd.date_range(T0, periods=hours, freq="h").as_unit("us")
    return pd.DataFrame(
        {
            "timestamp": times,
            "meter_id": meter,
            "anomaly": np.array([1 if h in anomalies else 0 for h in range(hours)], dtype=np.int8),
            "lead_reading_matches_bdg2_raw": [h not in untrusted for h in range(hours)],
        }
    )


def events(*rows: tuple[str, int, int]) -> pd.DataFrame:
    """(meter, first hour, hours) relative to T0."""
    return pd.DataFrame(
        [
            {
                "meter_id": meter,
                "start": T0 + pd.Timedelta(hours=first),
                "end": T0 + pd.Timedelta(hours=first + hours),
            }
            for meter, first, hours in rows
        ],
        columns=["meter_id", "start", "end"],
    )


def test_flagged_hours_are_the_hours_inside_an_event_of_the_same_meter() -> None:
    rows = pd.concat([labels("a", set(), 6), labels("b", set(), 6)], ignore_index=True)

    flags = flagged_hours(events(("a", 1, 2)), rows)

    assert flags.tolist() == [False, True, True, False, False, False] + [False] * 6
    assert not flagged_hours(events(), rows).any()


def test_segments_are_runs_of_consecutive_anomaly_hours_per_meter() -> None:
    rows = pd.concat([labels("a", {2, 3, 4, 10}), labels("b", {0, 1})], ignore_index=True)

    found = segments(rows)

    assert found[["meter_id", "hours"]].values.tolist() == [["a", 3], ["a", 1], ["b", 2]]
    assert found["start"].iloc[0] == T0 + pd.Timedelta(hours=2)
    assert found["end"].iloc[0] == T0 + pd.Timedelta(hours=5)


def test_scores_count_hours_segments_and_events_on_trusted_labels_only() -> None:
    rows = pd.concat(
        [
            labels("a", anomalies={2, 3, 4, 20}, untrusted={30, 31}),
            labels("b", anomalies={40}, untrusted={40}),  # an untrusted anomaly
        ],
        ignore_index=True,
    )
    found = events(
        ("a", 3, 3),  # hours 3-5: overlaps the labelled run 2-4
        ("a", 10, 2),  # labelled normal hours only: a false event
        ("a", 30, 2),  # only untrusted hours: unjudged
        ("b", 39, 3),  # overlaps an untrusted anomaly: unjudged
    )

    result = score(found, rows, meter_weeks=2.0)

    h = result["hours"]
    # flagged trusted hours: a 3, 4, 5, 10, 11 and b 39, 41 (b 40 and a 30-31 are untrusted)
    assert (h["true_positive"], h["false_positive"], h["false_negative"]) == (2, 5, 2)
    assert h["precision"] == pytest.approx(2 / 7, abs=1e-4)
    assert h["recall"] == 0.5
    assert result["segments"]["count"] == 2 and result["segments"]["recall"] == 0.5
    assert result["segments"]["by_length"]["1-2 h"] == {"segments": 1, "recall": 0.0}
    assert result["segments"]["by_length"]["3-23 h"] == {"segments": 1, "recall": 1.0}
    e = result["events"]
    assert (e["overlapping_a_labelled_anomaly"], e["on_labelled_normal_hours_only"]) == (1, 1)
    assert e["unjudged"] == 2 and e["precision"] == 0.5 and e["per_meter_week"] == 2.0
    assert result["chance_precision"] == pytest.approx(4 / 93, abs=1e-4)
    assert result["trusted_label_hours"] == 48 - 2 + 48 - 1


def test_no_events_scores_zero_recall_and_no_precision() -> None:
    result = score(events(), labels("a", {5, 6}), meter_weeks=1.0)

    assert result["hours"]["recall"] == 0.0 and result["hours"]["precision"] is None
    assert result["events"]["precision"] is None and result["segments"]["recall"] == 0.0


def synthetic_inputs() -> Inputs:
    """The synthetic load with a 2-day surge on B in the test window, labelled as an anomaly; a
    few labels on A are marked untrusted."""
    readings, weather = synthetic()
    start, end = pd.Timestamp("2017-03-27T00:00Z"), pd.Timestamp("2017-03-29T00:00Z")
    surge = (
        (readings["building_id"] == "B")
        & (readings["timestamp"] >= start)
        & (readings["timestamp"] < end)
    )
    readings.loc[surge, "value"] *= 1.6
    lab = readings[["timestamp", "meter_id"]].assign(
        anomaly=surge.astype(np.int8).to_numpy(),
        lead_reading_matches_bdg2_raw=True,
    )
    lab.loc[
        (lab["meter_id"] == "A-electricity") & (lab.index % 50 == 0),
        "lead_reading_matches_bdg2_raw",
    ] = False
    return Inputs(readings, BUILDINGS, weather, None, lab)


def test_a_check_on_the_synthetic_load_finds_the_labelled_surge_with_the_model() -> None:
    report = run_check(synthetic_inputs(), SPLIT)

    assert report["label"] == LABEL
    assert report["meters"] == 3 and report["meters_with_labels_in_detection_window"] == 3
    assert report["untrusted_label_rows_in_detection_window"] > 0
    model = report["detectors"]["model"]
    assert model["segments"]["count"] == 1 and model["segments"]["recall"] == 1.0
    assert model["hours"]["recall"] == 1.0
    rolling = report["detectors"]["rolling-z"]
    assert rolling["segments"]["recall"] == 0.0, "the weather-masked surge (D030)"
    context = report["forecast_context"]
    assert context["common_rows_mae_model"] < context["common_rows_mae_seasonal_naive"]


def test_the_command_line_needs_prepared_raw_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data", str(tmp_path), "--labels", str(tmp_path / "labels.parquet")]) == 1
    assert "error:" in capsys.readouterr().err
