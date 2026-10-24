"""Leakage-safe features for consumption models (docs/FEATURES.md, D025).

One row of features per reading, from information available for that reading's interval:

- **Conditions** (calendar, public holidays, weather, sun) describe the target interval itself or
  earlier intervals, never a later one. Weather is observed (BDG2) or reanalysis (ERA5), not a
  forecast: the model estimates consumption under the conditions that actually occurred, which is
  what an expected-consumption baseline needs.
- **Consumption history** (lags and rolling statistics) uses only readings whose interval started
  at least `horizon_hours` before the target interval starts. The target, and every reading after
  it, never enters its own features.

Nothing is fitted here: no imputation, scaling or encoding learned from data. Missing inputs stay
missing (NaN), and flag columns say what was available. Anything learned from data is fitted on
training rows in T014. Every feature is float64, and the same inputs give the same features for
each reading whatever the row order.

    uv run python -m wattwise.ml.features --data ../data/processed/bdg2/cleaned \
        --enrichment ../data/processed/era5/weather_enrichment.parquet
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import holidays
import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.data.acquisition import sha256_of
from wattwise.data.bdg2_sites import SITE_REGIONS, Region
from wattwise.data.solar import day_length_h, solar_elevation_deg

FloatArray = npt.NDArray[np.float64]

FEATURE_SET_VERSION: Final = "1"
#: The shortest history offset is one week, so a horizon of up to one week keeps every history
#: feature at or beyond it. The default matches the seasonal-naive baseline (D024).
DEFAULT_HORIZON_HOURS: Final = 168
MAX_HORIZON_HOURS: Final = 168
#: A rolling statistic needs at least this share of its window observed, or it is missing.
ROLLING_MIN_FRACTION: Final = 0.5
TEMPERATURE_WINDOW_HOURS: Final = 24
#: Degree-hour base: a common convention (about 65 degF), not a fitted balance point.
BALANCE_TEMPERATURE_C: Final = 18.0
SAME_HOUR_WEEKS: Final = 4
SAME_HOUR_MIN_WEEKS: Final = 2
DEFAULT_OUTPUT: Final = Path("../data/processed/features")
RULES: Final = (
    "Conditions (calendar, holidays, weather, sun) describe the target interval or earlier "
    "intervals, never a later one.",
    "Consumption history uses only readings whose interval started at least horizon_hours "
    "before the target interval starts.",
    "Nothing is fitted: missing inputs stay NaN, with flags; imputation and scaling are fitted on "
    "training rows by the model (T014).",
)


class Group(StrEnum):
    CALENDAR = "calendar"
    HOLIDAY = "holiday"
    WEATHER = "weather"
    SUN = "sun"
    HISTORY = "history"


class Source(StrEnum):
    COMPUTED = "computed"  # from the timestamp and building metadata
    REFERENCE = "reference"  # the holidays package's calendars
    OBSERVED = "observed"  # BDG2 measurements
    DERIVED = "derived"  # calculated from observed values
    MODELLED = "modelled"  # ERA5 reanalysis, a grid-cell value


@dataclass(frozen=True)
class Feature:
    name: str
    group: Group
    source: Source
    unit: str
    description: str


_H = "H (the horizon, default 168 h)"

# fmt: off
FEATURES: Final[tuple[Feature, ...]] = (
    Feature("hour_local", Group.CALENDAR, Source.COMPUTED, "h",
            "Hour of day, 0-23, in the building's local wall time."),
    Feature("day_of_week_local", Group.CALENDAR, Source.COMPUTED, "-",
            "Day of week in local time: 0 = Monday ... 6 = Sunday."),
    Feature("is_weekend_local", Group.CALENDAR, Source.COMPUTED, "0/1",
            "1 on a local Saturday or Sunday, else 0."),
    Feature("month_local", Group.CALENDAR, Source.COMPUTED, "-", "Month in local time, 1-12."),
    Feature("day_of_year_local", Group.CALENDAR, Source.COMPUTED, "-",
            "Day of year in local time, 1-366."),
    Feature("hour_sin", Group.CALENDAR, Source.COMPUTED, "-", "sin(2 pi hour_local / 24)."),
    Feature("hour_cos", Group.CALENDAR, Source.COMPUTED, "-", "cos(2 pi hour_local / 24)."),
    Feature("day_of_year_sin", Group.CALENDAR, Source.COMPUTED, "-",
            "sin(2 pi (day_of_year_local - 1) / days in the year)."),
    Feature("day_of_year_cos", Group.CALENDAR, Source.COMPUTED, "-",
            "cos(2 pi (day_of_year_local - 1) / days in the year)."),
    Feature("is_public_holiday", Group.HOLIDAY, Source.REFERENCE, "0/1",
            "1 if the local date is a public holiday (observed days included) in the site's "
            "country and region, 0 if not, NaN if the region is unknown."),
    Feature("holiday_region_known", Group.HOLIDAY, Source.COMPUTED, "0/1",
            "1 if the site's country is known, so is_public_holiday is defined; else 0."),
    Feature("air_temperature_c", Group.WEATHER, Source.OBSERVED, "degC",
            "BDG2 air temperature observed at the interval start. NaN if not observed."),
    Feature("dew_temperature_c", Group.WEATHER, Source.OBSERVED, "degC",
            "BDG2 dew-point temperature observed at the interval start."),
    Feature("wind_speed_m_s", Group.WEATHER, Source.OBSERVED, "m/s",
            "BDG2 wind speed observed at the interval start."),
    Feature("relative_humidity_pct_derived", Group.WEATHER, Source.DERIVED, "%",
            "Relative humidity at the interval start, derived from observed temperature and dew "
            "point (T007d)."),
    Feature("air_temperature_mean_24h_c", Group.WEATHER, Source.DERIVED, "degC",
            "Mean observed air temperature over the 24 hours ending at the interval start (it "
            "and the 23 before); NaN with fewer than 12 observations."),
    Feature("heating_degrees_c", Group.WEATHER, Source.DERIVED, "degC",
            "max(0, 18 - air_temperature_c)."),
    Feature("cooling_degrees_c", Group.WEATHER, Source.DERIVED, "degC",
            "max(0, air_temperature_c - 18)."),
    Feature("ghi_w_m2_era5", Group.WEATHER, Source.MODELLED, "W/m2",
            "ERA5 global horizontal irradiance, mean over the interval (T007d)."),
    Feature("cloud_cover_pct_era5", Group.WEATHER, Source.MODELLED, "%",
            "ERA5 total cloud cover at the interval start (T007d)."),
    Feature("weather_observed", Group.WEATHER, Source.COMPUTED, "0/1",
            "1 if an air temperature was observed at the interval start, else 0."),
    Feature("era5_available", Group.WEATHER, Source.COMPUTED, "0/1",
            "1 if ERA5 irradiance exists for the interval, else 0 (sites without coordinates)."),
    Feature("solar_elevation_deg", Group.SUN, Source.COMPUTED, "deg",
            "Geometric sun elevation at the middle of the interval, from building coordinates; "
            "NaN without coordinates."),
    Feature("is_daylight", Group.SUN, Source.COMPUTED, "0/1",
            "1 if solar_elevation_deg > 0, else 0; NaN without coordinates."),
    Feature("day_length_h", Group.SUN, Source.COMPUTED, "h",
            "Sunrise to sunset on the local date; NaN without coordinates."),
    Feature("lag_168h", Group.HISTORY, Source.OBSERVED, "as value",
            "The meter's reading 168 h (one week) before the interval start."),
    Feature("lag_336h", Group.HISTORY, Source.OBSERVED, "as value",
            "The meter's reading 336 h (two weeks) before the interval start."),
    Feature("same_hour_mean_4w", Group.HISTORY, Source.DERIVED, "as value",
            "Mean of the readings 1, 2, 3 and 4 weeks before the interval start; NaN with fewer "
            "than 2 of them."),
    Feature("rolling_mean_24h", Group.HISTORY, Source.DERIVED, "as value",
            f"Mean reading over the 24 h ending {_H} before the interval start; NaN with fewer "
            "than 12 readings."),
    Feature("rolling_mean_168h", Group.HISTORY, Source.DERIVED, "as value",
            f"Mean reading over the 168 h ending {_H} before the interval start; NaN with fewer "
            "than 84 readings."),
    Feature("rolling_std_168h", Group.HISTORY, Source.DERIVED, "as value",
            "Sample standard deviation over the same 168 h window."),
    Feature("rolling_min_168h", Group.HISTORY, Source.DERIVED, "as value",
            "Minimum reading over the same 168 h window (a baseload indicator)."),
)
# fmt: on

ALL_GROUPS: Final = tuple(Group)
LAGS_HOURS: Final = (168, 336)
ROLLING_WINDOWS_HOURS: Final = (24, 168)


@dataclass(frozen=True)
class FeatureConfig:
    horizon_hours: int = DEFAULT_HORIZON_HOURS
    groups: tuple[Group, ...] = ALL_GROUPS

    def __post_init__(self) -> None:
        if not 1 <= self.horizon_hours <= MAX_HORIZON_HOURS:
            raise ValueError(
                f"horizon_hours must be 1-{MAX_HORIZON_HOURS}: a feature may not see the target "
                f"(0), and the shortest history offset is {min(LAGS_HOURS)} h."
            )
        if not self.groups or len(set(self.groups)) != len(self.groups):
            raise ValueError("Give each feature group at most once, and at least one group.")


def feature_names(groups: Sequence[Group] = ALL_GROUPS) -> list[str]:
    """Feature columns in their fixed order, for the given groups."""
    return [f.name for f in FEATURES if f.group in groups]


def feature_manifest(config: FeatureConfig) -> dict[str, object]:
    """What a feature table was built with: version, settings, rules and column provenance."""
    return {
        "feature_set_version": FEATURE_SET_VERSION,
        "horizon_hours": config.horizon_hours,
        "groups": [g.value for g in Group if g in config.groups],
        "holidays_package_version": importlib.metadata.version("holidays"),
        "rules": list(RULES),
        "features": [
            {
                "name": f.name,
                "group": f.group.value,
                "source": f.source.value,
                "unit": f.unit,
                "description": f.description,
            }
            for f in FEATURES
            if f.group in config.groups
        ],
    }


def build_features(
    readings: pd.DataFrame,
    buildings: pd.DataFrame,
    weather: pd.DataFrame | None = None,
    enrichment: pd.DataFrame | None = None,
    *,
    regions: Mapping[str, Region | None] = SITE_REGIONS,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Features for every reading, indexed like `readings`.

    `readings`, `buildings` and `weather` are canonical tables (UTC, hourly). `enrichment` is the
    T007d table (`weather_enrichment.parquet`). Without `weather` or `enrichment`, their features
    are NaN and their flags 0. `regions` maps site IDs to their country and region for holidays;
    sites missing from it, or mapped to None, have no holiday information."""
    config = config or FeatureConfig()
    names = feature_names(config.groups)
    _check_readings(readings, buildings)
    if readings.empty:
        return pd.DataFrame({n: pd.Series(dtype="float64") for n in names}, index=readings.index)

    info = buildings.set_index(buildings["building_id"].astype(str))
    building = readings["building_id"].astype(str)
    sites = building.map(info["site_id"].astype(str)).to_numpy(dtype=object)
    times = pd.DatetimeIndex(readings["timestamp"])
    local = _local_calendar(times, building.map(info["timezone"].astype(str)).to_numpy(object))

    columns: dict[str, FloatArray] = {}
    if Group.CALENDAR in config.groups:
        columns |= _calendar(local)
    if Group.HOLIDAY in config.groups:
        columns |= _holidays(local.date, sites, regions)
    if Group.WEATHER in config.groups:
        columns |= _weather(times, sites, weather, enrichment)
    if Group.SUN in config.groups:
        columns |= _sun(times, local.date, building, info)
    if Group.HISTORY in config.groups:
        columns |= _history(readings, times, config.horizon_hours)
    return pd.DataFrame({n: columns[n] for n in names}, index=readings.index)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _check_readings(readings: pd.DataFrame, buildings: pd.DataFrame) -> None:
    missing = {"timestamp", "meter_id", "building_id", "value"} - set(readings.columns)
    if missing:
        raise ValueError(f"readings lack columns {sorted(missing)}")
    _check_hourly_utc(readings["timestamp"], "readings")
    if readings.duplicated(["meter_id", "timestamp"]).any():
        raise ValueError("readings have more than one value for a meter and hour")
    if buildings["building_id"].duplicated().any():
        raise ValueError("buildings list a building more than once")
    unknown = sorted(
        set(readings["building_id"].astype(str)) - set(buildings["building_id"].astype(str))
    )
    if unknown:
        raise ValueError(f"readings refer to buildings not in the buildings table: {unknown[:5]}")


def _check_hourly_utc(timestamps: pd.Series, table: str) -> None:
    dtype = timestamps.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError(f"{table}: timestamps must be timezone-aware UTC, found {dtype}")
    if not (timestamps == timestamps.dt.floor("h")).all():
        raise ValueError(f"{table}: feature set {FEATURE_SET_VERSION} needs whole-hour timestamps")


def _hourly_grid(table: pd.DataFrame, key: str, column: str) -> pd.DataFrame:
    """`column` on a complete hourly grid from the first to the last timestamp, one column per
    `key` value; NaN where there is no row."""
    wide = table.pivot(index="timestamp", columns=key, values=column).astype(float)
    if wide.empty:
        return wide
    hours = pd.date_range(wide.index.min(), wide.index.max(), freq="h")
    return wide.reindex(hours)


def _lookup(
    grid: pd.DataFrame, times: pd.DatetimeIndex, keys: npt.NDArray[np.object_], hours_before: int
) -> FloatArray:
    """The grid value for each (key, time - hours_before); NaN outside the grid."""
    out = np.full(len(times), np.nan)
    if grid.empty:
        return out
    position = np.asarray((times - grid.index[0]) // pd.Timedelta(hours=1), dtype=np.int64)
    position -= hours_before
    column = grid.columns.get_indexer(pd.Index(keys))
    ok = (position >= 0) & (position < len(grid)) & (column >= 0)
    out[ok] = grid.to_numpy(dtype=float)[position[ok], column[ok]]
    return out


# ---------------------------------------------------------------------------
# Feature groups
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Local:
    """Local wall-time fields per row."""

    hour: FloatArray
    day_of_week: FloatArray
    month: FloatArray
    day_of_year: FloatArray
    days_in_year: FloatArray
    date: pd.DatetimeIndex  # local midnight, timezone-naive


def _local_calendar(times: pd.DatetimeIndex, zones: npt.NDArray[np.object_]) -> _Local:
    """Convert each building's rows with its own zone."""
    fields = np.zeros((5, len(times)))
    date = np.empty(len(times), dtype="datetime64[us]")
    for zone in sorted(set(zones)):
        mask = zones == zone
        local = times[mask].tz_convert(zone)
        fields[:, mask] = [
            local.hour,
            local.dayofweek,
            local.month,
            local.dayofyear,
            np.where(local.is_leap_year, 366, 365),
        ]
        date[mask] = local.tz_localize(None).normalize().as_unit("us").to_numpy()
    hour, day_of_week, month, day_of_year, days_in_year = fields
    return _Local(
        hour=hour,
        day_of_week=day_of_week,
        month=month,
        day_of_year=day_of_year,
        days_in_year=days_in_year,
        date=pd.DatetimeIndex(date),
    )


def _calendar(local: _Local) -> dict[str, FloatArray]:
    year_angle = 2 * np.pi * (local.day_of_year - 1) / local.days_in_year
    return {
        "hour_local": local.hour,
        "day_of_week_local": local.day_of_week,
        "is_weekend_local": (local.day_of_week >= 5).astype(float),
        "month_local": local.month,
        "day_of_year_local": local.day_of_year,
        "hour_sin": np.sin(2 * np.pi * local.hour / 24),
        "hour_cos": np.cos(2 * np.pi * local.hour / 24),
        "day_of_year_sin": np.sin(year_angle),
        "day_of_year_cos": np.cos(year_angle),
    }


def _holidays(
    local_dates: pd.DatetimeIndex,
    sites: npt.NDArray[np.object_],
    regions: Mapping[str, Region | None],
) -> dict[str, FloatArray]:
    is_holiday = np.full(len(local_dates), np.nan)
    known = np.zeros(len(local_dates))
    dates = local_dates.to_numpy().astype("datetime64[D]")
    for site in sorted(set(sites)):
        region = regions.get(site)
        if region is None:
            continue
        mask = sites == site
        years = sorted({int(y) for y in dates[mask].astype("datetime64[Y]").astype(int) + 1970})
        try:
            calendar = holidays.country_holidays(
                region.country, subdiv=region.subdivision, years=years
            )
        except NotImplementedError as exc:
            raise ValueError(f"site {site}: no holiday calendar for {region}: {exc}") from exc
        observed = np.array(sorted(calendar), dtype="datetime64[D]")
        is_holiday[mask] = np.isin(dates[mask], observed).astype(float)
        known[mask] = 1.0
    return {"is_public_holiday": is_holiday, "holiday_region_known": known}


def _weather(
    times: pd.DatetimeIndex,
    sites: npt.NDArray[np.object_],
    weather: pd.DataFrame | None,
    enrichment: pd.DataFrame | None,
) -> dict[str, FloatArray]:
    nan = np.full(len(times), np.nan)
    observed = {"air_temperature_c": nan, "dew_temperature_c": nan, "wind_speed_m_s": nan}
    mean_24h = nan
    if weather is not None:
        _check_site_table(weather, "weather")
        for column in observed:
            if column in weather.columns:
                observed[column] = _lookup(
                    _hourly_grid(weather, "site_id", column), times, sites, 0
                )
        temperature = _hourly_grid(weather, "site_id", "air_temperature_c")
        rolled = temperature.rolling(
            TEMPERATURE_WINDOW_HOURS,
            min_periods=int(TEMPERATURE_WINDOW_HOURS * ROLLING_MIN_FRACTION),
        ).mean()
        mean_24h = _lookup(rolled, times, sites, 0)
    modelled = {
        c: nan for c in ("relative_humidity_pct_derived", "ghi_w_m2_era5", "cloud_cover_pct_era5")
    }
    if enrichment is not None:
        _check_site_table(enrichment, "enrichment")
        for column in modelled:
            modelled[column] = _lookup(_hourly_grid(enrichment, "site_id", column), times, sites, 0)
    t = observed["air_temperature_c"]
    return {
        **observed,
        **modelled,
        "air_temperature_mean_24h_c": mean_24h,
        "heating_degrees_c": np.maximum(0.0, BALANCE_TEMPERATURE_C - t),
        "cooling_degrees_c": np.maximum(0.0, t - BALANCE_TEMPERATURE_C),
        "weather_observed": (~np.isnan(t)).astype(float),
        "era5_available": (~np.isnan(modelled["ghi_w_m2_era5"])).astype(float),
    }


def _check_site_table(table: pd.DataFrame, name: str) -> None:
    _check_hourly_utc(table["timestamp"], name)
    if table.duplicated(["site_id", "timestamp"]).any():
        raise ValueError(f"{name}: more than one row for a site and hour")


def _sun(
    times: pd.DatetimeIndex,
    local_dates: pd.DatetimeIndex,
    building: pd.Series,
    info: pd.DataFrame,
) -> dict[str, FloatArray]:
    def coordinate(column: str) -> FloatArray:
        if column not in info.columns:
            return np.full(len(times), np.nan)
        return np.asarray(building.map(info[column].astype(float)), dtype=np.float64)

    latitude, longitude = coordinate("latitude"), coordinate("longitude")
    elevation = solar_elevation_deg(times + pd.Timedelta(minutes=30), latitude, longitude)
    return {
        "solar_elevation_deg": elevation,
        "is_daylight": np.where(np.isnan(elevation), np.nan, (elevation > 0).astype(float)),
        "day_length_h": day_length_h(local_dates, latitude),
    }


def _history(
    readings: pd.DataFrame, times: pd.DatetimeIndex, horizon: int
) -> dict[str, FloatArray]:
    grid = _hourly_grid(readings, "meter_id", "value")
    meters = readings["meter_id"].astype(str).to_numpy(dtype=object)
    columns = {f"lag_{lag}h": _lookup(grid, times, meters, lag) for lag in LAGS_HOURS}

    weeks = np.vstack(
        [_lookup(grid, times, meters, 168 * w) for w in range(1, SAME_HOUR_WEEKS + 1)]
    )
    counts = (~np.isnan(weeks)).sum(axis=0)
    totals = np.where(np.isnan(weeks), 0.0, weeks).sum(axis=0)
    columns["same_hour_mean_4w"] = np.where(
        counts >= SAME_HOUR_MIN_WEEKS, totals / np.maximum(counts, 1), np.nan
    )

    for window in ROLLING_WINDOWS_HOURS:
        rolling = grid.rolling(window, min_periods=int(window * ROLLING_MIN_FRACTION))
        columns[f"rolling_mean_{window}h"] = _lookup(rolling.mean(), times, meters, horizon)
        if window == 168:
            columns["rolling_std_168h"] = _lookup(rolling.std(), times, meters, horizon)
            columns["rolling_min_168h"] = _lookup(rolling.min(), times, meters, horizon)
    return columns


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def write(
    features: pd.DataFrame,
    keys: pd.DataFrame,
    config: FeatureConfig,
    inputs: Mapping[str, Path],
    output_dir: Path,
) -> dict[str, str]:
    """Write `features.parquet` (keys plus features) and `manifest.json`; return their SHA-256."""
    output_dir.mkdir(parents=True, exist_ok=True)
    table = pd.concat([keys.reset_index(drop=True), features.reset_index(drop=True)], axis=1)
    table.to_parquet(output_dir / "features.parquet", index=False)
    digests = {"features.parquet": sha256_of(output_dir / "features.parquet")}
    manifest = {
        "pipeline": "wattwise.ml.features",
        **feature_manifest(config),
        "inputs": {name: sha256_of(path) for name, path in sorted(inputs.items())},
        "rows": len(features),
        "missing_share": {c: round(float(features[c].isna().mean()), 4) for c in features},
        "outputs": {name: {"sha256": digest} for name, digest in digests.items()},
    }
    (output_dir / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    digests["manifest.json"] = sha256_of(output_dir / "manifest.json")
    return digests


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.features",
        description="Build the leakage-safe feature table for prepared canonical data.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="folder with readings.parquet, buildings.parquet and (optional) weather.parquet",
    )
    parser.add_argument(
        "--enrichment",
        type=Path,
        help="weather_enrichment.parquet from wattwise.data.era5; without it, ERA5 and humidity "
        "features are missing",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--horizon-hours", type=int, default=DEFAULT_HORIZON_HOURS)
    args = parser.parse_args(argv)
    try:
        config = FeatureConfig(horizon_hours=args.horizon_hours)
        inputs = {
            "readings.parquet": args.data / "readings.parquet",
            "buildings.parquet": args.data / "buildings.parquet",
        }
        readings = pd.read_parquet(inputs["readings.parquet"])
        buildings = pd.read_parquet(inputs["buildings.parquet"])
        weather = None
        if (args.data / "weather.parquet").exists():
            inputs["weather.parquet"] = args.data / "weather.parquet"
            weather = pd.read_parquet(inputs["weather.parquet"])
        enrichment = None
        if args.enrichment is not None:
            inputs["weather_enrichment.parquet"] = args.enrichment
            enrichment = pd.read_parquet(args.enrichment)
        features = build_features(readings, buildings, weather, enrichment, config=config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if weather is None:
        print("note: no weather.parquet, so observed weather features are missing")
    if enrichment is None:
        print("note: no --enrichment, so ERA5 and humidity features are missing")
    keys = readings[["timestamp", "meter_id", "building_id"]]
    digests = write(features, keys, config, inputs, args.output)
    print(
        f"{len(features):,} rows x {features.shape[1]} features (set {FEATURE_SET_VERSION}, "
        f"horizon {config.horizon_hours} h) -> {args.output}"
    )
    for name in features.columns:
        print(f"  {name:32s} missing {features[name].isna().mean():7.2%}")
    for name, digest in digests.items():
        print(f"  {name}: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
