"""T018 benchmark: injections, the rolling z-score, scoring, the tuning rule and a full run on the
synthetic load (not real performance)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import BUILDINGS, SPLIT, features_of, synthetic
from wattwise.ml.benchmark import (
    PATTERNS,
    Injection,
    Inputs,
    Pattern,
    choose,
    inject,
    main,
    outside_alerts,
    plan,
    run_benchmark,
    score_injections,
    summarise,
    windows,
)
from wattwise.ml.detection import DetectorConfig, detect, rolling_same_hour
from wattwise.ml.registry import promote, save, train

T0 = pd.Timestamp("2017-01-02T00:00Z")
WINDOW = (pd.Timestamp("2017-02-01T00:00Z"), pd.Timestamp("2017-03-01T00:00Z"))


def flat_readings(meters: tuple[str, ...] = ("m1", "m2"), days: int = 30) -> pd.DataFrame:
    times = pd.date_range(T0, periods=days * 24, freq="h").as_unit("us")
    return pd.concat(
        [
            pd.DataFrame(
                {"timestamp": times, "meter_id": m, "building_id": m.upper(), "value": 50.0}
            )
            for m in meters
        ],
        ignore_index=True,
    )


def injection(pattern: Pattern, start: str = "2017-01-10T00:00Z", meter: str = "m1") -> Injection:
    return Injection(0, meter, pattern, pd.Timestamp(start), PATTERNS[pattern].hours, 50.0)


def values(frame: pd.DataFrame, meter: str = "m1") -> pd.Series:
    return frame[frame["meter_id"] == meter].set_index("timestamp")["value"]


# ---------------------------------------------------------------------------
# Planning and injecting
# ---------------------------------------------------------------------------


def test_plans_are_deterministic_inside_the_window_and_rotate_patterns() -> None:
    levels = {f"m{i}": 10.0 for i in range(7)}

    first, skipped = plan(levels, WINDOW, replicate=3)
    again, _ = plan(levels, WINDOW, replicate=3)
    other, _ = plan(levels, WINDOW, replicate=4)

    assert first == again and first != other and not skipped
    assert sorted(i.pattern.value for i in first) == sorted(p.value for p in Pattern)
    for i in first:
        assert i.start >= WINDOW[0] + pd.Timedelta(hours=24)
        assert i.end <= WINDOW[1] - pd.Timedelta(hours=24)
    assert {i.meter_id: i.pattern for i in other}["m0"] != {i.meter_id: i.pattern for i in first}[
        "m0"
    ]


def test_patterns_that_do_not_fit_and_meters_without_a_level_are_skipped() -> None:
    short = (WINDOW[0], WINDOW[0] + pd.Timedelta(days=5))
    levels = {f"m{i}": 10.0 for i in range(7)} | {"m7": 0.0}

    planned, skipped = plan(levels, short, replicate=0)

    assert {s["pattern"] for s in skipped} >= {"long_sustained", "overnight", "drift"}
    assert any(s["meter_id"] == "m7" for s in skipped)
    assert all(i.hours <= 72 for i in planned)


def test_additive_patterns_add_a_share_of_the_level_only_inside_their_window() -> None:
    readings = flat_readings()

    spiked = inject(readings, [injection(Pattern.SPIKE)], {})

    diff = values(spiked) - values(readings)
    assert diff[diff != 0].index.tolist() == [
        pd.Timestamp("2017-01-10T00:00Z"),
        pd.Timestamp("2017-01-10T01:00Z"),
    ]
    assert diff.max() == 50.0  # +100% of the level
    assert values(spiked, "m2").equals(values(readings, "m2"))
    assert readings["value"].eq(50.0).all(), "the input is not modified"


def test_overnight_injection_uses_the_buildings_local_night() -> None:
    readings = flat_readings()

    night = inject(readings, [injection(Pattern.OVERNIGHT)], {"M1": "America/New_York"})

    changed = (values(night) - values(readings)).loc[lambda s: s != 0]
    local_hours = set(pd.DatetimeIndex(changed.index).tz_convert("America/New_York").hour)
    assert local_hours == {22, 23, 0, 1, 2, 3, 4, 5}
    assert changed.eq(15.0).all()  # +30% of 50


def test_drift_ramps_from_zero_to_its_magnitude() -> None:
    readings = flat_readings()

    drifted = values(inject(readings, [injection(Pattern.DRIFT)], {})) - 50.0

    window = drifted["2017-01-10T00:00Z":"2017-01-16T23:00Z"]
    assert window.iloc[0] == 0.0 and window.iloc[-1] == pytest.approx(25.0)
    assert (np.diff(window.to_numpy()) > 0).all()


def test_flatline_and_dropout_replace_readings_but_keep_missing_ones() -> None:
    readings = flat_readings()
    readings.loc[readings.index[0 : 24 * 30 : 7], "value"] += np.arange(103)  # vary the readings
    readings.loc[
        (readings["meter_id"] == "m1") & (readings["timestamp"] == "2017-01-10T05:00Z"), "value"
    ] = np.nan

    stuck = values(inject(readings, [injection(Pattern.FLATLINE)], {}))[
        "2017-01-10T00:00Z":"2017-01-10T23:00Z"
    ]
    dropped = values(inject(readings, [injection(Pattern.DROPOUT)], {}))[
        "2017-01-10T00:00Z":"2017-01-11T05:00Z"
    ]

    first = values(readings)["2017-01-10T00:00Z"]
    assert stuck.dropna().eq(first).all() and stuck.isna().sum() == 1
    assert dropped.dropna().eq(0.0).all() and dropped.isna().sum() == 1


# ---------------------------------------------------------------------------
# The rolling same-hour z-score
# ---------------------------------------------------------------------------


def test_the_rolling_z_score_uses_the_same_hour_on_previous_days_only() -> None:
    readings = flat_readings(("m1",), days=30)
    rng = np.random.default_rng(0)
    readings["value"] = 50.0 + rng.normal(0, 3, len(readings))
    series = values(readings)
    t = pd.Timestamp("2017-01-25T13:00Z")

    z, mean = rolling_same_hour(readings)

    past = series[[t - pd.Timedelta(days=d) for d in range(1, 15)]]
    row = readings.index[readings["timestamp"] == t][0]
    assert mean[row] == pytest.approx(past.mean())
    assert z[row] == pytest.approx((series[t] - past.mean()) / past.std(ddof=1))

    later = readings.assign(value=readings["value"].where(readings["timestamp"] <= t, 1e6))
    z_later, _ = rolling_same_hour(later)
    assert z_later[row] == pytest.approx(z[row]), "later readings change nothing"
    early = readings["timestamp"] < T0 + pd.Timedelta(days=7)
    assert z[early].isna().all(), "fewer than 7 previous days"


def test_detect_accepts_precomputed_scores_without_a_reference() -> None:
    readings = flat_readings(("m1",), days=10)
    z = pd.Series(0.0, index=readings.index)
    z.iloc[100:104] = 6.0
    expected = pd.Series(50.0, index=readings.index)
    rows = np.ones(len(readings), dtype=bool)

    found = detect(readings, expected, None, rows, DetectorConfig(horizon_hours=None), z=z)

    assert found.events[["start", "duration_hours"]].values.tolist() == [
        [readings["timestamp"].iloc[100], 4]
    ]
    with pytest.raises(ValueError, match="calibration, or precomputed"):
        detect(readings, expected, None, rows)
    with pytest.raises(ValueError, match="horizon_hours=None"):
        detect(readings, expected, None, rows, DetectorConfig(), z=z)


# ---------------------------------------------------------------------------
# Scoring and choosing
# ---------------------------------------------------------------------------


def events(*rows: tuple[str, str, int, str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "meter_id": meter,
                "start": pd.Timestamp(start),
                "end": pd.Timestamp(start) + pd.Timedelta(hours=hours),
                "signature": signature,
                "signatures": signatures,
            }
            for meter, start, hours, signature, signatures in rows
        ]
    )


def test_an_injection_is_scored_by_the_events_that_overlap_it() -> None:
    sustained = injection(Pattern.SUSTAINED)  # 2017-01-10, 72 h
    found = events(
        ("m1", "2017-01-10T06:00Z", 20, "unclassified", "unclassified"),
        ("m1", "2017-01-11T06:00Z", 40, "sustained", "sustained"),
        ("m2", "2017-01-10T00:00Z", 72, "sustained", "sustained"),  # another meter
    )

    (row,) = score_injections([sustained], found)

    assert row["detected"] and row["events"] == 2
    assert row["latency_hours"] == 6
    assert row["coverage"] == pytest.approx(60 / 72, abs=1e-4)
    assert row["signature"] == "sustained" and row["signature_match"] and row["signature_any"]


def test_a_missed_injection_and_alerts_outside_injections() -> None:
    spike = injection(Pattern.SPIKE)
    found = events(("m1", "2017-01-12T00:00Z", 3, "spike", "spike"))

    (row,) = score_injections([spike], found)

    assert not row["detected"] and row["latency_hours"] is None and row["coverage"] == 0.0
    assert outside_alerts([spike], found) == 1
    assert outside_alerts([spike], found.iloc[:0]) == 0


def test_summaries_give_recall_per_pattern_and_the_alert_rate() -> None:
    scored = [
        {"pattern": "spike", "detected": True, "latency_hours": 0, "coverage": 1.0, "events": 1,
         "signature_match": True, "signature_any": True},
        {"pattern": "spike", "detected": False, "latency_hours": None, "coverage": 0.0,
         "events": 0, "signature_match": False, "signature_any": False},
        {"pattern": "drift", "detected": True, "latency_hours": 40, "coverage": 0.5, "events": 2,
         "signature_match": False, "signature_any": True},
    ]  # fmt: skip

    result = summarise(scored, alerts=6, meter_weeks=12.0)

    assert result["patterns"]["spike"]["recall"] == 0.5
    assert result["patterns"]["drift"]["median_latency_hours"] == 40
    assert result["mean_recall"] == 0.75
    assert result["alerts_per_meter_week"] == 0.5


def test_the_setting_with_the_best_recall_within_the_budget_is_chosen() -> None:
    results = [
        {"mean_recall": 0.9, "alerts_per_meter_week": 2.0},
        {"mean_recall": 0.7, "alerts_per_meter_week": 0.4},
        {"mean_recall": 0.7, "alerts_per_meter_week": 0.3},
        {"mean_recall": 0.5, "alerts_per_meter_week": 0.1},
    ]

    assert choose(results, budget=0.5) == (2, True)  # tie on recall: fewer alerts
    assert choose(results, budget=0.05) == (3, False)  # none within: the fewest alerts


# ---------------------------------------------------------------------------
# A full run on the synthetic load
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> tuple[Inputs, Path]:
    readings, weather = synthetic()
    root = tmp_path_factory.mktemp("models")
    trained = train(readings, BUILDINGS, features_of(readings, weather), SPLIT)
    promote(save(trained, root), root)
    return Inputs(readings, BUILDINGS, weather, None), root


def test_windows_split_the_test_window_into_tuning_and_evaluation(
    registry: tuple[Inputs, Path],
) -> None:
    calibration, tuning, evaluation = windows(registry[1])

    assert calibration == (pd.Timestamp("2017-03-01T00:00Z"), pd.Timestamp("2017-03-22T00:00Z"))
    assert tuning[0] == calibration[1] and tuning[1] == evaluation[0]
    assert evaluation[1] == pd.Timestamp("2017-04-11T00:00Z")
    assert tuning[1] - tuning[0] == pd.Timedelta(hours=160)  # a third of 20 days, whole hours


def test_a_benchmark_run_is_complete_and_reproducible(registry: tuple[Inputs, Path]) -> None:
    inputs, root = registry
    grid = [
        {"z_on": 4.0, "z_off": 2.0, "min_hours": 3},
        {"z_on": 8.0, "z_off": 3.0, "min_hours": 6},
    ]

    first = run_benchmark(inputs, root, replicates=2, grid=grid, log=lambda _: None)
    second = run_benchmark(inputs, root, replicates=2, grid=grid, log=lambda _: None)

    assert json.dumps(first, default=str) == json.dumps(second, default=str)
    assert first["label"].startswith("synthetic benchmark")
    assert (
        set(first["tuning"]) == {"model", "model-adaptive", "rolling-z"}
        and len(first["tuning"]["model"]) == 2
    )
    assert set(first["evaluation"]["model"]) == {"chosen", "t016_default"}
    skipped = {s["pattern"] for s in first["skipped_injections"]["tuning"]}
    assert "long_sustained" in skipped, "14 days cannot fit a 160-hour tuning window"
    assert isinstance(first["decision"]["keep_model_detector"], bool)


def test_the_command_line_writes_the_report_and_needs_a_model(
    registry: tuple[Inputs, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs, root = registry
    folder = tmp_path / "data"
    folder.mkdir()
    inputs.readings.to_parquet(folder / "readings.parquet")
    inputs.buildings.to_parquet(folder / "buildings.parquet")
    assert inputs.weather is not None
    inputs.weather.to_parquet(folder / "weather.parquet")
    output = tmp_path / "out"

    code = main(["--data", str(folder), "--root", str(root), "--replicates", "1",
                 "--output", str(output)])  # fmt: skip

    assert code == 0
    report = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    assert report["replicates_per_window"] == 1 and len(report["tuning"]["model"]) == 16
    assert "synthetic benchmark" in (output / "benchmark.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["--data", str(folder), "--root", str(tmp_path / "none")]) == 1
    assert "error:" in capsys.readouterr().err


def test_the_decision_needs_the_budget_to_hold_out_of_sample(
    registry: tuple[Inputs, Path],
) -> None:
    inputs, root = registry
    grid = [{"z_on": 4.0, "z_off": 2.0, "min_hours": 3}]

    loose = run_benchmark(inputs, root, replicates=1, budget=100.0, grid=grid, log=lambda _: None)
    tight = run_benchmark(inputs, root, replicates=1, budget=1e-9, grid=grid, log=lambda _: None)

    for report in (loose, tight):
        d = report["decision"]
        assert d["keep_model_detector"] == (
            d["first_rule_result"] and d["model_within_budget_on_evaluation"]
        )
    assert tight["decision"]["keep_model_detector"] is False
    assert tight["decision"]["model_within_budget_on_evaluation"] is False
    best = loose["best_tuning_recall_within_alert_rate"]
    assert set(best) == {"model", "model-adaptive", "rolling-z"} and set(best["model"]) == {
        "0.2",
        "0.3",
        "0.5",
        "1",
    }


def test_every_model_detector_gets_its_own_decision_against_the_rolling_z_score(
    registry: tuple[Inputs, Path],
) -> None:
    inputs, root = registry
    grid = [{"z_on": 4.0, "z_off": 2.0, "min_hours": 3}]

    report = run_benchmark(inputs, root, replicates=1, budget=1e-9, grid=grid, log=lambda _: None)

    candidates = report["decision"]["candidates"]
    assert set(candidates) == {"model", "model-adaptive"}
    for result in candidates.values():
        assert result["keep"] == (
            result["higher_recall_than_rolling_z"]
            and result["within_budget_in_tuning"]
            and result["within_budget_on_evaluation"]
        )
        assert result["keep"] is False  # nothing meets a zero budget


# ---------------------------------------------------------------------------
# Full-scale equivalences (T044b): the same results, in time that scales
# ---------------------------------------------------------------------------


def _reference_inject(
    readings: pd.DataFrame, injections: list[Injection], timezones: dict[str, str]
) -> pd.DataFrame:
    """The original implementation, which compared every row to every injection's meter."""
    from wattwise.ml.signatures import SignatureConfig

    night_hours = SignatureConfig().night_hours
    out = readings["value"].to_numpy(dtype=float).copy()
    times = pd.DatetimeIndex(readings["timestamp"])
    meters = readings["meter_id"].astype(str).to_numpy()
    buildings = readings["building_id"].astype(str).to_numpy()
    for inj in injections:
        rows = np.flatnonzero((meters == inj.meter_id) & (times >= inj.start) & (times < inj.end))
        if rows.size == 0:
            continue
        spec = PATTERNS[inj.pattern]
        amount = spec.magnitude * inj.level
        if inj.pattern in (Pattern.SPIKE, Pattern.SUSTAINED, Pattern.LONG_SUSTAINED):
            out[rows] += amount
        elif inj.pattern is Pattern.OVERNIGHT:
            local = times[rows].tz_convert(timezones.get(buildings[rows[0]], "UTC"))
            out[rows[np.isin(local.hour, night_hours)]] += amount
        elif inj.pattern is Pattern.DRIFT:
            elapsed = np.asarray((times[rows] - inj.start) / pd.Timedelta(hours=1), dtype=float)
            out[rows] += amount * elapsed / max(spec.hours - 1, 1)
        elif inj.pattern is Pattern.FLATLINE:
            first = out[rows[0]]
            stuck = first if np.isfinite(first) else inj.level
            out[rows] = np.where(np.isnan(out[rows]), np.nan, stuck)
        else:
            out[rows] = np.where(np.isnan(out[rows]), np.nan, 0.0)
    return readings.assign(value=out)


def test_the_indexed_injection_equals_the_original_for_every_pattern() -> None:
    rng = np.random.default_rng(2)
    readings = flat_readings(("m1", "m2", "m3"), days=40).sample(frac=1.0, random_state=4)
    readings["value"] = rng.normal(50, 5, len(readings))
    readings.loc[readings.sample(frac=0.02, random_state=1).index, "value"] = np.nan
    starts = ("2017-01-10T00:00Z", "2017-01-15T06:00Z", "2017-01-20T00:00Z")
    injections = [
        injection(pattern, start, meter)
        for i, pattern in enumerate(Pattern)
        for meter, start in [(("m1", "m2", "m3")[i % 3], starts[i % 3])]
    ]
    zones = {"M1": "America/New_York", "M2": "Europe/London", "M3": "UTC"}

    fast = inject(readings, injections, zones)
    slow = _reference_inject(readings, injections, zones)

    pd.testing.assert_frame_equal(fast, slow)
    assert (fast["value"].fillna(-1) != readings["value"].fillna(-1)).any()  # something changed


def test_features_on_a_history_margin_equal_features_on_the_whole_series() -> None:
    from wattwise.ml.benchmark import FEATURE_MARGIN, HISTORY_MARGIN
    from wattwise.ml.features import build_features

    readings, weather = synthetic()
    window = (pd.Timestamp("2017-03-25T00:00Z"), pd.Timestamp("2017-04-08T00:00Z"))
    times = readings["timestamp"]
    needed = ((times >= window[0] - HISTORY_MARGIN) & (times < window[1])).to_numpy()
    kept = ((times >= window[0] - HISTORY_MARGIN - FEATURE_MARGIN) & (times < window[1])).to_numpy()
    assert readings["timestamp"].min() <= window[0] - HISTORY_MARGIN - FEATURE_MARGIN  # real margin

    whole = build_features(readings, BUILDINGS, weather, None)
    cut = build_features(readings[kept], BUILDINGS, weather, None)

    rows = readings.index[needed]
    pd.testing.assert_frame_equal(cut.loc[rows], whole.loc[rows])
