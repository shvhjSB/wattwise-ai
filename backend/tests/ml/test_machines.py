"""T066: the machine comparison's figures, on the synthetic test factory where all are known."""

import numpy as np
import pandas as pd
import pytest

from tests.factory_data import MAIN, PRESS, PUMP, TIMEZONE, factory_tables
from wattwise.ml.machines import OpenHours, compare, figures

WEEKDAYS = OpenHours(frozenset(range(5)), 6, 18)


def electricity() -> pd.DataFrame:
    _, readings = factory_tables()
    frame = readings[readings["meter_type"] == "electricity"].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["value"] = frame["value"].astype(float)
    return frame[["meter_id", "building_id", "timestamp", "value"]]


def test_each_meter_has_the_figures_built_into_the_factory() -> None:
    by_id = {m.meter_id: m for m in figures(electricity(), TIMEZONE, WEEKDAYS)}

    press, pump, main = by_id[PRESS], by_id[PUMP], by_id[MAIN]
    assert (press.energy_kwh, press.running_hours, press.closed_kwh) == (3280.0, 164, 80.0)
    assert press.running_threshold_kwh == 2.0 and press.peak_kwh == 20.0
    assert press.events == 1  # the night run
    assert (pump.energy_kwh, pump.running_hours, pump.closed_kwh, pump.events) == (
        1344.0,
        672,
        864.0,
        0,
    )
    assert (main.energy_kwh, main.closed_kwh, main.peak_kwh) == (24784.0, 13904.0, 52.0)
    assert pump.closed_share() == pytest.approx(864 / 1344)


def test_the_comparison_is_against_the_largest_meter_unless_one_is_named() -> None:
    result = compare(electricity(), TIMEZONE, WEEKDAYS)

    assert result["main"]["meter_id"] == MAIN and result["main"]["chosen"] is False
    assert [m["meter_id"] for m in result["machines"]] == [PRESS, PUMP]  # largest first
    assert result["machines"][0]["share_of_main"] == pytest.approx(3280 / 24784)
    assert result["unmetered_kwh"] == pytest.approx(20160.0)
    assert result["unmetered_share"] == pytest.approx(20160 / 24784)

    named = compare(electricity(), TIMEZONE, WEEKDAYS, main=PRESS)
    assert named["main"]["meter_id"] == PRESS and named["main"]["chosen"] is True
    with pytest.raises(ValueError, match="not one of"):
        compare(electricity(), TIMEZONE, WEEKDAYS, main="elsewhere")


def test_closed_hours_follow_the_buildings_local_clock() -> None:
    # Open every day 00:00 to 02:00 local: before the clocks went back (30 October 2016) that is
    # 22:00 to 00:00 UTC, after it 23:00 to 01:00 UTC.
    stamps = pd.DatetimeIndex(["2016-10-28T22:30Z", "2016-10-30T22:30Z", "2016-10-30T23:30Z"])
    hours = OpenHours(frozenset(range(7)), 0, 2)

    assert hours.is_open(stamps.tz_convert(TIMEZONE)).tolist() == [True, False, True]


def test_missing_hours_add_nothing_and_opening_hours_are_checked() -> None:
    frame = electricity()
    frame.loc[frame["meter_id"] == PUMP, "value"] = np.where(
        np.arange((frame["meter_id"] == PUMP).sum()) < 10, np.nan, 2.0
    )
    pump = {m.meter_id: m for m in figures(frame, TIMEZONE, WEEKDAYS)}[PUMP]

    assert pump.energy_kwh == 1324.0 and pump.hours_with_reading == 662
    assert pump.negative_hours == 0
    frame.loc[frame.index[(frame["meter_id"] == PUMP).to_numpy()][-2:], "value"] = -0.5
    offset = {m.meter_id: m for m in figures(frame, TIMEZONE, WEEKDAYS)}[PUMP]
    assert (offset.negative_hours, offset.negative_kwh) == (2, -1.0)
    assert offset.energy_kwh == 1324.0 - 4.0 - 1.0  # included as recorded
    with pytest.raises(ValueError, match="open days"):
        OpenHours(frozenset(), 6, 18)
    with pytest.raises(ValueError, match="opening hours"):
        OpenHours(frozenset({0}), 18, 6)
    with pytest.raises(ValueError, match="at least two"):
        compare(frame[frame["meter_id"] == PUMP], TIMEZONE, WEEKDAYS)
