from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import at, readings
from wattwise.data.synthetic import generate
from wattwise.ml.baselines import (
    DEFAULT_SPLIT,
    HourOfWeekProfile,
    SeasonalNaive,
    common_rows_comparison,
    default_baselines,
    main,
    run,
)
from wattwise.ml.splits import Chronological, Role, Split, SplitConfig, make_split

WEEK = pd.Timedelta(days=7)


def weekly(buildings: tuple[str, ...] = ("A", "B"), days: int = 35) -> pd.DataFrame:
    """Readings that repeat exactly every week (value = hour of the week + 10 per building)."""
    data = readings(buildings, days=days)
    hour_of_week = data["timestamp"].dt.dayofweek * 24 + data["timestamp"].dt.hour
    offset = data["building_id"].map({b: 10.0 * i for i, b in enumerate(buildings)})
    return data.assign(value=(hour_of_week + offset).astype(float))


def split_for(data: pd.DataFrame, test_start: float = 28, test_end: float = 35) -> Split:
    config = SplitConfig(
        time=Chronological(train_start=at(0), test_start=at(test_start), test_end=at(test_end))
    )
    return make_split(data, config)


# ---------------------------------------------------------------------------
# Seasonal naive: only the past
# ---------------------------------------------------------------------------


def test_seasonal_naive_repeats_last_weeks_reading() -> None:
    data = weekly()
    rows = data[data["timestamp"] >= pd.Timestamp(at(28))]

    predicted = SeasonalNaive().predict(rows.drop(columns="value"), data)

    np.testing.assert_array_equal(predicted.to_numpy(), rows["value"].to_numpy())
    assert predicted.index.equals(rows.index)


def test_seasonal_naive_never_sees_its_own_hour_or_the_future() -> None:
    data = weekly()
    rows = data[data["timestamp"] >= pd.Timestamp(at(28))]
    changed = data.copy()
    changed.loc[changed["timestamp"] >= pd.Timestamp(at(28)), "value"] = (
        1e9  # the present and future
    )

    before = SeasonalNaive().predict(rows.drop(columns="value"), data)
    after = SeasonalNaive().predict(rows.drop(columns="value"), changed)

    pd.testing.assert_series_equal(before, after)


def test_seasonal_naive_has_no_prediction_without_last_weeks_reading() -> None:
    data = weekly()
    first_week = data[data["timestamp"] < pd.Timestamp(at(7))]

    predicted = SeasonalNaive().predict(first_week.drop(columns="value"), data)

    assert predicted.isna().all()
    with pytest.raises(ValueError, match="lag must be positive"):
        SeasonalNaive(lag_hours=0)


# ---------------------------------------------------------------------------
# Hour-of-week profile: only the training rows, in local time
# ---------------------------------------------------------------------------


def test_the_profile_uses_only_training_rows() -> None:
    data = weekly()
    train = data[data["timestamp"] < pd.Timestamp(at(28))]
    rows = data[data["timestamp"] >= pd.Timestamp(at(28))].drop(columns="value")
    profile = HourOfWeekProfile({})
    profile.fit(train)
    expected = profile.predict(rows, data)

    tampered = data.copy()
    tampered.loc[tampered["timestamp"] >= pd.Timestamp(at(28)), "value"] = -1e9
    again = HourOfWeekProfile({})
    again.fit(train)

    pd.testing.assert_series_equal(again.predict(rows, tampered), expected)
    np.testing.assert_array_equal(expected.to_numpy(), data.loc[rows.index, "value"].to_numpy())


def test_the_profile_follows_local_wall_time_across_daylight_saving() -> None:
    # A building open 08:00-18:00 local time in New York, across the March 2017 clock change.
    times = pd.date_range("2017-01-02", "2017-04-03", freq="h", tz="UTC", inclusive="left")
    local = times.tz_convert("US/Eastern")
    open_hours = (local.hour >= 8) & (local.hour < 18) & (local.dayofweek < 5)
    data = pd.DataFrame(
        {
            "timestamp": times.as_unit("us"),
            "meter_id": "N-electricity",
            "building_id": "N",
            "meter_type": "electricity",
            "unit": "kWh",
            "value": np.where(open_hours, 100.0, 10.0),
        }
    )
    train = data[data["timestamp"] < pd.Timestamp("2017-03-06", tz="UTC")]  # winter only
    summer = data[data["timestamp"] >= pd.Timestamp("2017-03-20", tz="UTC")]  # after the change

    local_profile = HourOfWeekProfile({"N": "US/Eastern"})
    local_profile.fit(train)
    utc_profile = HourOfWeekProfile({})
    utc_profile.fit(train)

    local_error = (local_profile.predict(summer, data) - summer["value"]).abs().mean()
    utc_error = (utc_profile.predict(summer, data) - summer["value"]).abs().mean()
    assert local_error == 0.0
    assert utc_error > 0.0, "a UTC profile is an hour off after the change"


def test_the_profile_falls_back_to_the_meter_median_and_skips_unknown_meters() -> None:
    data = weekly(days=14)
    train = data[(data["timestamp"] < pd.Timestamp(at(7))) & (data["building_id"] == "A")]
    train = train[train["timestamp"].dt.dayofweek != 0]  # no Monday slots in training
    rows = data[data["timestamp"] >= pd.Timestamp(at(7))].drop(columns="value")
    profile = HourOfWeekProfile({})
    profile.fit(train)

    predicted = profile.predict(rows, data)

    mondays = (rows["timestamp"].dt.dayofweek == 0) & (rows["building_id"] == "A")
    assert (predicted[mondays] == train["value"].median()).all()
    assert predicted[rows["building_id"] == "B"].isna().all(), "no training data, no forecast"


def test_the_profile_must_be_fitted() -> None:
    with pytest.raises(RuntimeError, match="Fit the profile"):
        HourOfWeekProfile({}).predict(readings(days=1), readings(days=1))


# ---------------------------------------------------------------------------
# Running and scoring
# ---------------------------------------------------------------------------


def test_both_baselines_are_perfect_on_a_purely_weekly_load() -> None:
    data = weekly()
    split = split_for(data)

    reports = run(split, [SeasonalNaive(), HourOfWeekProfile({})], roles=[Role.TEST]).reports

    assert [r.forecaster.name for r in reports] == ["seasonal-naive-1w", "hour-of-week-median"]
    for report in reports:
        (score,) = report.scores
        assert score.overall.mae == 0.0
        assert score.overall.missing_prediction == 0


def test_the_comparison_on_common_rows_scores_only_rows_every_baseline_predicts() -> None:
    data = weekly()
    data.loc[data["timestamp"] == pd.Timestamp(at(22)), "value"] = (
        np.nan
    )  # last week's reading gone
    split = split_for(data)
    result = run(split, [SeasonalNaive(), HourOfWeekProfile({})], roles=[Role.TEST])

    comparison = common_rows_comparison(result)

    rows = {r["forecaster"]: r for r in comparison}
    assert rows["seasonal-naive-1w"]["common_rows"] == rows["hour-of-week-median"]["common_rows"]
    assert rows["seasonal-naive-1w"]["common_rows"] == 2 * 7 * 24 - 2
    assert rows["hour-of-week-median"]["mae"] == 0.0


def test_the_synthetic_fixture_runs_end_to_end() -> None:
    dataset = generate()
    first = dataset.readings["timestamp"].min()
    config = SplitConfig(
        time=Chronological(
            train_start=first.to_pydatetime(),
            validation_start=(first + 5 * WEEK).to_pydatetime(),
            test_start=(first + 6 * WEEK).to_pydatetime(),
            test_end=(first + 8 * WEEK).to_pydatetime(),
        )
    )

    result = run(make_split(dataset.readings, config), default_baselines(dataset.buildings))

    for report in result.reports:
        assert [s.role for s in report.scores] == [Role.VALIDATION, Role.TEST]
        assert all(s.overall.mae is not None for s in report.scores)


def test_cli_writes_one_report_per_baseline(tmp_path: Path) -> None:
    dataset = generate()
    data = tmp_path / "data"
    data.mkdir()
    dataset.readings.to_parquet(data / "readings.parquet")
    dataset.buildings.to_parquet(data / "buildings.parquet")
    start = dataset.readings["timestamp"].min().to_pydatetime()

    code = main(
        [
            "--data",
            str(data),
            "--output",
            str(tmp_path / "out"),
            "--train-start",
            start.isoformat(),
            "--validation-start",
            (start + 5 * WEEK).isoformat(),
            "--test-start",
            (start + 6 * WEEK).isoformat(),
            "--test-end",
            (start + 8 * WEEK).isoformat(),
        ]
    )

    assert code == 0
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == [
        "common_rows.json",
        "hour-of-week-median.json",
        "hour-of-week-median.md",
        "seasonal-naive-1w.json",
        "seasonal-naive-1w.md",
    ]


def test_cli_explains_missing_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--data", str(tmp_path)]) == 1
    assert "Prepare the data first" in capsys.readouterr().err


def test_the_default_split_tests_after_training() -> None:
    (fold,) = DEFAULT_SPLIT.time.folds()

    assert fold.validation is not None
    assert fold.train.end <= fold.validation.start <= fold.test.start
    assert fold.test.start == datetime(2017, 10, 1, tzinfo=UTC)


def test_cli_rejects_split_dates_without_a_time_zone(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--data", str(tmp_path), "--test-start", "2017-10-01T00:00"])
