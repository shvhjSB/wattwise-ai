"""T054: the detector study's statistic, protocol constants, selection and acceptance rules."""

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wattwise.ml.detection import DETECTOR_DEFAULTS, Detector, DetectorConfig, rolling_same_hour
from wattwise.ml.detector_study import (
    BUDGET,
    CANDIDATES,
    DEFAULT,
    DEVELOPMENT,
    HELD_OUT,
    HISTORY_START,
    Candidate,
    accept,
    bootstrap_difference,
    diagnose_short_misses,
    evaluate,
    main,
    select,
)

START = pd.Timestamp("2016-06-01T00:00Z")
SPIKE = pd.Timestamp("2016-07-05T12:00Z")


def series(values: list[float], meter: str = "m") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(START, periods=len(values), freq="h").as_unit("us"),
            "meter_id": meter,
            "building_id": "b",
            "meter_type": "electricity",
            "unit": "kWh",
            "value": values,
        }
    )


def alternating(days: int, spike: float = 0.0) -> pd.DataFrame:
    """10 ± 0.5, alternating by day (same-hour mean 10, sd about 0.52), with `spike` kWh added
    at SPIKE: about 5.8 sd, between the opening threshold 4 and the default z_spike 8."""
    frame = series([10 + 0.5 * (-1) ** (h // 24) for h in range(24 * days)])
    frame.loc[frame["timestamp"] == SPIKE, "value"] += spike
    return frame


def labels_for(readings: pd.DataFrame, anomalies: set[pd.Timestamp]) -> pd.DataFrame:
    inside = readings[readings["timestamp"] >= pd.Timestamp("2016-07-01T00:00Z")]
    return pd.DataFrame(
        {
            "timestamp": inside["timestamp"].to_numpy(),
            "meter_id": inside["meter_id"].to_numpy(),
            "anomaly": np.array([t in anomalies for t in inside["timestamp"]], dtype=np.int8),
            "lead_reading_matches_bdg2_raw": True,
        }
    )


# -- the robust statistic -------------------------------------------------------------------


def test_the_median_baseline_is_not_inflated_by_an_earlier_outlier() -> None:
    values = [10.0] * (24 * 20)
    values[24 * 3 + 5] = 100.0  # one earlier outlier at 05:00
    values[24 * 16 + 5] = 20.0  # a real jump at 05:00, 13 days later
    readings = series(values)
    jump = 24 * 16 + 5

    z_mean, mean = rolling_same_hour(readings)
    z_median, median = rolling_same_hour(readings, statistic="median")

    assert median[jump] == 10.0
    assert z_median[jump] == pytest.approx(100.0)  # (20 - 10) / the 1 % floor of 10
    assert mean[jump] == pytest.approx((13 * 10 + 100) / 14)
    assert z_mean[jump] < 1  # masked by the outlier inside the 14-day window


def test_the_median_baseline_needs_seven_days_of_history() -> None:
    z, centre = rolling_same_hour(series([10.0] * (24 * 9)), statistic="median")

    assert np.isnan(z[: 24 * 7]).all() and np.isnan(centre[: 24 * 7]).all()
    assert (z[24 * 7 :] == 0).all()


def test_the_mean_baseline_is_unchanged_and_unknown_statistics_are_refused() -> None:
    readings = alternating(20)
    z, mean = rolling_same_hour(readings)

    explicit_z, explicit_mean = rolling_same_hour(readings, statistic="mean")
    pd.testing.assert_series_equal(z, explicit_z)
    pd.testing.assert_series_equal(mean, explicit_mean)
    with pytest.raises(ValueError, match="statistic"):
        rolling_same_hour(readings, statistic="trimmed")


# -- protocol constants ---------------------------------------------------------------------


def test_the_candidates_are_the_predeclared_grid_and_include_the_production_default() -> None:
    names = [c.name for c in CANDIDATES]

    assert len(names) == len(set(names)) == 18
    assert DEFAULT in CANDIDATES
    assert DEFAULT.config() == DetectorConfig(**DETECTOR_DEFAULTS[Detector.ROLLING_Z])  # type: ignore[arg-type]
    assert all(c.z_spike >= c.z_on for c in CANDIDATES)


def test_the_held_out_window_is_strictly_later_than_development() -> None:
    assert DEVELOPMENT[0] < DEVELOPMENT[1] == HELD_OUT[0] < HELD_OUT[1]
    assert HISTORY_START + timedelta(days=14) <= DEVELOPMENT[0]


# -- scoring, selection and acceptance ------------------------------------------------------


def test_a_short_spike_is_dropped_by_the_default_and_kept_by_a_lower_spike_rule() -> None:
    readings = alternating(40, spike=3.0)
    labels = labels_for(readings, {SPIKE})
    short = Candidate("mean", 4.0, 4.0)

    results = evaluate(readings, labels, DEVELOPMENT, [DEFAULT, short])

    assert results[DEFAULT.name]["segments"]["recall"] == 0.0
    assert results[short.name]["segments"]["recall"] == 1.0
    assert results[short.name]["per_meter"] == {"m": [1, 1]}
    assert results[short.name]["events"]["count"] == 1


def test_the_diagnosis_says_which_rule_dropped_a_missed_short_segment() -> None:
    readings = alternating(40, spike=3.0)

    diagnosis = diagnose_short_misses(readings, labels_for(readings, {SPIKE}))

    assert diagnosis["short_segments"] == diagnosis["missed"] == 1
    assert diagnosis["missed_by_peak_abs_z"]["4 to 8"] == 1
    assert diagnosis["missed_above_baseline"] == 1


def result(recall: float, per_week: float, precision: float = 0.2) -> dict[str, object]:
    bands = {name: {"recall": recall} for name in ("1-2 h", "3-23 h", "24 h or more")}
    return {
        "segments": {"recall": recall, "by_length": bands},
        "events": {"per_meter_week": per_week, "precision": precision},
    }


def test_selection_takes_the_best_recall_within_the_budget() -> None:
    results = {
        DEFAULT.name: result(0.19, 0.43),
        "a": result(0.30, BUDGET + 0.01),  # over the budget
        "b": result(0.25, 0.48),
        "c": result(0.2505, 0.45),  # a tie with b: fewer events wins
    }

    assert select(results) == "c"
    assert select({"a": result(0.3, 0.9)}) == DEFAULT.name


def test_the_bootstrap_interval_is_paired_by_meter_and_reproducible() -> None:
    baseline = {"a": [4, 1], "b": [6, 2], "c": [5, 1]}
    better = {"a": [4, 3], "b": [6, 4], "c": [5, 3]}

    assert bootstrap_difference(baseline, baseline) == (0.0, 0.0)
    low, high = bootstrap_difference(baseline, better)
    assert 0 < low <= high
    assert bootstrap_difference(baseline, better) == (low, high)


def test_acceptance_needs_every_predeclared_criterion() -> None:
    default = result(0.19, 0.43, precision=0.22)

    assert accept(default, result(0.25, 0.45, precision=0.21), (0.02, 0.09))["passed"]
    small_gain = accept(default, result(0.21, 0.45, precision=0.22), (0.01, 0.03))
    assert not small_gain["passed"]
    assert not small_gain["criteria"]["recall_gain_at_least_0.03"]
    over_budget = accept(default, result(0.30, 0.6, precision=0.22), (0.05, 0.15))
    assert not over_budget["criteria"]["within_budget"]
    noisier = accept(default, result(0.30, 0.45, precision=0.15), (0.05, 0.15))
    assert not noisier["criteria"]["event_precision_loss_at_most_0.02"]
    unsure = accept(default, result(0.25, 0.45, precision=0.22), (-0.01, 0.12))
    assert not unsure["criteria"]["bootstrap_interval_above_zero"]


# -- scored once ----------------------------------------------------------------------------


def test_the_held_out_window_is_scored_once_and_only_after_development(tmp_path: Path) -> None:
    args = ["--data", str(tmp_path / "none"), "--labels", str(tmp_path / "none.parquet")]
    args += ["--output", str(tmp_path)]

    assert main(["held-out", *args]) == 1  # no development result yet
    (tmp_path / "development.json").write_text("{}", encoding="utf-8")
    (tmp_path / "held_out.json").write_text("{}", encoding="utf-8")
    assert main(["held-out", *args]) == 1  # already scored
