"""Compare the machines of one site from their own meters (T066, D077).

For each meter of a building: its energy, its share of the main meter, its running hours, what it
used while the site was closed, its highest hour, and how many events the default detector finds
in its readings. Everything comes from the stored readings and is computed on request; nothing is
stored, and nothing comes from a model.

- **The main meter** is the one the user names, or else the meter with the most energy. The other
  meters are compared against it; what they do not account for is *unmetered*: other loads,
  losses, or machines that are not behind that main meter.
- **Running:** an hour in which the meter used at least 10 % of its 99.9th-percentile hourly use
  (and at least 0.01 kWh). An hour with any running counts as a running hour.
- **Closed hours:** outside the opening days and hours the user gives, in the building's own
  time zone (so the clock changes are handled).
- **Events:** the default detector (D030, the rolling same-hour z-score) run on these readings
  now. They are anomalies to investigate, not confirmed waste, and not stored alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.ml.detection import (
    DETECTOR_DEFAULTS,
    Detector,
    DetectorConfig,
    detect,
    rolling_same_hour,
)

RUNNING_SHARE: Final = 0.1
RUNNING_FLOOR_KWH: Final = 0.01
DEFINITIONS: Final = {
    "energy_kwh": "The sum of the meter's hourly readings over the period; missing hours add "
    "nothing.",
    "share_of_main": "The meter's energy divided by the main meter's, over the same period.",
    "running_hours": "Hours in which the meter used at least 10% of its 99.9th-percentile hourly "
    "use (and at least 0.01 kWh).",
    "closed_kwh": "Energy in the hours outside the opening days and hours given, in the "
    "building's local time.",
    "peak_kwh": "The meter's highest hourly use.",
    "events": "Events the default detector (the rolling same-hour z-score) finds in these "
    "readings now: anomalies to investigate, not confirmed waste, and not stored alerts.",
    "unmetered_kwh": "The main meter's energy minus the compared meters': other loads, losses, "
    "or meters that are not behind the main meter.",
    "negative_hours": "Hours the meter recorded below zero. They are included as recorded; many "
    "of them point to a meter offset or wiring to check, not to energy produced.",
}


@dataclass(frozen=True)
class OpenHours:
    """When the site is open: these weekdays (0 is Monday), from `start` to `end` (local hours,
    `end` exclusive, up to 24)."""

    days: frozenset[int]
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.days or not self.days <= set(range(7)):
            raise ValueError("open days must be one or more of 0 (Monday) to 6 (Sunday)")
        if not 0 <= self.start < self.end <= 24:
            raise ValueError("opening hours must satisfy 0 <= from < to <= 24")

    def is_open(self, local: pd.DatetimeIndex) -> npt.NDArray[np.bool_]:
        day = np.isin(np.asarray(local.dayofweek), sorted(self.days))
        hour = np.asarray(local.hour)
        return day & (hour >= self.start) & (hour < self.end)


@dataclass(frozen=True)
class MeterFigures:
    meter_id: str
    energy_kwh: float
    hours_with_reading: int
    running_threshold_kwh: float
    running_hours: int
    closed_kwh: float
    peak_kwh: float
    events: int
    negative_hours: int
    negative_kwh: float

    def closed_share(self) -> float | None:
        return self.closed_kwh / self.energy_kwh if self.energy_kwh > 0 else None


def figures(readings: pd.DataFrame, timezone: str, hours: OpenHours) -> list[MeterFigures]:
    """Each meter's figures, from hourly readings (`meter_id`, `building_id`, `timestamp` in
    UTC, `value` in kWh, missing as NaN), in meter-id order."""
    if readings.empty:
        return []
    frame = readings.sort_values(["meter_id", "timestamp"], kind="stable").reset_index(drop=True)
    config = DetectorConfig(**DETECTOR_DEFAULTS[Detector.ROLLING_Z])  # type: ignore[arg-type]
    z, baseline = rolling_same_hour(frame, floor_fraction=config.scale_floor_fraction)
    every = np.ones(len(frame), dtype=bool)
    events = detect(frame, baseline, None, every, config, z=z).events
    counts = events.groupby("meter_id").size() if len(events) else pd.Series(dtype=int)
    local = pd.DatetimeIndex(frame["timestamp"]).tz_convert(timezone)
    closed = ~hours.is_open(local)
    out = []
    for meter, rows in frame.groupby("meter_id", sort=True):
        values = rows["value"].astype(float)
        present = values.dropna()
        top = float(present.quantile(0.999)) if len(present) else 0.0
        threshold = max(RUNNING_FLOOR_KWH, RUNNING_SHARE * top)
        out.append(
            MeterFigures(
                meter_id=str(meter),
                energy_kwh=float(present.sum()),
                hours_with_reading=len(present),
                running_threshold_kwh=round(threshold, 4),
                running_hours=int((present >= threshold).sum()),
                closed_kwh=float(values[closed[rows.index]].sum()),
                peak_kwh=float(present.max()) if len(present) else 0.0,
                events=int(counts.get(meter, 0)),
                negative_hours=int((present < 0).sum()),
                negative_kwh=float(present[present < 0].sum()),
            )
        )
    return out


def compare(
    readings: pd.DataFrame, timezone: str, hours: OpenHours, main: str | None = None
) -> dict[str, Any]:
    """The comparison: the main meter's figures, every other meter's with its share of the main
    meter (largest first), and the unmetered remainder. `main` must be one of the meters."""
    meters = figures(readings, timezone, hours)
    if len(meters) < 2:
        raise ValueError("a comparison needs at least two meters")
    by_id = {m.meter_id: m for m in meters}
    if main is None:
        main_figures = max(meters, key=lambda m: (m.energy_kwh, m.meter_id))
    elif main in by_id:
        main_figures = by_id[main]
    else:
        raise ValueError(f"{main} is not one of this building's compared meters")
    chosen = main is not None
    others = sorted(
        (m for m in meters if m.meter_id != main_figures.meter_id),
        key=lambda m: (-m.energy_kwh, m.meter_id),
    )
    total = main_figures.energy_kwh
    unmetered = total - sum(m.energy_kwh for m in others)
    return {
        "main": {**_out(main_figures), "chosen": chosen},
        "machines": [
            {**_out(m), "share_of_main": m.energy_kwh / total if total > 0 else None}
            for m in others
        ],
        "unmetered_kwh": unmetered,
        "unmetered_share": unmetered / total if total > 0 else None,
    }


def _out(m: MeterFigures) -> dict[str, Any]:
    return {
        "meter_id": m.meter_id,
        "energy_kwh": round(m.energy_kwh, 3),
        "hours_with_reading": m.hours_with_reading,
        "running_threshold_kwh": m.running_threshold_kwh,
        "running_hours": m.running_hours,
        "closed_kwh": round(m.closed_kwh, 3),
        "closed_share": m.closed_share(),
        "peak_kwh": round(m.peak_kwh, 3),
        "events": m.events,
        "negative_hours": m.negative_hours,
        "negative_kwh": round(m.negative_kwh, 3),
    }
