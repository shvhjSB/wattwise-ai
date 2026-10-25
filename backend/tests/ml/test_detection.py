"""T016 detector. Most tests build residuals with known scores: calibration noise of +-1 gives a
median of 0 and a MAD of 1, so the scale is exactly 1.4826 and a residual of z * 1.4826 in the
detection rows (which have no noise) scores exactly z."""

import json
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.ml.detection import (
    MAD_TO_SIGMA,
    Detection,
    DetectorConfig,
    calibrate,
    detect,
    main,
    run_detection,
)
from wattwise.ml.registry import promote, save, train

START = pd.Timestamp("2017-01-02T00:00Z")  # a Monday
WEEK = 168
CALIBRATION_HOURS = 3 * WEEK
LEVEL = 100.0


def meter(
    scores: Mapping[int, float] | None = None,
    detection_hours: int = 3 * WEEK,
    drop: tuple[int, ...] = (),
    meter_id: str = "m1",
) -> tuple[pd.DataFrame, pd.Series, np.ndarray, np.ndarray]:
    """Readings, expected (a flat LEVEL), and the calibration and detection masks. `scores` maps
    detection hours (0 = first detection hour) to the score injected there."""
    n = CALIBRATION_HOURS + detection_hours
    value = np.full(n, LEVEL)
    value[:CALIBRATION_HOURS] += np.where(np.arange(CALIBRATION_HOURS) % 2 == 0, 1.0, -1.0)
    for hour, z in (scores or {}).items():
        value[CALIBRATION_HOURS + hour] += z * MAD_TO_SIGMA
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(START, periods=n, freq="h").as_unit("us"),
            "meter_id": meter_id,
            "building_id": "B1",
            "value": value,
        }
    )
    frame = frame.drop(index=[CALIBRATION_HOURS + h for h in drop]).reset_index(drop=True)
    calibration = np.asarray(frame.index < CALIBRATION_HOURS)
    expected = pd.Series(LEVEL, index=frame.index)
    return frame, expected, calibration, ~calibration


def run(
    scores: Mapping[int, float] | None = None, config: DetectorConfig | None = None, **kw: object
) -> Detection:
    frame, expected, calibration, detection = meter(scores, **kw)  # type: ignore[arg-type]
    cal = calibrate(frame, expected, calibration, config)
    return detect(frame, expected, cal, detection, config)


def hours(detected: Detection) -> list[tuple[str, int, int]]:
    """(direction, first detection hour, duration) per event."""
    first = START + timedelta(hours=CALIBRATION_HOURS)
    events = detected.events
    offsets = (events["start"] - first) // pd.Timedelta(hours=1)
    return list(
        zip(
            events["direction"].tolist(),
            offsets.astype(int).tolist(),
            events["duration_hours"].astype(int).tolist(),
            strict=True,
        )
    )


def flat(*values: float, at: int = 10) -> dict[int, float]:
    return {at + i: v for i, v in enumerate(values)}


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def test_calibration_uses_only_its_rows_and_has_the_expected_scale() -> None:
    frame, expected, calibration, _ = meter({5: 50.0, 6: 50.0})

    cal = calibrate(frame, expected, calibration)

    assert cal.center["m1"] == 0.0
    assert cal.scale["m1"] == pytest.approx(MAD_TO_SIGMA)
    assert cal.rows["m1"] == CALIBRATION_HOURS
    assert cal.reference_center["m1"] == 0.0  # value(t) - value(t - 168): same parity, so 0


def test_a_perfect_fit_gets_the_floor_scale_not_zero() -> None:
    frame, expected, calibration, _ = meter()
    perfect = expected.where(~calibration, frame["value"])

    cal = calibrate(frame, perfect, calibration)

    assert cal.scale["m1"] == pytest.approx(0.01 * frame.loc[calibration, "value"].abs().mean())


# ---------------------------------------------------------------------------
# Thresholds, persistence and hysteresis
# ---------------------------------------------------------------------------


def test_nothing_below_the_opening_threshold() -> None:
    assert run(flat(3.9, 3.9, 3.9, 3.9)).events.empty


def test_a_short_crossing_needs_persistence_or_a_spike() -> None:
    assert run(flat(5.0)).events.empty  # one hour, below the spike level
    assert run(flat(5.0, 5.0)).events.empty  # two flagged hours < min_hours
    assert hours(run(flat(5.0, 5.0, 5.0))) == [("high", 10, 3)]
    spike = run(flat(9.0))
    assert hours(spike) == [("high", 10, 1)]
    assert spike.events["peak_z"].iloc[0] == pytest.approx(9.0)


def test_hysteresis_keeps_an_event_open_between_the_two_thresholds() -> None:
    detected = run(flat(4.5, 3.0, 3.0, 2.1, 1.0, 3.5))

    # Opens at 4.5, continues while >= 2; 1.0 is a one-hour gap, bridged; 3.5 continues it.
    assert hours(detected) == [("high", 10, 6)]
    assert detected.events["flagged_hours"].iloc[0] == 5


def test_adjacent_windows_merge_across_short_gaps_only() -> None:
    assert hours(run(flat(5, 5, 5, 0, 0, 5, 5, 5))) == [("high", 10, 8)]
    assert hours(run(flat(5, 5, 5, 0, 0, 0, 5, 5, 5))) == [("high", 10, 3), ("high", 16, 3)]
    config = DetectorConfig(max_gap_hours=0)
    assert hours(run(flat(5, 5, 5, 0, 5, 5, 5), config)) == [("high", 10, 3), ("high", 14, 3)]


def test_missing_hours_are_bridged_like_gaps_and_counted() -> None:
    detected = run(flat(5, 5, 5, 5, 5, 5, 5, 5), drop=(13, 14))

    assert hours(detected) == [("high", 10, 8)]
    assert detected.events["missing_hours"].iloc[0] == 2
    assert detected.events["flagged_hours"].iloc[0] == 6


def test_high_and_low_deviations_are_separate_events() -> None:
    detected = run(flat(5, 5, 5, -5, -5, -5))

    assert hours(detected) == [("high", 10, 3), ("low", 13, 3)]
    low = detected.events[detected.events["direction"] == "low"].iloc[0]
    assert low["peak_z"] == pytest.approx(5.0) and low["residual_sum"] < 0


def test_an_event_records_its_extent_peak_and_residual_sum() -> None:
    e = run(flat(4.5, 7.0, 5.0)).events.iloc[0]

    first = START + timedelta(hours=CALIBRATION_HOURS + 10)
    assert e["start"] == first and e["end"] == first + timedelta(hours=3)
    assert e["peak_time"] == first + timedelta(hours=1)
    assert e["peak_residual"] == pytest.approx(7.0 * MAD_TO_SIGMA, abs=1e-3)
    assert e["residual_sum"] == pytest.approx(16.5 * MAD_TO_SIGMA, abs=1e-3)
    assert e["meter_id"] == "m1" and e["building_id"] == "B1" and not e["ongoing"]


def test_an_event_running_to_the_end_of_the_window_is_ongoing() -> None:
    last = 3 * WEEK - 1
    detected = run({last - 2: 5.0, last - 1: 5.0, last: 5.0})

    assert detected.events["ongoing"].tolist() == [True]


# ---------------------------------------------------------------------------
# Long events and the pre-event reference
# ---------------------------------------------------------------------------


def absorbing(config: DetectorConfig | None) -> Detection:
    """A 3-week step of +50 where the model 'learns' the anomaly after one week: its expected
    value follows the readings from then on, so model residuals vanish."""
    frame, expected, calibration, detection = meter(detection_hours=5 * WEEK)
    step = slice(CALIBRATION_HOURS + 24, CALIBRATION_HOURS + 24 + 3 * WEEK)
    values = frame["value"].to_numpy().copy()
    values[step] += 50.0
    frame["value"] = values
    absorbed = expected.copy()
    absorbed.iloc[step.start + WEEK : step.stop] = values[step.start + WEEK : step.stop]
    cal = calibrate(frame, absorbed, calibration, config)
    return detect(frame, absorbed, cal, detection, config)


def test_one_long_event_stays_one_event_after_the_model_absorbs_it() -> None:
    detected = absorbing(DetectorConfig())

    assert hours(detected) == [("high", 24, 3 * WEEK)]
    e = detected.events.iloc[0]
    assert e["reference_hours"] == 2 * WEEK
    assert e["residual_sum"] == pytest.approx(50.0 * 3 * WEEK, rel=1e-6)


def test_without_the_reference_a_long_event_is_cut_off_after_a_week() -> None:
    detected = absorbing(DetectorConfig(horizon_hours=None))

    assert hours(detected) == [("high", 24, WEEK)]
    assert detected.events["reference_hours"].tolist() == [0]


# ---------------------------------------------------------------------------
# Configuration, order and coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"z_on": 2.0, "z_off": 2.0}, {"z_on": 9.0, "z_spike": 8.0}, {"min_hours": 0}],
)
def test_inconsistent_thresholds_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        DetectorConfig(**kwargs)  # type: ignore[arg-type]


def test_events_do_not_depend_on_row_order_and_meters_are_independent() -> None:
    a, _, ca, da = meter(flat(5, 5, 5), meter_id="m1")
    b, _, cb, db = meter(flat(-6, -6, -6, -6, at=40), meter_id="m2")
    frame = pd.concat([a, b], ignore_index=True)
    expected = pd.Series(LEVEL, index=frame.index)
    calibration, detection = np.concatenate([ca, cb]), np.concatenate([da, db])
    order = np.random.default_rng(0).permutation(len(frame))

    first = detect(frame, expected, calibrate(frame, expected, calibration), detection)
    shuffled = frame.iloc[order]
    second = detect(
        shuffled,
        expected.iloc[order],
        calibrate(shuffled, expected.iloc[order], calibration[order]),
        detection[order],
    )

    pd.testing.assert_frame_equal(first.events, second.events)
    assert first.events[["meter_id", "direction"]].values.tolist() == [
        ["m1", "high"],
        ["m2", "low"],
    ]


def test_a_meter_without_calibration_rows_gets_no_scores() -> None:
    frame, expected, _, detection = meter(flat(9, 9, 9))
    nothing = np.zeros(len(frame), dtype=bool)

    detected = detect(frame, expected, calibrate(frame, expected, nothing), detection)

    assert detected.events.empty and detected.scores.empty


# ---------------------------------------------------------------------------
# With the promoted model, and the command line
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Synthetic data with an injected 2-day surge on meter B in the test window, and a
    registry with a model trained and promoted on the same data."""
    readings, weather = synthetic()
    surge = (
        (readings["building_id"] == "B")
        & (readings["timestamp"] >= pd.Timestamp("2017-03-27T00:00Z"))
        & (readings["timestamp"] < pd.Timestamp("2017-03-29T00:00Z"))
    )
    readings.loc[surge, "value"] *= 1.6
    folder = tmp_path_factory.mktemp("data")
    readings.to_parquet(folder / "readings.parquet")
    BUILDINGS.to_parquet(folder / "buildings.parquet")
    weather.to_parquet(folder / "weather.parquet")
    root = tmp_path_factory.mktemp("models")
    trained = train(readings, BUILDINGS, features_of(readings, weather), SPLIT)
    promote(save(trained, root), root)
    return folder, root


def test_detection_with_the_promoted_model_finds_an_injected_surge(
    prepared: tuple[Path, Path],
) -> None:
    folder, root = prepared
    readings = pd.read_parquet(folder / "readings.parquet")
    weather = pd.read_parquet(folder / "weather.parquet")

    result = run_detection(readings, features_of(readings, weather), root)

    events = result.detection.events
    start, end = pd.Timestamp("2017-03-27T00:00Z"), pd.Timestamp("2017-03-29T00:00Z")
    overlapping = events[
        (events["meter_id"] == "B-electricity") & (events["start"] < end) & (events["end"] > start)
    ]
    # One event, exactly the injected window. (The model, trained on two synthetic months, also
    # raises unrelated alarms elsewhere: false-alarm rates are T018's benchmark.)
    assert overlapping[["direction", "start", "end", "flagged_hours"]].values.tolist() == [
        ["high", start, end, 48]
    ]
    assert result.detection_window[0] == SPLIT.time.test_start  # type: ignore[union-attr]
    assert set(result.calibration.rows.index) == {"A-electricity", "B-electricity", "C-electricity"}


def test_the_command_line_writes_identical_outputs_and_needs_a_model(
    prepared: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder, root = prepared
    args = ["--data", str(folder), "--root", str(root)]

    assert main([*args, "--output", str(tmp_path / "one")]) == 0
    assert main([*args, "--output", str(tmp_path / "two")]) == 0

    for name in ("events.csv", "scores.parquet", "summary.json", "report.md"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    summary = json.loads((tmp_path / "one" / "summary.json").read_text(encoding="utf-8"))
    assert summary["events"] >= 1 and summary["detector_version"] == "1"
    assert "not confirmed waste" in summary["interpretation"]
    capsys.readouterr()

    assert main(["--data", str(folder), "--root", str(tmp_path / "empty")]) == 1
    assert "Train and promote one" in capsys.readouterr().err
