"""T019 intervals on synthetic data with known noise (not real performance)."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.ml.intervals import (
    MIN_MONTH_ROWS,
    Method,
    assess,
    conformal_quantile,
    fit,
    main,
    rolling_bounds,
    run_intervals,
)
from wattwise.ml.registry import promote, save, train

T0 = pd.Timestamp("2017-01-02T00:00Z")


def series(
    days: int = 120,
    split_day: int = 60,
    level_before: float = 10.0,
    level_after: float = 10.0,
    noise_before: float = 0.1,
    noise_after: float = 0.1,
    meters: tuple[str, ...] = ("m1",),
    seed: int = 0,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Rows, predictions and levels. The prediction is exact apart from Gaussian noise whose
    standard deviation is noise * level; the level and the noise may change at split_day."""
    rng = np.random.default_rng(seed)
    frames, predicted, level = [], [], []
    for meter in meters:
        times = pd.date_range(T0, periods=days * 24, freq="h").as_unit("us")
        after = np.asarray(times >= T0 + pd.Timedelta(days=split_day))
        lvl = np.where(after, level_after, level_before)
        sigma = np.where(after, noise_after, noise_before) * lvl
        p = lvl.astype(float)
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": times,
                    "meter_id": meter,
                    "value": p + rng.normal(0, 1, len(p)) * sigma,
                }
            )
        )
        predicted.append(p)
        level.append(lvl.astype(float))
    return pd.concat(frames, ignore_index=True), np.concatenate(predicted), np.concatenate(level)


def windows(rows: pd.DataFrame, split_day: int = 60) -> tuple[np.ndarray, np.ndarray]:
    before = (rows["timestamp"] < T0 + pd.Timedelta(days=split_day)).to_numpy()
    return before, ~before


# ---------------------------------------------------------------------------
# The conformal quantile and fixed intervals
# ---------------------------------------------------------------------------


def test_the_conformal_quantile_is_the_corrected_order_statistic() -> None:
    scores = np.arange(1.0, 20.0)  # 1 .. 19, n = 19

    assert conformal_quantile(scores, 0.1) == 18.0  # ceil(20 * 0.9) = 18th smallest
    assert conformal_quantile([*scores, np.nan, np.inf], 0.1) == 18.0
    assert conformal_quantile([1.0, 2.0], 0.1) == math.inf  # needs 3 scores


def test_fixed_intervals_cover_as_promised_when_nothing_changes() -> None:
    rows, predicted, level = series(meters=("m1", "m2"), seed=1)
    cal, test = windows(rows)

    for method in (Method.ABSOLUTE, Method.RELATIVE):
        fitted = fit(
            method, 0.1, rows["meter_id"][cal], rows["value"][cal], predicted[cal], level[cal]
        )
        result = assess(
            rows[test], *fitted.bounds(rows["meter_id"][test], predicted[test], level[test]), 0.1
        )
        assert result["coverage"] == pytest.approx(0.9, abs=0.02)
        assert set(fitted.quantiles.index) == {"m1", "m2"}


def test_a_level_change_breaks_absolute_intervals_but_not_relative_ones() -> None:
    """The meter's level doubles after calibration and its noise scales with it."""
    rows, predicted, level = series(level_after=20.0, seed=2)
    cal, test = windows(rows)
    results = {}
    for method in (Method.ABSOLUTE, Method.RELATIVE):
        fitted = fit(
            method, 0.1, rows["meter_id"][cal], rows["value"][cal], predicted[cal], level[cal]
        )
        lower, upper = fitted.bounds(rows["meter_id"][test], predicted[test], level[test])
        results[method] = assess(rows[test], lower, upper, 0.1)

    assert results[Method.ABSOLUTE]["coverage"] < 0.65
    assert results[Method.RELATIVE]["coverage"] == pytest.approx(0.9, abs=0.02)
    assert results[Method.RELATIVE]["calibrated"]
    assert not results[Method.ABSOLUTE]["calibrated"]


def test_bounds_are_missing_without_a_prediction_or_scale_and_never_negative() -> None:
    rows, predicted, level = series(days=20, split_day=10)
    fitted = fit(Method.RELATIVE, 0.1, rows["meter_id"], rows["value"], predicted, level)

    lower, upper = fitted.bounds(
        ["m1", "m1", "m1", "zz"], [np.nan, 1.0, 0.1, 5.0], [10.0, 0.0, 10.0, 10.0]
    )

    assert np.isnan(lower[0]) and np.isnan(lower[1]), "no prediction; no positive level"
    assert lower[2] == 0.0 and upper[2] > 0.1, "clipped at zero"
    assert np.isnan(upper[3]), "unknown meter"
    with pytest.raises(ValueError, match="rolling_bounds"):
        fit(Method.ROLLING, 0.1, rows["meter_id"], rows["value"], predicted, level)
    with pytest.raises(ValueError, match="alpha"):
        fit(Method.RELATIVE, 1.5, rows["meter_id"], rows["value"], predicted, level)


# ---------------------------------------------------------------------------
# Rolling intervals
# ---------------------------------------------------------------------------


def test_rolling_intervals_adapt_when_the_noise_itself_changes() -> None:
    """The relative noise doubles after day 60. A fixed relative interval under-covers from then
    on; the rolling one recovers once its 28-day window has moved past the change."""
    rows, predicted, level = series(days=150, noise_after=0.2, seed=3)
    cal, _ = windows(rows)
    fixed = fit(
        Method.RELATIVE, 0.1, rows["meter_id"][cal], rows["value"][cal], predicted[cal], level[cal]
    )
    late = (rows["timestamp"] >= T0 + pd.Timedelta(days=100)).to_numpy()

    fixed_late = assess(
        rows[late], *fixed.bounds(rows["meter_id"][late], predicted[late], level[late]), 0.1
    )
    lower, upper = rolling_bounds(rows, predicted, level, 0.1, first_score_time=T0)
    rolling_late = assess(rows[late], lower[late], upper[late], 0.1)

    assert fixed_late["coverage"] < 0.65
    assert rolling_late["coverage"] == pytest.approx(0.9, abs=0.02)


def test_rolling_intervals_use_only_scores_from_before_the_lag() -> None:
    rows, predicted, level = series(days=60)
    day = T0 + pd.Timedelta(days=45)
    target = (
        (rows["timestamp"] >= day) & (rows["timestamp"] < day + pd.Timedelta(days=1))
    ).to_numpy()
    before = rolling_bounds(rows, predicted, level, 0.1, first_score_time=T0)

    recent = (rows["timestamp"] >= day - pd.Timedelta(days=7)).to_numpy()  # inside the lag
    changed = rows.assign(value=np.where(recent, rows["value"] * 50, rows["value"]))
    after = rolling_bounds(changed, predicted, level, 0.1, first_score_time=T0)

    np.testing.assert_array_equal(before[1][target], after[1][target])
    old = (rows["timestamp"] < day - pd.Timedelta(days=7)).to_numpy()
    shifted = rows.assign(value=np.where(old, rows["value"] * 50, rows["value"]))
    assert not np.array_equal(
        rolling_bounds(shifted, predicted, level, 0.1, first_score_time=T0)[1][target],
        before[1][target],
    ), "scores before the lag do matter"


def test_rolling_intervals_need_enough_scores_after_the_first_score_time() -> None:
    rows, predicted, level = series(days=40)

    lower, _ = rolling_bounds(
        rows, predicted, level, 0.1, first_score_time=T0 + pd.Timedelta(days=20)
    )

    early = (rows["timestamp"] < T0 + pd.Timedelta(days=34)).to_numpy()  # 20 + 7 lag + 7 days
    assert np.isnan(lower[early]).all()
    assert np.isfinite(lower[~early]).all()


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def test_assessment_counts_months_meters_widths_and_the_interval_score() -> None:
    times = pd.date_range("2017-01-31T20:00Z", periods=8, freq="h").as_unit("us")
    rows = pd.DataFrame({"timestamp": times, "meter_id": ["a"] * 4 + ["b"] * 4, "value": 10.0})
    lower = np.array([9, 9, 11, 9, 9, 9, 9, np.nan])
    upper = np.array([11, 11, 12, 11, 11, 11, 11, np.nan])

    result = assess(rows, lower, upper, alpha=0.2)

    assert result["coverage"] == pytest.approx(6 / 7, abs=1e-4)
    assert result["rows"] == 7 and result["rows_without_interval"] == 1
    assert set(result["by_month"]) == {"2017-01", "2017-02"}
    assert (
        result["per_meter_coverage"]["min"] == 0.75 and result["per_meter_coverage"]["max"] == 1.0
    )
    assert result["mean_width"] == pytest.approx(13 / 7, abs=1e-4)
    # one miss by 1 kWh: penalty 2 / 0.2 * 1 = 10, spread over 7 rows
    assert result["interval_score"] == pytest.approx((13 + 10) / 7, abs=1e-4)
    assert not result["calibrated"]  # 85.7% against 80% nominal
    assert MIN_MONTH_ROWS > 7, "these tiny months do not decide calibration"


# ---------------------------------------------------------------------------
# With the promoted model
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    readings, weather = synthetic()
    features = features_of(readings, weather)
    root = tmp_path_factory.mktemp("models")
    promote(save(train(readings, BUILDINGS, features, SPLIT), root), root)
    return readings, weather, root


def test_a_run_reports_every_method_and_level(
    registry: tuple[pd.DataFrame, pd.DataFrame, Path],
) -> None:
    readings, weather, root = registry

    report = run_intervals(readings, features_of(readings, weather), root)

    assert set(report["results"]) == {
        f"{m}@{p}" for m in ("absolute", "relative", "rolling") for p in ("80%", "90%", "95%")
    }
    assert report["results"]["rolling@90%"]["calibration_window"] is None
    absolute = report["results"]["absolute@90%"]
    assert absolute["calibration_window"]["coverage"] == pytest.approx(0.9, abs=0.02)
    assert absolute["test_window"]["rows"] > 1000


def test_the_command_line_writes_the_report_and_needs_a_model(
    registry: tuple[pd.DataFrame, pd.DataFrame, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readings, weather, root = registry
    folder = tmp_path / "data"
    folder.mkdir()
    readings.to_parquet(folder / "readings.parquet")
    BUILDINGS.to_parquet(folder / "buildings.parquet")
    weather.to_parquet(folder / "weather.parquet")

    assert (
        main(["--data", str(folder), "--root", str(root), "--output", str(tmp_path / "out")]) == 0
    )
    report = json.loads((tmp_path / "out" / "intervals.json").read_text(encoding="utf-8"))
    assert report["tolerance"] == 0.02
    capsys.readouterr()
    assert main(["--data", str(folder), "--root", str(tmp_path / "none")]) == 1
    assert "Train and promote one first" in capsys.readouterr().err
