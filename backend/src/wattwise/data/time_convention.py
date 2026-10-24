"""Which clock do naive local timestamps follow? Evidence-based classification and UTC conversion.

Datasets such as BDG2 publish hourly data with naive "local" timestamps on a regular grid. That
can mean local *standard* time (a fixed offset all year) or local *wall-clock* time (with
daylight saving, forced onto a regular grid). Converting with the wrong rule shifts half of every
year by an hour. This module measures which rule fits, using daylight-saving transitions:

- **Human signals** (building load) follow the wall clock: people arrive at 08:00 on the clock.
  In standard-time timestamps the daily profile therefore moves 1 h *earlier* after the spring
  change and back after the autumn change; in wall-clock timestamps it does not move.
- **Solar signals** (temperature) follow the sun: the profile does not move in standard time and
  moves 1 h *later* after the spring change in wall-clock time.

A verdict needs at least two usable transitions, agreement of at least 75%, and it must hold at
every identifiability margin tried; otherwise the clock is UNDETERMINED and must not be guessed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict


class Clock(StrEnum):
    STANDARD = "standard"  # fixed winter UTC offset all year
    WALL_CLOCK = "wall_clock"  # local civil time, with daylight saving
    UNDETERMINED = "undetermined"


class Signal(StrEnum):
    HUMAN = "human"  # schedules follow the wall clock, e.g. building load
    SOLAR = "solar"  # follows the sun, e.g. air temperature


#: Expected best lag (hours, `after` relative to `before`) at each transition, per clock.
EXPECTED_LAG: Final = {
    Signal.HUMAN: {
        Clock.STANDARD: {"spring": -1, "autumn": 1},
        Clock.WALL_CLOCK: {"spring": 0, "autumn": 0},
    },
    Signal.SOLAR: {
        Clock.STANDARD: {"spring": 0, "autumn": 0},
        Clock.WALL_CLOCK: {"spring": 1, "autumn": -1},
    },
}
DEFAULT_MARGINS: Final = (0.0025, 0.005, 0.01)
MIN_USABLE: Final = 2
AGREEMENT: Final = 0.75


class Transition(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: str  # local calendar date of the change, YYYY-MM-DD
    kind: str  # "spring" (clocks forward) or "autumn" (clocks back)


class ShiftEvidence(BaseModel):
    """Correlation of the daily profile before vs after a transition at lags -1, 0, +1 h."""

    model_config = ConfigDict(frozen=True)

    day: str
    kind: str
    series: int  # number of series that met the coverage requirement
    scores: dict[int, float]  # empty if unusable

    @property
    def lag(self) -> int | None:
        return max(self.scores, key=lambda k: self.scores[k]) if self.scores else None

    @property
    def margin(self) -> float:
        """How much better the best lag is than the runner-up (0 if unusable)."""
        if not self.scores:
            return 0.0
        ordered = sorted(self.scores.values(), reverse=True)
        return ordered[0] - ordered[1]


class ClockVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    clock: Clock
    reason: str


def transitions(timezone: str, start: str, end: str) -> list[Transition]:
    """Daylight-saving changes in [start, end), from the time zone database."""
    zone = ZoneInfo(timezone)
    days = pd.date_range(start, end, freq="D", inclusive="left")
    offsets = [zone.utcoffset(datetime(d.year, d.month, d.day, 12)) for d in days]
    found = []
    for i in range(1, len(days)):
        before, after = offsets[i - 1], offsets[i]
        if before is not None and after is not None and before != after:
            kind = "spring" if after > before else "autumn"
            found.append(Transition(day=days[i].strftime("%Y-%m-%d"), kind=kind))
    return found


def winter_offset(timezone: str, year: int) -> pd.Timedelta:
    """The UTC offset in mid-January: the 'standard' offset for northern-hemisphere zones.

    Uses the total offset, not `dst()`, because some zones (e.g. Europe/Dublin) define winter as
    a *negative* daylight saving in the time zone database."""
    offset = ZoneInfo(timezone).utcoffset(datetime(year, 1, 15, 12))
    if offset is None:
        raise ValueError(f"{timezone} has no UTC offset")
    return pd.Timedelta(offset)


def profile_shift(
    frame: pd.DataFrame,
    transition: Transition,
    *,
    weekdays_only: bool,
    window_days: int = 21,
    min_coverage: float = 0.9,
) -> ShiftEvidence:
    """Compare the mean normalised daily profile in the windows before and after a transition.

    `frame` has a naive local DatetimeIndex and one column per series (e.g. building). The
    transition day itself is excluded."""
    day = pd.Timestamp(transition.day)
    before = _profile(frame, day - pd.Timedelta(days=window_days), day, weekdays_only, min_coverage)
    after = _profile(
        frame,
        day + pd.Timedelta(days=1),
        day + pd.Timedelta(days=window_days + 1),
        weekdays_only,
        min_coverage,
    )
    if before is None or after is None:
        return ShiftEvidence(day=transition.day, kind=transition.kind, series=0, scores={})
    profile_before, count = before
    profile_after, _ = after
    scores = {
        lag: round(float(np.corrcoef(profile_before, np.roll(profile_after, -lag))[0, 1]), 6)
        for lag in (-1, 0, 1)
    }
    return ShiftEvidence(day=transition.day, kind=transition.kind, series=count, scores=scores)


def _profile(
    frame: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    weekdays_only: bool,
    min_coverage: float,
) -> tuple[np.ndarray, int] | None:
    index = pd.DatetimeIndex(frame.index)
    block = frame[(index >= start) & (index < end)]
    if weekdays_only:
        block = block[pd.DatetimeIndex(block.index).dayofweek < 5]
    if block.empty:
        return None
    block = block.loc[:, block.notna().mean() >= min_coverage]
    means = block.mean()
    block = block.loc[:, means.abs() > 0]
    if block.shape[1] == 0:
        return None
    hours = pd.DatetimeIndex(block.index).hour
    profile = (block / block.mean()).groupby(hours).mean().mean(axis=1)
    if len(profile) != 24 or not np.isfinite(profile.to_numpy()).all():
        return None
    values = profile.to_numpy(dtype=float)
    if np.std(values) == 0:
        return None
    return values, int(block.shape[1])


def classify(
    evidence: Sequence[ShiftEvidence],
    signal: Signal,
    margins: Sequence[float] = DEFAULT_MARGINS,
) -> ClockVerdict:
    """A clock only if the same verdict holds at every margin; otherwise UNDETERMINED."""
    verdicts = [_classify_at(evidence, signal, margin) for margin in margins]
    clocks = {v.clock for v in verdicts}
    if len(clocks) == 1:
        return verdicts[1 if len(verdicts) > 1 else 0]
    detail = "; ".join(
        f"margin {m:g}: {v.clock.value}" for m, v in zip(margins, verdicts, strict=True)
    )
    return ClockVerdict(clock=Clock.UNDETERMINED, reason=f"sensitive to the margin ({detail})")


def _classify_at(evidence: Sequence[ShiftEvidence], signal: Signal, margin: float) -> ClockVerdict:
    usable = [e for e in evidence if e.lag is not None and e.margin >= margin]
    if len(usable) < MIN_USABLE:
        return ClockVerdict(
            clock=Clock.UNDETERMINED,
            reason=f"only {len(usable)} usable transition(s) at margin {margin:g}",
        )
    shares = {
        clock: sum(e.lag == rule[e.kind] for e in usable) / len(usable)
        for clock, rule in EXPECTED_LAG[signal].items()
    }
    clock, share = max(shares.items(), key=lambda item: item[1])
    lags = ", ".join(f"{e.kind} {e.lag:+d}" for e in usable if e.lag is not None)
    if share >= AGREEMENT:
        return ClockVerdict(
            clock=clock, reason=f"{share:.0%} of {len(usable)} usable transitions agree ({lags})"
        )
    return ClockVerdict(
        clock=Clock.UNDETERMINED,
        reason=f"no clock reaches {AGREEMENT:.0%} agreement ({lags})",
    )


def nonexistent_hours(timezone: str, start: str, end: str) -> list[pd.Timestamp]:
    """Naive local times skipped by the spring change (e.g. 02:00 on US spring days)."""
    skipped: list[pd.Timestamp] = []
    for transition in transitions(timezone, start, end):
        if transition.kind != "spring":
            continue
        hours = pd.date_range(transition.day, periods=24, freq="h")
        localised = hours.tz_localize(timezone, nonexistent="NaT", ambiguous="NaT")
        skipped.extend(hours[localised.isna()])
    return skipped


def to_utc(naive: pd.DatetimeIndex, timezone: str, clock: Clock) -> pd.DatetimeIndex:
    """Convert naive local timestamps to UTC (microseconds). Unconvertible entries become NaT.

    STANDARD: add the fixed winter offset. WALL_CLOCK: localise in the zone; times that do not
    exist (spring) or occur twice (autumn) become NaT rather than being guessed."""
    if clock is Clock.UNDETERMINED:
        raise ValueError("Cannot convert timestamps whose clock is undetermined.")
    naive = pd.DatetimeIndex(naive)
    if naive.tz is not None:
        raise ValueError("Expected naive timestamps.")
    if clock is Clock.STANDARD:
        years = sorted(set(naive.year.dropna().astype(int)))
        offsets = {year: winter_offset(timezone, year) for year in years}
        if len(set(offsets.values())) > 1:
            raise ValueError(f"{timezone} changed its winter offset within the data")
        offset = next(iter(offsets.values())) if offsets else pd.Timedelta(0)
        utc = (naive - offset).tz_localize("UTC")
    else:
        utc = naive.tz_localize(timezone, nonexistent="NaT", ambiguous="NaT").tz_convert("UTC")
    return utc.as_unit("us")
