"""Sun position from NOAA's General Solar Position Calculations (docs/FEATURES.md, D025).

The NOAA equations are accurate to a fraction of a degree, far finer than an hourly reading needs,
and need no dependency. Times are UTC; `times` may be timezone-naive, in which case they are read
as UTC. Elevation is geometric (no atmospheric refraction); day length uses the standard sunrise
zenith of 90.833 degrees, which includes refraction and the sun's radius.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

FloatArray = npt.NDArray[np.float64]

SUNRISE_ZENITH_DEG: Final = 90.833


def _fractional_year(times: pd.DatetimeIndex) -> FloatArray:
    """NOAA's fractional year gamma, in radians."""
    days = np.where(times.is_leap_year, 366.0, 365.0)
    hours = np.asarray(times.hour + times.minute / 60.0, dtype=float)
    return np.asarray(
        2 * np.pi / days * (np.asarray(times.dayofyear, dtype=float) - 1 + (hours - 12) / 24),
        dtype=float,
    )


def equation_of_time_min(times: pd.DatetimeIndex) -> FloatArray:
    """Apparent minus mean solar time, in minutes."""
    gamma = _fractional_year(times)
    return np.asarray(
        229.18
        * (
            0.000075
            + 0.001868 * np.cos(gamma)
            - 0.032077 * np.sin(gamma)
            - 0.014615 * np.cos(2 * gamma)
            - 0.040849 * np.sin(2 * gamma)
        ),
        dtype=float,
    )


def declination_rad(times: pd.DatetimeIndex) -> FloatArray:
    """Solar declination, in radians."""
    gamma = _fractional_year(times)
    return np.asarray(
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma),
        dtype=float,
    )


def solar_elevation_deg(
    times: pd.DatetimeIndex, latitude: npt.ArrayLike, longitude: npt.ArrayLike
) -> FloatArray:
    """Geometric elevation of the sun's centre above the horizon at each time, in degrees.
    NaN where a coordinate is missing."""
    lat = np.radians(np.asarray(latitude, dtype=float))
    minutes = np.asarray(times.hour * 60 + times.minute + times.second / 60.0, dtype=float)
    true_solar_min = (
        minutes + equation_of_time_min(times) + 4.0 * np.asarray(longitude, dtype=float)
    )
    hour_angle = np.radians(true_solar_min / 4.0 - 180.0)
    decl = declination_rad(times)
    cos_zenith = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(hour_angle)
    return np.asarray(90.0 - np.degrees(np.arccos(np.clip(cos_zenith, -1.0, 1.0))), dtype=float)


def day_length_h(days: pd.DatetimeIndex, latitude: npt.ArrayLike) -> FloatArray:
    """Hours from sunrise to sunset, using the declination at 12:00 of each day in `days`.
    24 in polar day, 0 in polar night, NaN where the latitude is missing."""
    noon = days.normalize() + pd.Timedelta(hours=12)
    lat = np.radians(np.asarray(latitude, dtype=float))
    decl = declination_rad(noon)
    cos_hour_angle = (np.cos(np.radians(SUNRISE_ZENITH_DEG)) - np.sin(lat) * np.sin(decl)) / (
        np.cos(lat) * np.cos(decl)
    )
    hour_angle_deg = np.degrees(np.arccos(np.clip(cos_hour_angle, -1.0, 1.0)))
    return np.asarray(2.0 * hour_angle_deg / 15.0, dtype=float)
