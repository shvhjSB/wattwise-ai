from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wattwise.data.time_convention import Clock, winter_offset

#: (site_id, timezone, electricity clock, buildings, flat load?) for a mini BDG2-format dataset.
SiteSpec = tuple[str, str, Clock, int, bool]
BDG2_GRID = pd.date_range("2016-01-01", "2018-01-01", freq="h", inclusive="left")


@pytest.fixture
def readings() -> pd.DataFrame:
    """A small valid readings table with typed columns, deliberately not sorted by key."""
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2016-01-01T01:00:00Z",
                    "2016-01-01T00:00:00Z",
                    "2016-01-01T00:00:00Z",
                    "2016-01-01T01:00:00Z",
                ],
                utc=True,
            ),
            "meter_id": ["b2:electricity", "b2:electricity", "b1:electricity", "b1:electricity"],
            "building_id": ["b2", "b2", "b1", "b1"],
            "meter_type": ["electricity"] * 4,
            "unit": ["kWh"] * 4,
            "value": [12.5, 10.0, 3.25, None],
        }
    )


@pytest.fixture
def buildings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "building_id": ["b1", "b2"],
            "site_id": ["site-a", "site-a"],
            "timezone": ["Europe/London", "US/Eastern"],
        }
    )


@pytest.fixture
def weather() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "site_id": ["site-a", "site-a"],
            "timestamp": pd.to_datetime(["2016-01-01T00:00:00Z", "2016-01-01T01:00:00Z"], utc=True),
            "air_temperature_c": [4.5, None],
        }
    )


def on_bdg2_grid(values: pd.Series, timezone: str, clock: Clock) -> pd.Series:
    """Place a UTC-indexed series on BDG2's naive regular local grid, as BDG2 did.

    STANDARD: shift by the fixed winter offset. WALL_CLOCK: use local civil time, leaving the
    spring non-existent hour empty and summing the two readings of the repeated autumn hour."""
    utc = pd.DatetimeIndex(values.index)
    if clock is Clock.STANDARD:
        local = utc.tz_convert("UTC").tz_localize(None) + winter_offset(timezone, 2016)
        placed = pd.Series(values.to_numpy(), index=local)
    else:
        local = utc.tz_convert(timezone).tz_localize(None)
        placed = pd.Series(values.to_numpy(), index=local).groupby(level=0).sum(min_count=1)
    return placed.reindex(BDG2_GRID)


@pytest.fixture
def make_bdg2_raw(tmp_path: Path) -> Callable[[Sequence[SiteSpec]], Path]:
    """Build a mini BDG2-format raw directory (same files, columns and timestamp format)."""

    def build(sites: Sequence[SiteSpec], seed: int = 0) -> Path:
        rng = np.random.default_rng(seed)
        utc = pd.date_range("2015-12-31", "2018-01-02", freq="h", tz="UTC")
        metadata: list[dict[str, object]] = []
        electricity: dict[str, pd.Series] = {}
        weather: list[pd.DataFrame] = []
        for site_id, timezone, clock, count, flat in sites:
            wall = utc.tz_convert(timezone)
            occupied = (wall.hour >= 8) & (wall.hour < 18) & (wall.dayofweek < 5)
            for i in range(count):
                building = f"{site_id}_office_B{i}"
                base = 30.0 + 5 * i
                load = base + rng.normal(0, 1.5, len(utc))
                if not flat:
                    load = load + 60.0 * np.asarray(occupied)
                electricity[building] = on_bdg2_grid(pd.Series(load, index=utc), timezone, clock)
                metadata.append(
                    {
                        "building_id": building,
                        "site_id": site_id,
                        "primaryspaceusage": "Office",
                        "sqm": 1000.0 + 100 * i,
                        "lat": None,
                        "lng": None,
                        "timezone": timezone,
                        "electricity": "Yes",
                        "hotwater": "Yes" if i == 0 else None,
                    }
                )
            # Temperature follows the sun, i.e. standard time; BDG2 weather uses a fixed offset.
            solar_hour = (
                utc.tz_convert("UTC").tz_localize(None) + winter_offset(timezone, 2016)
            ).hour
            temperature = (
                10 + 6 * np.cos(2 * np.pi * (solar_hour - 15) / 24) + rng.normal(0, 0.5, len(utc))
            )
            series = on_bdg2_grid(pd.Series(temperature, index=utc), timezone, Clock.STANDARD)
            weather.append(
                pd.DataFrame(
                    {
                        "timestamp": BDG2_GRID.strftime("%Y-%m-%d %H:%M:%S"),
                        "site_id": site_id,
                        "airTemperature": series.round(1).to_numpy(),
                        "cloudCoverage": np.nan,
                        "dewTemperature": (series - 3).round(1).to_numpy(),
                        "precipDepth1HR": 0.0,
                        "precipDepth6HR": np.nan,
                        "seaLvlPressure": 1015.0,
                        "windDirection": 180.0,
                        "windSpeed": 3.1,
                    }
                )
            )

        root = tmp_path / "bdg2"
        for folder in ("metadata", "weather", "meters/raw", "meters/cleaned"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        pd.DataFrame(metadata).to_csv(root / "metadata" / "metadata.csv", index=False)
        wide = pd.DataFrame(electricity, index=BDG2_GRID)
        wide.index = pd.Index(BDG2_GRID.strftime("%Y-%m-%d %H:%M:%S"), name="timestamp")
        wide.round(4).to_csv(root / "meters" / "raw" / "electricity.csv")
        cleaned = wide.round(4).mask(wide.round(4) < 0)  # BDG2 cleaning removed bad readings
        cleaned.to_csv(root / "meters" / "cleaned" / "electricity_cleaned.csv")
        pd.concat(weather).to_csv(root / "weather" / "weather.csv", index=False)
        return root

    return build
