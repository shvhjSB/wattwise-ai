import numpy as np
import pandas as pd
import pytest

from wattwise.data.solar import day_length_h, equation_of_time_min, solar_elevation_deg

# Cross-checked once against pvlib 0.16.1's NREL SPA over 2016-2017 at six points: elevation within
# 0.53 degrees, day length within 5.2 minutes (docs/WORK_LOG.md, T013). The tolerances below
# allow for that.


@pytest.mark.parametrize(
    ("day", "expected"),
    [("2016-02-11", -14.2), ("2016-04-15", 0.0), ("2016-11-03", 16.4), ("2017-07-26", -6.5)],
)
def test_the_equation_of_time_matches_known_values(day: str, expected: float) -> None:
    value = equation_of_time_min(pd.DatetimeIndex([pd.Timestamp(f"{day}T12:00:00Z")]))[0]

    assert value == pytest.approx(expected, abs=1.0)


def highest_elevation(day: str, latitude: float, longitude: float) -> float:
    minutes = pd.date_range(f"{day}T00:00Z", periods=24 * 60, freq="min")
    n = len(minutes)
    return float(solar_elevation_deg(minutes, np.full(n, latitude), np.full(n, longitude)).max())


@pytest.mark.parametrize(
    ("day", "latitude", "expected"),
    [
        ("2016-06-20", 40.0, 90 - 40 + 23.44),  # June solstice: the sun is over 23.44 N
        ("2016-12-21", 40.0, 90 - 40 - 23.44),
        ("2016-03-20", 0.0, 90.0),  # March equinox, overhead at the equator
        ("2016-06-20", -33.9, 90 - 33.9 - 23.44),
    ],
)
def test_the_noon_sun_is_as_high_as_geometry_says(
    day: str, latitude: float, expected: float
) -> None:
    assert highest_elevation(day, latitude, -75.0) == pytest.approx(expected, abs=0.6)


def test_the_sun_is_below_the_horizon_at_local_midnight() -> None:
    midnight = pd.DatetimeIndex([pd.Timestamp("2016-06-20T05:00Z")])  # 00:00 at 75 W

    assert solar_elevation_deg(midnight, [40.0], [-75.0])[0] < -20


@pytest.mark.parametrize(
    ("day", "latitude", "hours"),
    [
        ("2016-06-21", 51.5, 16 + 38 / 60),  # London: sunrise 04:43, sunset 21:21
        ("2016-12-21", 51.5, 7 + 49 / 60),  # London: 08:04 to 15:53
        ("2016-03-20", 0.0, 12.12),  # the equator: 12 h plus refraction and the sun's radius
        ("2016-06-21", 80.0, 24.0),  # polar day
        ("2016-12-21", 80.0, 0.0),  # polar night
    ],
)
def test_day_length_matches_known_values(day: str, latitude: float, hours: float) -> None:
    assert day_length_h(pd.DatetimeIndex([day]), [latitude])[0] == pytest.approx(hours, abs=0.1)


def test_missing_coordinates_give_nan() -> None:
    times = pd.DatetimeIndex([pd.Timestamp("2016-06-20T12:00Z")] * 2)

    elevation = solar_elevation_deg(times, [np.nan, 40.0], [0.0, np.nan])
    length = day_length_h(times, [np.nan])

    assert np.isnan(elevation).all()
    assert np.isnan(length).all()
