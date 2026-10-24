import numpy as np
import pandas as pd
import pytest

from tests.data.conftest import on_bdg2_grid
from wattwise.data.time_convention import (
    Clock,
    ShiftEvidence,
    Signal,
    classify,
    nonexistent_hours,
    profile_shift,
    to_utc,
    transitions,
    winter_offset,
)

UTC = pd.date_range("2015-12-31", "2018-01-02", freq="h", tz="UTC")


def human_load(timezone: str, flat: bool = False, seed: int = 0) -> pd.Series:
    """Occupied 08:00-18:00 on weekdays by the *wall clock*, like a real building."""
    rng = np.random.default_rng(seed)
    wall = UTC.tz_convert(timezone)
    occupied = np.asarray((wall.hour >= 8) & (wall.hour < 18) & (wall.dayofweek < 5))
    load = 40 + rng.normal(0, 1.5, len(UTC)) + (0 if flat else 60 * occupied)
    return pd.Series(load, index=UTC)


def solar_temperature(timezone: str) -> pd.Series:
    """Warmest at 15:00 *solar* (standard) time, independent of the clock change."""
    solar = (UTC.tz_localize(None) + winter_offset(timezone, 2016)).hour
    return pd.Series(10 + 6 * np.cos(2 * np.pi * (solar - 15) / 24), index=UTC)


def verdict(series: pd.Series, timezone: str, clock: Clock, signal: Signal) -> Clock:
    frame = on_bdg2_grid(series, timezone, clock).to_frame("x")
    evidence = [
        profile_shift(frame, t, weekdays_only=signal is Signal.HUMAN)
        for t in transitions(timezone, "2016-01-01", "2018-01-01")
    ]
    return classify(evidence, signal).clock


# ---------------------------------------------------------------------------
# Time-zone facts
# ---------------------------------------------------------------------------


def test_transitions_come_from_the_time_zone_database() -> None:
    us = transitions("US/Eastern", "2016-01-01", "2018-01-01")
    uk = transitions("Europe/London", "2016-01-01", "2018-01-01")

    assert [(t.day, t.kind) for t in us] == [
        ("2016-03-13", "spring"),
        ("2016-11-06", "autumn"),
        ("2017-03-12", "spring"),
        ("2017-11-05", "autumn"),
    ]
    assert [t.day for t in uk] == ["2016-03-27", "2016-10-30", "2017-03-26", "2017-10-29"]
    assert transitions("UTC", "2016-01-01", "2018-01-01") == []


@pytest.mark.parametrize(
    ("timezone", "hours"),
    [("US/Eastern", -5), ("US/Pacific", -8), ("Europe/London", 0), ("Europe/Dublin", 0)],
)
def test_winter_offset_is_the_january_offset(timezone: str, hours: int) -> None:
    # Europe/Dublin models winter as negative daylight saving; the total offset is still 0.
    assert winter_offset(timezone, 2016) == pd.Timedelta(hours=hours)


def test_nonexistent_hours_are_the_skipped_spring_hours() -> None:
    assert nonexistent_hours("US/Eastern", "2016-01-01", "2018-01-01") == [
        pd.Timestamp("2016-03-13 02:00"),
        pd.Timestamp("2017-03-12 02:00"),
    ]
    assert nonexistent_hours("Europe/London", "2016-01-01", "2017-01-01") == [
        pd.Timestamp("2016-03-27 01:00")
    ]


# ---------------------------------------------------------------------------
# Conversion to UTC
# ---------------------------------------------------------------------------


def test_standard_time_uses_the_fixed_winter_offset_all_year() -> None:
    naive = pd.DatetimeIndex(["2016-01-15 12:00", "2016-07-01 12:00", "2016-03-13 02:00"])

    utc = to_utc(naive, "US/Eastern", Clock.STANDARD)

    assert list(utc.strftime("%H:%M")) == ["17:00", "17:00", "07:00"]
    assert not np.any(utc.isna()), "every standard-time hour exists"
    assert str(utc.dtype) == "datetime64[us, UTC]"


def test_wall_clock_time_follows_daylight_saving() -> None:
    naive = pd.DatetimeIndex(["2016-01-15 12:00", "2016-07-01 12:00"])

    assert list(to_utc(naive, "US/Eastern", Clock.WALL_CLOCK).strftime("%H:%M")) == [
        "17:00",
        "16:00",
    ]


def test_wall_clock_hours_that_do_not_exist_or_repeat_are_not_guessed() -> None:
    naive = pd.DatetimeIndex(["2016-03-13 02:00", "2016-11-06 01:00", "2016-11-06 03:00"])

    utc = to_utc(naive, "US/Eastern", Clock.WALL_CLOCK)

    assert list(utc.isna()) == [True, True, False]


def test_undetermined_or_aware_input_cannot_be_converted() -> None:
    with pytest.raises(ValueError, match="undetermined"):
        to_utc(pd.DatetimeIndex(["2016-01-01"]), "US/Eastern", Clock.UNDETERMINED)
    with pytest.raises(ValueError, match="naive"):
        to_utc(pd.DatetimeIndex(["2016-01-01"], tz="UTC"), "US/Eastern", Clock.STANDARD)


# ---------------------------------------------------------------------------
# Classification on series with a known convention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("timezone", ["US/Eastern", "Europe/London"])
@pytest.mark.parametrize("clock", [Clock.STANDARD, Clock.WALL_CLOCK])
def test_building_load_reveals_its_clock(timezone: str, clock: Clock) -> None:
    assert verdict(human_load(timezone), timezone, clock, Signal.HUMAN) is clock


@pytest.mark.parametrize("clock", [Clock.STANDARD, Clock.WALL_CLOCK])
def test_solar_temperature_reveals_its_clock(clock: Clock) -> None:
    assert verdict(solar_temperature("US/Eastern"), "US/Eastern", clock, Signal.SOLAR) is clock


def test_a_flat_round_the_clock_load_proves_nothing() -> None:
    load = human_load("US/Eastern", flat=True)

    assert verdict(load, "US/Eastern", Clock.WALL_CLOCK, Signal.HUMAN) is Clock.UNDETERMINED


def evidence(kind: str, scores: dict[int, float]) -> ShiftEvidence:
    return ShiftEvidence(day="2016-03-13", kind=kind, series=10, scores=scores)


def test_lag_and_margin_come_from_the_scores() -> None:
    e = evidence("spring", {-1: 0.97, 0: 0.99, 1: 0.95})

    assert (e.lag, round(e.margin, 6)) == (0, 0.02)
    assert evidence("spring", {}).lag is None


def test_a_verdict_must_hold_at_every_margin() -> None:
    borderline = [
        evidence("spring", {-1: 0.950, 0: 0.957, 1: 0.90}),  # margin 0.007
        evidence("autumn", {-1: 0.90, 0: 0.957, 1: 0.950}),
        evidence("spring", {-1: 0.950, 0: 0.957, 1: 0.90}),
    ]

    result = classify(borderline, Signal.HUMAN)

    assert result.clock is Clock.UNDETERMINED
    assert "sensitive to the margin" in result.reason


def test_one_usable_transition_is_not_enough() -> None:
    result = classify([evidence("spring", {-1: 0.9, 0: 0.99, 1: 0.9})], Signal.HUMAN)

    assert result.clock is Clock.UNDETERMINED
    assert "only 1 usable" in result.reason


def test_mixed_evidence_is_undetermined() -> None:
    mixed = [
        evidence("spring", {-1: 0.99, 0: 0.9, 1: 0.8}),
        evidence("autumn", {-1: 0.8, 0: 0.99, 1: 0.9}),
    ]

    assert classify(mixed, Signal.HUMAN).clock is Clock.UNDETERMINED
