from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from wattwise.ml.features import build_features
from wattwise.ml.splits import Chronological, SplitConfig

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
JAN = datetime(2017, 1, 1, tzinfo=UTC)


def at(day: float) -> datetime:
    """Midnight UTC on 2017-01-(1 + day); fractions give hours."""
    return JAN + day * DAY


def readings(
    buildings: Sequence[str] = ("A", "B"), days: int = 10, freq: str = "h"
) -> pd.DataFrame:
    """Canonical electricity readings from 2017-01-01: one meter per building, regular intervals."""
    times = pd.date_range(JAN, JAN + days * DAY, freq=freq, inclusive="left").as_unit("us")
    frames = [
        pd.DataFrame(
            {
                "timestamp": times,
                "meter_id": f"{b}-electricity",
                "building_id": b,
                "meter_type": "electricity",
                "unit": "kWh",
                "value": np.arange(len(times), dtype=float),
            }
        )
        for b in buildings
    ]
    return pd.concat(frames, ignore_index=True)


# A synthetic, weather-driven load for model tests (not real performance): weekday occupancy
# plus heating that follows a temperature changing from day to day.
START = datetime(2017, 1, 1, tzinfo=UTC)
VALIDATION_START = datetime(2017, 3, 1, tzinfo=UTC)
DAYS = 100
SPLIT = SplitConfig(
    time=Chronological(
        train_start=START,
        validation_start=VALIDATION_START,
        test_start=datetime(2017, 3, 22, tzinfo=UTC),
        test_end=datetime(2017, 4, 11, tzinfo=UTC),
    )
)
BUILDINGS = pd.DataFrame(
    {
        "building_id": ["A", "B", "C"],
        "site_id": ["S1", "S1", "S2"],
        "timezone": ["UTC", "UTC", "UTC"],
        "latitude": [40.0, 40.0, 51.5],
        "longitude": [-75.0, -75.0, 0.0],
    }
)


def synthetic(seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    times = pd.date_range(START, periods=DAYS * 24, freq="h").as_unit("us")
    day = np.arange(len(times)) // 24
    weather, readings = [], []
    for site in ("S1", "S2"):
        temperature = rng.uniform(-10, 20, DAYS)[day] + 4 * np.sin(2 * np.pi * times.hour / 24)
        weather.append(
            pd.DataFrame({"site_id": site, "timestamp": times, "air_temperature_c": temperature})
        )
    temperature_of = {w["site_id"].iloc[0]: w["air_temperature_c"].to_numpy() for w in weather}
    occupied = (times.dayofweek < 5) & (times.hour >= 8) & (times.hour < 18)
    for building, site, base in (("A", "S1", 50.0), ("B", "S1", 120.0), ("C", "S2", 15.0)):
        heating = np.maximum(0.0, 15.0 - temperature_of[site])
        load = base * (0.5 + 0.5 * occupied + 0.04 * heating) * rng.normal(1.0, 0.02, len(times))
        readings.append(
            pd.DataFrame(
                {
                    "timestamp": times,
                    "meter_id": f"{building}-electricity",
                    "building_id": building,
                    "meter_type": "electricity",
                    "unit": "kWh",
                    "value": load,
                }
            )
        )
    return pd.concat(readings, ignore_index=True), pd.concat(weather, ignore_index=True)


def features_of(readings: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    return build_features(readings, BUILDINGS, weather, regions={})
