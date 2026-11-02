import json
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wattwise.ml import lbnl59
from wattwise.ml.detection import rolling_same_hour

FOLDER = "Bldg59_clean data"


def utc(start: str, periods: int, freq: str = "15min") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq=freq, tz="UTC")


# --- suspected interpolation -------------------------------------------------------------


def test_the_filled_points_of_a_sloped_straight_run_are_suspected() -> None:
    noise = [3.1, 2.7, 3.9, 2.2]
    line = [1.0, 1.5, 2.0, 2.5, 3.0]  # five points: two real ends, three filled between them
    values = pd.Series(noise + line + noise)

    flags = lbnl59.suspected_interpolation(values)

    assert flags.tolist() == [False] * 5 + [True] * 3 + [False] * 5


def test_four_points_on_a_line_are_not_enough() -> None:
    values = pd.Series([3.1, 2.7, 1.0, 1.5, 2.0, 2.5, 9.0, 2.2])

    assert not lbnl59.suspected_interpolation(values).any()


def test_a_constant_run_is_kept_because_flat_loads_are_real() -> None:
    values = pd.Series([0.2] * 20)

    assert not lbnl59.suspected_interpolation(values).any()


def test_a_gap_breaks_a_run() -> None:
    values = pd.Series([1.0, 2.0, 3.0, np.nan, 5.0, 6.0, 7.0, 8.0])

    assert not lbnl59.suspected_interpolation(values).any()


# --- reading and the hourly series ---------------------------------------------------------


def test_points_are_read_as_utc_without_the_trailing_comma_column(tmp_path: Path) -> None:
    archive = tmp_path / "b.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(f"{FOLDER}/ele.csv", "date,a,b,\n2018/1/1 1:00,1,2,\n2018-01-01 01:15:00,3,4,\n")
        z.writestr(f"__MACOSX/{FOLDER}/._ele.csv", "junk")

    frame = lbnl59.read_points(archive, "ele.csv")

    assert list(frame.columns) == ["a", "b"]
    assert list(frame.index) == list(utc("2018-01-01 01:00", 2))
    assert frame["b"].tolist() == [2, 4]


def test_off_grid_points_are_dropped_and_missing_slots_are_empty() -> None:
    index = utc("2020-01-01", 4).delete(2).append(pd.DatetimeIndex(["2020-01-01 00:05"], tz="UTC"))
    ele = pd.DataFrame({c: 1.0 for c in lbnl59.END_USES}, index=index).sort_index()

    grid = lbnl59.quarter_hour_grid(ele)

    assert list(grid.index) == list(utc("2020-01-01", 4))
    assert grid["mels_S"].isna().tolist() == [False, False, True, False]


def flat_grid(hours: int, value: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    index = utc("2020-01-01", hours * 4)
    return pd.DataFrame(
        {c: value + rng.uniform(0, 0.1, len(index)) for c in lbnl59.END_USES}, index=index
    )


def test_an_hour_needs_all_four_quarter_hours_of_every_end_use() -> None:
    grid = flat_grid(3)
    grid.iloc[5, 2] = np.nan  # one quarter-hour of mels_N in the second hour

    hourly, _ = lbnl59.hourly_end_uses(grid)

    assert hourly.notna().all(axis=1).tolist() == [True, False, True]


def test_suspected_interpolation_masks_the_hour_for_every_end_use() -> None:
    grid = flat_grid(6)
    grid.iloc[4:12, 0] = np.linspace(1.0, 2.4, 8)  # eight points on a line, hours 1-2

    hourly, summary = lbnl59.hourly_end_uses(grid)

    assert hourly.notna().all(axis=1).tolist() == [True, False, False, True, True, True]
    assert summary["mels_S"]["suspected_interpolation_share"] == round(6 / 24, 4)  # interior
    assert summary["mels_S"]["raw_missing_rate"] == lbnl59.RAW_MISSING_RATE["mels_S"]


def test_end_use_baselines_add_up_to_the_total_baseline() -> None:
    rng = np.random.default_rng(1)
    index = utc("2020-01-01", 24 * 30, "h")
    hourly = pd.DataFrame({c: rng.uniform(1, 5, len(index)) for c in lbnl59.END_USES}, index=index)
    hourly.iloc[100:110] = np.nan

    parts = lbnl59.rolling_baselines(hourly)
    readings = lbnl59.readings_from(hourly)
    _, total = rolling_same_hour(readings)

    summed = parts.sum(axis=1, min_count=len(lbnl59.END_USES)).to_numpy()
    assert np.allclose(summed, total.to_numpy(), equal_nan=True)


# --- dated events --------------------------------------------------------------------------


def dampers(days: int, closed: set[date]) -> pd.DataFrame:
    index = pd.date_range("2020-08-01", periods=days * 24 * 4, freq="15min", tz=lbnl59.TIMEZONE)
    value = np.where([d.date() in closed for d in index], 10.0, 55.0)
    frame = pd.DataFrame({f"rtu_00{i}_oadmpr_pct": value for i in range(1, 5)}, index=index)
    return frame.tz_convert("UTC")


def test_weekdays_with_every_damper_at_minimum_are_found_and_weekends_bridged() -> None:
    closed = {date(2020, 8, 6), date(2020, 8, 7), date(2020, 8, 10), date(2020, 8, 20)}

    days = lbnl59.damper_minimum_days(dampers(31, closed))

    assert days == sorted(closed)
    assert lbnl59.spans(days) == [
        (date(2020, 8, 6), date(2020, 8, 10), 3),
        (date(2020, 8, 20), date(2020, 8, 20), 1),
    ]


def test_one_open_damper_means_not_at_minimum() -> None:
    frame = dampers(10, {date(2020, 8, 4)})
    frame["rtu_004_oadmpr_pct"] = 40.0

    assert lbnl59.damper_minimum_days(frame) == []


def test_events_overlapping_a_window_use_local_dates() -> None:
    events = pd.DataFrame(
        {
            "start": pd.to_datetime(["2020-03-16 06:00", "2020-03-18 08:00"], utc=True),
            "end": pd.to_datetime(["2020-03-17 06:00", "2020-03-20 06:00"], utc=True),
        }
    )

    # 2020-03-17 06:00 UTC is 23:00 on the 16th in Berkeley; 2020-03-18 08:00 UTC is 01:00
    # on the 18th
    assert lbnl59.overlapping(events, date(2020, 3, 17), date(2020, 3, 17)) == []
    assert lbnl59.overlapping(events, date(2020, 3, 16), date(2020, 3, 19)) == [0, 1]


def test_weekly_windows_are_anchored_on_the_date() -> None:
    index = pd.date_range(
        "2020-03-01", "2020-04-01", freq="h", tz=lbnl59.TIMEZONE, inclusive="left"
    )
    total = pd.Series(
        np.where(index < pd.Timestamp("2020-03-17", tz=lbnl59.TIMEZONE), 50.0, 30.0), index=index
    )

    weeks = lbnl59.weekly_around(total.tz_convert("UTC"), date(2020, 3, 17), weeks=2)

    assert [w["mean_kw"] for w in weeks] == [50.0, 50.0, 30.0, 30.0]
    assert weeks[2]["week_from"] == "2020-03-17"


# --- the whole case study ------------------------------------------------------------------


def synthetic_archive(path: Path) -> Path:
    """Ninety days of a regular office with a drop from the shelter-in-place date on, and the
    dampers held at minimum on three weekdays. Synthetic: it tests the plumbing only."""
    index = pd.date_range("2020-01-20", "2020-04-20", freq="15min", tz="UTC", inclusive="left")
    local = index.tz_convert(lbnl59.TIMEZONE)
    rng = np.random.default_rng(7)
    working = (local.dayofweek < 5) & (local.hour >= 8) & (local.hour < 18)
    level = np.where(local >= pd.Timestamp("2020-03-18", tz=lbnl59.TIMEZONE), 0.5, 1.0)
    stamp = index.tz_localize(None).strftime("%Y-%m-%d %H:%M:%S")
    ele = pd.DataFrame({"date": stamp})
    for i, column in enumerate(lbnl59.END_USES):
        base = 2.0 + i + 10.0 * working * level
        ele[column] = np.round(base + rng.normal(0, 0.3, len(index)), 3)
    closed = (
        pd.Series(local.date)
        .isin([date(2020, 2, 4), date(2020, 2, 5), date(2020, 2, 6)])
        .to_numpy()
    )
    damper = pd.DataFrame({"date": stamp})
    for i in range(1, 5):
        damper[f"rtu_00{i}_oadmpr_pct"] = np.where(closed, 10.0, 50.0)
    weather = pd.DataFrame({"date": stamp, "air_temp_set_1": 15.0 + rng.normal(0, 1, len(index))})
    occ = pd.DataFrame({"date": stamp, "occ_third_south": 5.0 * working, "occ_fourth_south": 0.0})
    with zipfile.ZipFile(path, "w") as z:
        for name, frame in {
            "ele.csv": ele,
            "rtu_oa_damper.csv": damper,
            "site_weather.csv": weather,
            "occ.csv": occ,
        }.items():
            z.writestr(f"{FOLDER}/{name}", frame.to_csv(index=False))
    return path


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return lbnl59.run(synthetic_archive(tmp_path_factory.mktemp("lbnl") / "b.zip"))


def test_the_case_study_describes_the_series_and_masking(report: dict) -> None:  # type: ignore[type-arg]
    assert "derived, not a whole-building meter" in report["series"]["definition"]
    assert set(report["masking"]) == set(lbnl59.END_USES)
    assert report["series"]["hours_used"] > 2000


def test_the_drop_shows_in_the_weeks_around_the_order(report: dict) -> None:  # type: ignore[type-arg]
    weeks = report["weeks_around_shelter_in_place"]

    assert weeks[3]["mean_kw"] > weeks[4]["mean_kw"]
    assert weeks[4]["week_from"] == "2020-03-18"


def test_the_authors_events_are_the_dated_windows(report: dict) -> None:  # type: ignore[type-arg]
    authors = [w for w in report["dated_windows"] if w["basis"] == "authors' timeline"]

    assert [w["number"] for w in authors] == [1, 2, 3, 4, 5, 6, 7]
    assert [w["kind"] for w in authors].count("MPC testing") == 4
    shelter = authors[1]
    assert (shelter["start"], shelter["end"]) == ("2020-03-18", "2020-12-31")
    assert shelter["hvac_kw"]["hours"] > 0


def test_the_damper_window_is_found_outside_the_wildfire_windows(report: dict) -> None:  # type: ignore[type-arg]
    damper = [w for w in report["dated_windows"] if w["kind"] == "damper-at-minimum"]

    assert [(w["start"], w["end"], w["days"]) for w in damper] == [("2020-02-04", "2020-02-06", 3)]
    assert damper[0]["in_authors_wildfire_window"] is False
    assert damper[0]["rtu_damper_pct"]["event_mean"] == pytest.approx(10.0)


def test_every_event_breakdown_adds_up(report: dict) -> None:  # type: ignore[type-arg]
    for event in report["events"]:
        parts = sum(event["end_use_deviation_kwh"].values())
        assert parts == pytest.approx(event["deviation_kwh"], abs=0.01)


def test_the_outputs_are_strict_json_and_markdown(report: dict, tmp_path: Path) -> None:  # type: ignore[type-arg]
    paths = lbnl59.write(report, tmp_path)

    json.loads(paths[0].read_text(encoding="utf-8"))  # strict: no NaN
    text = paths[1].read_text(encoding="utf-8")
    assert "Masking: suspected interpolation" in text
    assert "Weeks around the start of shelter-in-place" in text


def test_the_report_keeps_the_narrative_above_the_marker(tmp_path: Path) -> None:
    path = tmp_path / "r.md"
    path.write_text(f"# Narrative\n\n{lbnl59.MARKER}\n\nold\n", encoding="utf-8")

    lbnl59.update_report(path, "new\n")

    assert path.read_text(encoding="utf-8") == f"# Narrative\n\n{lbnl59.MARKER}\n\nnew\n"
    plain = tmp_path / "plain.md"
    plain.write_text("# Plain\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no line"):
        lbnl59.update_report(plain, "x")


def test_a_missing_archive_explains_how_to_get_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert lbnl59.main(["--archive", str(tmp_path / "none.zip")]) == 1
    assert "wattwise.data.dryad fetch lbnl59" in capsys.readouterr().err
