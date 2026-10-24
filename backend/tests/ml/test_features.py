import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.ml.conftest import HOUR, JAN, readings
from wattwise.data.bdg2_sites import Region
from wattwise.ml.features import (
    ALL_GROUPS,
    FEATURE_SET_VERSION,
    FEATURES,
    FeatureConfig,
    Group,
    build_features,
    feature_manifest,
    feature_names,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGIONS = {"S1": Region(country="US", subdivision="NY"), "S2": None}
HISTORY = feature_names([Group.HISTORY])
CONDITIONS = feature_names([g for g in Group if g is not Group.HISTORY])


def buildings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "building_id": ["A", "B"],
            "site_id": ["S1", "S2"],
            "timezone": ["America/New_York", "Europe/London"],
            "latitude": [40.7, np.nan],
            "longitude": [-74.0, np.nan],
        }
    )


def noisy_readings(days: int = 40, seed: int = 1) -> pd.DataFrame:
    frame = readings(("A", "B"), days=days)
    rng = np.random.default_rng(seed)
    return frame.assign(value=rng.uniform(10, 100, len(frame)))


def site_hours(sites: tuple[str, ...], days: int = 40) -> pd.DataFrame:
    times = pd.date_range(JAN, periods=days * 24, freq="h").as_unit("us")
    return pd.concat(
        [pd.DataFrame({"site_id": s, "timestamp": times}) for s in sites], ignore_index=True
    )


def weather(days: int = 40, seed: int = 2) -> pd.DataFrame:
    frame = site_hours(("S1", "S2"), days)
    rng = np.random.default_rng(seed)
    return frame.assign(
        air_temperature_c=rng.uniform(-5, 25, len(frame)),
        dew_temperature_c=rng.uniform(-10, 0, len(frame)),
        wind_speed_m_s=rng.uniform(0, 10, len(frame)),
    )


def enrichment(days: int = 40, seed: int = 3) -> pd.DataFrame:
    """ERA5 for S1 only (S2 has no coordinates); humidity for both."""
    frame = site_hours(("S1", "S2"), days)
    rng = np.random.default_rng(seed)
    era5 = (frame["site_id"] == "S1").to_numpy()
    return frame.assign(
        ghi_w_m2_era5=np.where(era5, rng.uniform(0, 800, len(frame)), np.nan),
        cloud_cover_pct_era5=np.where(era5, rng.uniform(0, 100, len(frame)), np.nan),
        relative_humidity_pct_derived=rng.uniform(20, 100, len(frame)),
    )


def build(
    data: pd.DataFrame | None = None,
    weather_table: pd.DataFrame | None = None,
    enrichment_table: pd.DataFrame | None = None,
    horizon: int = 168,
) -> pd.DataFrame:
    return build_features(
        noisy_readings() if data is None else data,
        buildings(),
        weather() if weather_table is None else weather_table,
        enrichment() if enrichment_table is None else enrichment_table,
        regions=REGIONS,
        config=FeatureConfig(horizon_hours=horizon),
    )


def changed_rows(before: pd.DataFrame, after: pd.DataFrame) -> pd.Series:
    same = (before == after) | (before.isna() & after.isna())
    return ~same.all(axis=1)


# ---------------------------------------------------------------------------
# The feature list
# ---------------------------------------------------------------------------


def test_the_feature_list_is_versioned_unique_and_matches_the_output() -> None:
    names = [f.name for f in FEATURES]
    features = build()

    assert FEATURE_SET_VERSION == "1"
    assert len(names) == len(set(names))
    assert {f.group for f in FEATURES} == set(Group)
    assert list(features.columns) == names == feature_names()
    assert (features.dtypes == "float64").all()
    assert features.index.equals(noisy_readings().index)


def test_groups_select_columns_in_the_fixed_order() -> None:
    only = build_features(
        noisy_readings(),
        buildings(),
        config=FeatureConfig(groups=(Group.HISTORY, Group.CALENDAR)),
    )

    assert list(only.columns) == feature_names([Group.CALENDAR, Group.HISTORY])
    assert only.columns[0] == "hour_local"


@pytest.mark.parametrize("horizon", [0, -1, 169])
def test_horizons_that_would_leak_or_drop_history_are_refused(horizon: int) -> None:
    with pytest.raises(ValueError, match="horizon_hours"):
        FeatureConfig(horizon_hours=horizon)


def test_each_group_at_most_once() -> None:
    with pytest.raises(ValueError, match="at most once"):
        FeatureConfig(groups=(Group.SUN, Group.SUN))
    with pytest.raises(ValueError, match="at least one"):
        FeatureConfig(groups=())


def test_the_manifest_records_version_settings_and_provenance() -> None:
    manifest = feature_manifest(FeatureConfig(horizon_hours=24, groups=(Group.WEATHER,)))

    assert manifest["feature_set_version"] == FEATURE_SET_VERSION
    assert manifest["horizon_hours"] == 24
    assert manifest["groups"] == ["weather"]
    assert manifest["holidays_package_version"] == "0.106"
    features = manifest["features"]
    assert isinstance(features, list)
    assert [f["name"] for f in features] == feature_names([Group.WEATHER])
    assert {f["source"] for f in features} == {"observed", "derived", "modelled", "computed"}


def test_the_documented_feature_list_matches_the_code() -> None:
    doc = (REPO_ROOT / "docs" / "FEATURES.md").read_text(encoding="utf-8")
    rows = {
        cells[1].strip("` "): [c.strip() for c in cells[2:5]]
        for cells in (line.split("|") for line in doc.splitlines() if line.startswith("| `"))
    }

    assert f"Feature set version: **{FEATURE_SET_VERSION}**" in doc
    assert rows == {f.name: [f.group.value, f.source.value, f.unit] for f in FEATURES}


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("horizon", [1, 24, 168])
def test_readings_inside_the_horizon_never_change_a_feature(horizon: int) -> None:
    """Rewrite every reading from a cutoff on: no feature before cutoff + horizon may change, and
    history features must change from exactly cutoff + horizon (so the test is not vacuous)."""
    data = noisy_readings()
    cutoff = pd.Timestamp(JAN + timedelta(days=20, hours=5))
    later = data["timestamp"] >= cutoff
    rewritten = data.copy()
    rewritten.loc[later, "value"] = np.random.default_rng(9).uniform(1e3, 1e4, int(later.sum()))

    changed = changed_rows(build(data, horizon=horizon), build(rewritten, horizon=horizon))

    times = data.loc[changed, "timestamp"]
    assert times.min() == cutoff + pd.Timedelta(hours=horizon)
    assert not changed[data["timestamp"] < cutoff + pd.Timedelta(hours=horizon)].any()


def test_a_reading_never_enters_its_own_features() -> None:
    data = noisy_readings()
    target = (data["meter_id"] == "A-electricity") & (data["timestamp"] == JAN + 25 * 24 * HOUR)
    for replacement in (np.nan, 1e6):
        rewritten = data.copy()
        rewritten.loc[target, "value"] = replacement

        changed = changed_rows(build(data), build(rewritten))

        assert not changed[target].any()
        assert changed.any(), "the rewritten reading does feed later rows' features"


def test_later_weather_never_changes_a_feature() -> None:
    cutoff = pd.Timestamp(JAN + timedelta(days=20, hours=5))
    w, e = weather(), enrichment()
    w2, e2 = w.copy(), e.copy()
    w2.loc[w2["timestamp"] > cutoff, "air_temperature_c"] += 30.0
    e2.loc[e2["timestamp"] > cutoff, ["ghi_w_m2_era5", "relative_humidity_pct_derived"]] *= 0.5

    data = noisy_readings()
    changed = changed_rows(build(data, w, e), build(data, w2, e2))

    assert data.loc[changed, "timestamp"].min() == cutoff + pd.Timedelta(hours=1)


def test_conditions_do_not_depend_on_consumption() -> None:
    data = noisy_readings()
    rewritten = data.assign(value=data["value"] * 3 + 7)

    assert build(data)[CONDITIONS].equals(build(rewritten)[CONDITIONS])


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


def value_at(data: pd.DataFrame, meter: str, when: datetime) -> float:
    rows = data[(data["meter_id"] == meter) & (data["timestamp"] == when)]
    return float(rows["value"].iloc[0]) if len(rows) else float("nan")


def test_lags_and_rolling_statistics_match_their_definitions() -> None:
    data = noisy_readings()
    horizon = 24
    features = build(data, horizon=horizon)
    t = JAN + timedelta(days=30, hours=7)
    row = features[(data["meter_id"] == "A-electricity") & (data["timestamp"] == t)].iloc[0]
    meter = data[data["meter_id"] == "A-electricity"].set_index("timestamp")["value"]
    day = meter[t - (horizon + 23) * HOUR : t - horizon * HOUR]
    week = meter[t - (horizon + 167) * HOUR : t - horizon * HOUR]

    assert len(day) == 24 and len(week) == 168
    assert row["lag_168h"] == value_at(data, "A-electricity", t - 168 * HOUR)
    assert row["lag_336h"] == value_at(data, "A-electricity", t - 336 * HOUR)
    assert row["same_hour_mean_4w"] == pytest.approx(
        np.mean([value_at(data, "A-electricity", t - 168 * w * HOUR) for w in (1, 2, 3, 4)])
    )
    assert row["rolling_mean_24h"] == pytest.approx(day.mean())
    assert row["rolling_mean_168h"] == pytest.approx(week.mean())
    assert row["rolling_std_168h"] == pytest.approx(week.std(ddof=1))
    assert row["rolling_min_168h"] == week.min()


def test_missing_history_gives_nan_not_a_guess() -> None:
    data = noisy_readings()
    t = JAN + timedelta(days=30, hours=7)
    a = data["meter_id"] == "A-electricity"
    gap = a & (data["timestamp"] == t - 168 * HOUR)
    sparse_day = a & (data["timestamp"] > t - 192 * HOUR) & (data["timestamp"] <= t - 179 * HOUR)
    weeks = a & data["timestamp"].isin([t - 504 * HOUR, t - 672 * HOUR, t - 336 * HOUR])
    data = data[~(gap | sparse_day | weeks)]  # rows dropped, not set to NaN

    row = build(data).loc[(data["meter_id"] == "A-electricity") & (data["timestamp"] == t)].iloc[0]

    assert np.isnan(row["lag_168h"]) and np.isnan(row["lag_336h"])
    assert np.isnan(row["same_hour_mean_4w"]), "0 of 4 weeks observed"
    assert np.isnan(row["rolling_mean_24h"]), "14 of 24 hours missing"
    assert not np.isnan(row["rolling_mean_168h"]), "still more than half of the week observed"


def test_the_first_hours_have_no_history() -> None:
    features = build()

    first_week = noisy_readings()["timestamp"] < JAN + 168 * HOUR
    assert features.loc[first_week, HISTORY].isna().all().all()


def test_missing_weather_is_explicit() -> None:
    gap_time = JAN + timedelta(days=5, hours=3)
    w = weather()
    w = w[~((w["site_id"] == "S1") & (w["timestamp"] == gap_time))]
    data = noisy_readings()
    features = build(data, w)
    at_gap = (data["building_id"] == "A") & (data["timestamp"] == gap_time)
    row = features[at_gap].iloc[0]

    assert np.isnan(row["air_temperature_c"]) and row["weather_observed"] == 0.0
    assert np.isnan(row["heating_degrees_c"]) and np.isnan(row["cooling_degrees_c"])
    assert not np.isnan(row["air_temperature_mean_24h_c"]), "23 of 24 hours observed"
    assert features.loc[~at_gap, "weather_observed"].eq(1.0).all()


def test_era5_is_flagged_per_site_and_humidity_comes_from_the_enrichment() -> None:
    data = noisy_readings()
    features = build(data)
    a = (data["building_id"] == "A").to_numpy()

    assert features.loc[a, "era5_available"].eq(1.0).all()
    assert features.loc[~a, "era5_available"].eq(0.0).all()
    assert features.loc[~a, "ghi_w_m2_era5"].isna().all()
    assert features["relative_humidity_pct_derived"].notna().all()


def test_without_weather_tables_the_weather_features_are_missing_and_flagged() -> None:
    features = build_features(noisy_readings(), buildings(), regions=REGIONS)
    weather_values = [
        f.name for f in FEATURES if f.group is Group.WEATHER and not f.unit.startswith("0/1")
    ]

    assert features[weather_values].isna().all().all()
    assert features[["weather_observed", "era5_available"]].eq(0.0).all().all()


def test_the_24_hour_temperature_mean_needs_half_its_window() -> None:
    t = JAN + timedelta(days=10)
    w = weather()
    window = (w["timestamp"] > t - 24 * HOUR) & (w["timestamp"] <= t)
    keep_11 = window & (w["timestamp"] > t - 11 * HOUR)
    keep_12 = window & (w["timestamp"] > t - 12 * HOUR)
    data = noisy_readings()
    at = (data["building_id"] == "A") & (data["timestamp"] == t)

    eleven = build(data, w[~window | keep_11]).loc[at, "air_temperature_mean_24h_c"].iloc[0]
    twelve = build(data, w[~window | keep_12]).loc[at, "air_temperature_mean_24h_c"].iloc[0]

    assert np.isnan(eleven)
    s1 = w[(w["site_id"] == "S1") & keep_12]["air_temperature_c"]
    assert twelve == pytest.approx(s1.mean())


def test_calendar_features_use_local_time_across_daylight_saving() -> None:
    times = pd.DatetimeIndex(["2017-03-12T06:00Z", "2017-03-12T07:00Z", "2017-03-13T03:00Z"])
    data = pd.DataFrame(
        {
            "timestamp": list(times) * 2,
            "meter_id": ["ny"] * 3 + ["az"] * 3,
            "building_id": ["NY"] * 3 + ["AZ"] * 3,
            "value": 1.0,
        }
    ).astype({"timestamp": "datetime64[us, UTC]"})
    sites = pd.DataFrame(
        {
            "building_id": ["NY", "AZ"],
            "site_id": ["S1", "S3"],
            "timezone": ["America/New_York", "America/Phoenix"],
        }
    )

    features = build_features(data, sites, config=FeatureConfig(groups=(Group.CALENDAR,)))

    # New York springs forward at 02:00 local on 12 March 2017; Phoenix has no daylight saving.
    assert features["hour_local"].tolist() == [1.0, 3.0, 23.0, 23.0, 0.0, 20.0]
    assert features["day_of_week_local"].tolist() == [6.0, 6.0, 6.0, 5.0, 6.0, 6.0]
    assert features["is_weekend_local"].tolist() == [1.0] * 6
    assert features["day_of_year_local"].tolist() == [71.0, 71.0, 71.0, 70.0, 71.0, 71.0]
    assert features["hour_sin"].iloc[0] == pytest.approx(np.sin(2 * np.pi / 24))


@pytest.mark.parametrize(
    ("timezone", "region", "utc", "expected"),
    [
        ("America/Los_Angeles", Region(country="US", subdivision="CA"), "2016-07-05T03:00Z", 1.0),
        ("America/Los_Angeles", Region(country="US", subdivision="CA"), "2016-07-05T08:00Z", 0.0),
        ("Europe/London", Region(country="GB", subdivision="ENG"), "2016-08-29T12:00Z", 1.0),
        ("Europe/London", Region(country="GB", subdivision="ENG"), "2016-08-30T12:00Z", 0.0),
        ("Europe/Dublin", Region(country="IE"), "2016-03-17T12:00Z", 1.0),
        ("America/Toronto", Region(country="CA", subdivision="ON"), "2016-02-15T17:00Z", 1.0),
        ("America/New_York", Region(country="US", subdivision="DC"), "2016-04-15T17:00Z", 1.0),
    ],
)
def test_holidays_follow_the_local_date_and_the_sites_region(
    timezone: str, region: Region, utc: str, expected: float
) -> None:
    data = pd.DataFrame(
        {"timestamp": [pd.Timestamp(utc)], "meter_id": "m", "building_id": "X", "value": 1.0}
    ).astype({"timestamp": "datetime64[us, UTC]"})
    sites = pd.DataFrame({"building_id": ["X"], "site_id": ["S"], "timezone": [timezone]})

    features = build_features(
        data, sites, regions={"S": region}, config=FeatureConfig(groups=(Group.HOLIDAY,))
    )

    assert features["is_public_holiday"].tolist() == [expected]
    assert features["holiday_region_known"].tolist() == [1.0]


def test_an_unknown_region_has_no_holiday_value() -> None:
    data = noisy_readings()
    features = build(data)
    b = (data["building_id"] == "B").to_numpy()

    assert features.loc[b, "is_public_holiday"].isna().all()
    assert features.loc[b, "holiday_region_known"].eq(0.0).all()
    assert features.loc[~b, "is_public_holiday"].notna().all()
    new_years_day = (~b) & (data["timestamp"] == JAN + 12 * HOUR).to_numpy()
    assert features.loc[new_years_day, "is_public_holiday"].tolist() == [1.0]


def test_a_region_without_a_holiday_calendar_is_an_error() -> None:
    with pytest.raises(ValueError, match="no holiday calendar"):
        build_features(noisy_readings(), buildings(), regions={"S1": Region(country="XX")})


def test_sun_features_come_from_coordinates_and_are_missing_without_them() -> None:
    data = noisy_readings()
    features = build(data)
    a = (data["building_id"] == "A").to_numpy()
    noon = a & (data["timestamp"] == JAN + 17 * HOUR).to_numpy()  # about 12:00 in New York
    night = a & (data["timestamp"] == JAN + 5 * HOUR).to_numpy()

    assert (
        features.loc[~a, ["solar_elevation_deg", "is_daylight", "day_length_h"]].isna().all().all()
    )
    assert features.loc[noon, "solar_elevation_deg"].iloc[0] == pytest.approx(26.0, abs=1.0)
    assert features.loc[noon, "is_daylight"].iloc[0] == 1.0
    assert features.loc[night, "is_daylight"].iloc[0] == 0.0
    jan_1 = a & (data["timestamp"] >= JAN + 5 * HOUR) & (data["timestamp"] < JAN + 29 * HOUR)
    assert features.loc[jan_1, "day_length_h"].nunique() == 1, "one value per local date"
    # New York, 1 January 2017: sunrise 07:20, sunset 16:39.
    assert features.loc[jan_1, "day_length_h"].iloc[0] == pytest.approx(9 + 19 / 60, abs=0.15)


# ---------------------------------------------------------------------------
# Determinism and inputs
# ---------------------------------------------------------------------------


def test_features_are_deterministic_and_independent_of_row_order() -> None:
    data = noisy_readings()
    shuffled = data.sample(frac=1.0, random_state=4)

    first, second = build(data), build(data)
    reordered = build(shuffled)

    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(reordered.loc[data.index], first)


def test_empty_readings_give_an_empty_table() -> None:
    features = build_features(noisy_readings().iloc[:0], buildings())

    assert features.empty and list(features.columns) == feature_names()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.drop(columns="value"), "lack columns"),
        (lambda d: d.assign(timestamp=d["timestamp"].dt.tz_localize(None)), "timezone-aware UTC"),
        (lambda d: d.assign(timestamp=d["timestamp"].dt.tz_convert("Europe/Paris")), "UTC"),
        (lambda d: d.assign(timestamp=d["timestamp"] + pd.Timedelta(minutes=30)), "whole-hour"),
        (lambda d: pd.concat([d, d.iloc[:1]]), "more than one value"),
        (lambda d: d.assign(building_id="Z"), "not in the buildings table"),
    ],
)
def test_bad_readings_are_refused(
    change: Callable[[pd.DataFrame], pd.DataFrame], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_features(change(noisy_readings()), buildings())


def test_bad_weather_and_buildings_are_refused() -> None:
    w = weather()
    with pytest.raises(ValueError, match="weather: more than one row"):
        build(weather_table=pd.concat([w, w.iloc[:1]]))
    e = enrichment().assign(timestamp=lambda f: f["timestamp"] + pd.Timedelta(minutes=10))
    with pytest.raises(ValueError, match=r"enrichment: .*whole-hour"):
        build(enrichment_table=e)
    with pytest.raises(ValueError, match="more than once"):
        build_features(noisy_readings(), pd.concat([buildings(), buildings()]))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_the_command_line_writes_identical_outputs_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    noisy_readings().to_parquet(data_dir / "readings.parquet")
    buildings().to_parquet(data_dir / "buildings.parquet")
    weather().to_parquet(data_dir / "weather.parquet")
    enrichment().to_parquet(tmp_path / "enrichment.parquet")
    args = ["--data", str(data_dir), "--enrichment", str(tmp_path / "enrichment.parquet")]

    assert main([*args, "--output", str(tmp_path / "one"), "--horizon-hours", "24"]) == 0
    assert main([*args, "--output", str(tmp_path / "two"), "--horizon-hours", "24"]) == 0

    for name in ("features.parquet", "manifest.json"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    manifest = json.loads((tmp_path / "one" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["horizon_hours"] == 24
    assert manifest["groups"] == [g.value for g in ALL_GROUPS]
    assert set(manifest["inputs"]) == {
        "readings.parquet",
        "buildings.parquet",
        "weather.parquet",
        "weather_enrichment.parquet",
    }
    assert set(manifest["missing_share"]) == set(feature_names())
    table = pd.read_parquet(tmp_path / "one" / "features.parquet")
    assert list(table.columns) == ["timestamp", "meter_id", "building_id", *feature_names()]
    assert "horizon 24 h" in capsys.readouterr().out


def test_the_command_line_says_what_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    noisy_readings().to_parquet(tmp_path / "readings.parquet")
    buildings().to_parquet(tmp_path / "buildings.parquet")

    assert main(["--data", str(tmp_path), "--output", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "no weather.parquet" in out and "no --enrichment" in out

    assert main(["--data", str(tmp_path / "nowhere")]) == 1
    assert "error:" in capsys.readouterr().err
    assert main(["--data", str(tmp_path), "--horizon-hours", "0"]) == 1
