"""LBNL Building 59 case study (T040): does the whole-building detector react to known events?

One office building in Berkeley, California, 2018-2020 (CC0, Dryad doi:10.7941/D1N33Q, obtained
with `python -m wattwise.data.dryad fetch lbnl59`). It has five electricity sub-meters, rooftop-unit
(RTU) control points and, for nine months, measured occupancy. This module runs WattWise's default
detector (the rolling same-hour z-score, D030) on a whole-building series and compares its events
with the end uses, the RTU outdoor-air dampers, outdoor temperature, occupancy, and dated events.

What the data is, and what it is not (docs/reports/lbnl59-case-study.md has the evidence):

- **The "whole-building" series is derived:** the sum of the five metered end uses (`mels_S`,
  `lig_S`, `mels_N`, `hvac_N`, `hvac_S`, kW). There is no north-wing lighting column and no
  whole-building meter in the files, so it is a sub-metered total, not the building's bill.
- **Clocks are inferred, not documented.** Energy, weather, RTU and occupancy timestamps behave
  like UTC (solar radiation peaks near 20:30, and the morning lighting ramp moves one clock hour
  between winter and summer, as it would for people keeping daylight-saving time).
- **Imputed values are not flagged.** The authors filled gaps (linear interpolation, KNN, matrix
  factorisation) and published the raw missing rates per column. Only one kind of fill leaves a
  trace: a run of points on an exact straight line. Those runs (at least `MIN_LINEAR_POINTS`
  points, not constant) are masked as *suspected* interpolation. Constant runs are kept: lights
  off at night are genuinely flat. KNN and matrix-factorisation fills cannot be identified, so
  some imputed values remain; the report compares the masked share with the raw missing rate.
- **Dated events:** the Bay Area shelter-in-place order (from 2020-03-17, sourced), and spans where
  every RTU's outdoor-air damper was held at its 10 % minimum through the working day, found in the
  data itself. That some of those spans coincide with sourced wildfire-smoke alerts is a
  hypothesis about why the dampers closed, not something the dataset documents.

The end-use breakdown of an event is arithmetic (the total is the sum of the end uses, and the
detector's baseline is a mean, so deviations add up). It says where the deviation was metered,
not why it happened. An event is an anomaly to investigate, not confirmed waste.

    uv run python -m wattwise.ml.lbnl59 --report ../docs/reports/lbnl59-case-study.md
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import pandas as pd

from wattwise.ml.detection import (
    DETECTOR_DEFAULTS,
    ROLLING_DAYS,
    Detector,
    DetectorConfig,
    detect,
    rolling_same_hour,
)
from wattwise.ml.evaluation import compute_metrics

CASE_STUDY_VERSION: Final = "1"
TIMEZONE: Final = "America/Los_Angeles"
BUILDING_ID: Final = "lbnl59"
METER_ID: Final = "lbnl59-sum-of-end-uses"
END_USES: Final = ("mels_S", "lig_S", "mels_N", "hvac_N", "hvac_S")
#: Raw-data missing rates, 2018-2020, from the authors'
#: data_description_table_3year_clean_data.xlsx.
RAW_MISSING_RATE: Final = {
    "mels_S": 0.3292,
    "lig_S": 0.1817,
    "mels_N": 0.1969,
    "hvac_N": 0.0811,
    "hvac_S": 0.0810,
}
MIN_LINEAR_POINTS: Final = 6  # 1.5 hours of 15-minute points on one straight line
LINEAR_TOLERANCE: Final = 1e-6  # kW; the files store float32-like values
DAMPER_MINIMUM: Final = 10.0  # % open: the value the RTU dampers are held at in the data
DAMPER_TOLERANCE: Final = 0.5
WORKDAY_HOURS: Final = range(8, 17)  # local clock hours checked for a damper held at minimum
MIN_DAMPER_HOURS: Final = 6  # of those 9 hours
SHELTER_IN_PLACE: Final = {
    "name": "Bay Area shelter-in-place order",
    "start": "2020-03-17",
    "end": "2020-04-07",
    "source": "https://elementsarchive.lbl.gov/2020/03/17/shelter-in-place-order-for-six-bay-area-counties/",
    "quote": "Six Bay Area counties have ordered all residents to shelter-in-place beginning "
    "March 17 and lasting until at least April 7. ... This includes the Lab.",
}
SMOKE_ALERTS: Final = (
    {
        "dates": "2020-08-18 to 2020-08-19",
        "source": "https://www.baaqmd.gov/News-and-Events/Page-Resources/2020-News/081820-STA",
        "quote": "Spare the Air Alerts for wildfire smoke for today, Tuesday, August 18, and "
        "tomorrow, Wednesday, August 19",
    },
    {
        "dates": "through 2020-09-11 (the 24th and 25th consecutive alert)",
        "source": "https://www.baaqmd.gov/News-and-Events/Page-Resources/2020-News/090920-STA",
        "quote": "extending the Spare the Air Alert for wildfire smoke through Friday, "
        "September 11",
    },
)
#: 2020-08-18 is the first sourced smoke alert; the end is the extension "through Friday,
#: September 11", called as "the 24th and 25th consecutive" alert, which fits a run from Aug 18.
SMOKE_PERIOD: Final = (date(2020, 8, 18), date(2020, 9, 11))
TRAIN_END: Final = pd.Timestamp("2020-01-01", tz=TIMEZONE)  # the profile learns 2018-2019 only
DEFAULT_ARCHIVE: Final = Path("../data/raw/lbnl59/Building_59.zip")
DEFAULT_OUTPUT: Final = Path("../data/processed/lbnl59")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_points(archive: Path | zipfile.ZipFile, name: str) -> pd.DataFrame:
    """One CSV of `Bldg59_clean data/` with a UTC index (the inferred clock), sorted, without
    duplicate timestamps or the empty column a trailing comma creates."""
    handle = archive if isinstance(archive, zipfile.ZipFile) else zipfile.ZipFile(archive)
    matches = [
        n for n in handle.namelist() if n.endswith(f"/{name}") and not n.startswith("__MACOSX")
    ]
    if len(matches) != 1:
        raise FileNotFoundError(f"{name} is not in the archive (found {len(matches)}).")
    frame = pd.read_csv(io.BytesIO(handle.read(matches[0])))
    frame = frame.loc[:, ~frame.columns.astype(str).str.startswith("Unnamed")]
    stamps = pd.to_datetime(frame.pop("date"), format="mixed").dt.tz_localize("UTC")
    frame.index = pd.DatetimeIndex(stamps, name="timestamp")
    frame = frame[~frame.index.duplicated()].sort_index()
    numeric: pd.DataFrame = frame.apply(pd.to_numeric, errors="coerce")
    return numeric


# ---------------------------------------------------------------------------
# Suspected interpolation and the hourly series
# ---------------------------------------------------------------------------


def suspected_interpolation(
    values: pd.Series,
    min_points: int = MIN_LINEAR_POINTS,
    tolerance: float = LINEAR_TOLERANCE,
) -> pd.Series:
    """True for points in a run of at least `min_points` consecutive points on one non-flat
    straight line (equal steps that are not zero). `values` is on a regular grid."""
    v = values.to_numpy(dtype=float)
    step = np.diff(v)
    same_step = np.abs(np.diff(step)) < tolerance  # step i+1 equals step i
    moving = np.abs(step[1:]) >= tolerance
    link = same_step & moving  # points i, i+1, i+2 lie on one sloped line
    flags = np.zeros(len(v), dtype=bool)
    start = None
    for i, linked in enumerate([*link.tolist(), False]):
        if linked and start is None:
            start = i
        elif not linked and start is not None:
            points = i - start + 2  # links start..i-1 cover points start..i+1
            if points >= min_points:
                flags[start : i + 2] = True
            start = None
    return pd.Series(flags, index=values.index)


def quarter_hour_grid(ele: pd.DataFrame) -> pd.DataFrame:
    """The end uses on a complete 15-minute UTC grid. Off-grid points (the files hold some
    5- and 10-minute timestamps) are dropped, and missing slots are NaN."""
    stamps = pd.DatetimeIndex(ele.index)
    on_grid = ele[(stamps.minute % 15 == 0) & (stamps.second == 0)]
    grid = pd.date_range(on_grid.index.min(), on_grid.index.max(), freq="15min", name="timestamp")
    return on_grid.reindex(grid)[list(END_USES)]


def hourly_end_uses(grid: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, float]]]:
    """Mean kW per hour (= kWh in the hour) for each end use, and the masking summary.

    A point suspected of interpolation is removed; an hour needs all four quarter-hours of every
    end use, so that the end uses always add up to the total over the same hours."""
    masked = grid.copy()
    summary: dict[str, dict[str, float]] = {}
    for column in END_USES:
        flags = suspected_interpolation(grid[column])
        masked.loc[flags.to_numpy(), column] = np.nan
        summary[column] = {
            "raw_missing_rate": RAW_MISSING_RATE[column],
            "suspected_interpolation_share": round(float(flags.mean()), 4),
            "missing_in_clean_file_share": round(float(grid[column].isna().mean()), 4),
        }
    complete = masked.notna().all(axis=1)
    hour = pd.DatetimeIndex(masked.index).floor("h")
    counts = complete.groupby(hour).sum()
    hourly = masked.groupby(hour).mean()
    hourly.loc[counts.reindex(hourly.index).to_numpy() < 4, :] = np.nan
    hourly.index.name = "timestamp"
    return hourly, summary


def readings_from(hourly: pd.DataFrame, column: str | None = None) -> pd.DataFrame:
    """WattWise's readings frame for the total (or one end use), present hours only."""
    values = hourly.sum(axis=1, min_count=len(END_USES)) if column is None else hourly[column]
    values = values.dropna()
    return pd.DataFrame(
        {
            "meter_id": METER_ID if column is None else f"lbnl59-{column}",
            "building_id": BUILDING_ID,
            "timestamp": values.index,
            "value": values.to_numpy(dtype=float),
        }
    )


# ---------------------------------------------------------------------------
# Detection and the per-event comparison
# ---------------------------------------------------------------------------


def detect_events(readings: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The default detector's classified events, and every hour of every event."""
    from wattwise.ml.signatures import classify  # signatures imports detection

    config = DetectorConfig(**DETECTOR_DEFAULTS[Detector.ROLLING_Z])  # type: ignore[arg-type]
    z, baseline = rolling_same_hour(readings, floor_fraction=config.scale_floor_fraction)
    every = np.ones(len(readings), dtype=bool)
    detection = detect(readings, baseline, None, every, config, z=z)
    buildings = pd.DataFrame({"building_id": [BUILDING_ID], "timezone": [TIMEZONE]})
    return classify(detection, buildings, config.z_off), detection.hours


def rolling_baselines(hourly: pd.DataFrame) -> pd.DataFrame:
    """Each end use's rolling same-hour mean (the detector's baseline), on the hours where the
    total exists. Means are linear, so these add up to the total's baseline."""
    present = hourly.dropna()
    result = {}
    for column in END_USES:
        readings = readings_from(present, column)
        _, mean = rolling_same_hour(readings)
        result[column] = pd.Series(mean.to_numpy(dtype=float), index=readings["timestamp"])
    return pd.DataFrame(result)


def same_hour_reference(series: pd.Series, hours: pd.DatetimeIndex) -> tuple[float, float, int]:
    """Mean of `series` over `hours`, the mean over the same hours on the `ROLLING_DAYS` days
    before the first of them (the detector's own reference), and how many event hours had data."""
    during = series.reindex(hours)
    before = pd.DatetimeIndex(
        [h - pd.Timedelta(days=d) for d in range(1, ROLLING_DAYS + 1) for h in hours]
    )
    before = before[before < hours.min()]
    reference = series.reindex(before)
    return (
        _round(float(during.mean())) if during.notna().any() else np.nan,
        _round(float(reference.mean())) if reference.notna().any() else np.nan,
        int(during.notna().sum()),
    )


def describe_event(
    event: pd.Series,
    hours: pd.DataFrame,
    hourly: pd.DataFrame,
    baselines: pd.DataFrame,
    context: dict[str, pd.Series],
) -> dict[str, Any]:
    """An event with its end-use breakdown and the context points."""
    times = pd.DatetimeIndex(hours["timestamp"])
    observed = hours["value"].notna().to_numpy()
    present = times[observed]
    deviation = (hourly.reindex(present) - baselines.reindex(present)).sum()
    total = float(deviation.sum())
    local = pd.DatetimeIndex([event["start"], event["end"]]).tz_convert(TIMEZONE)
    record: dict[str, Any] = {
        "start_local": local[0].strftime("%Y-%m-%d %H:%M"),
        "end_local": local[1].strftime("%Y-%m-%d %H:%M"),
        "direction": str(event["direction"]),
        "signature": str(event["signature"]),
        "duration_hours": int(event["duration_hours"]),
        "peak_z": _round(float(event["peak_z"])),
        "deviation_kwh": _round(total),
        "end_use_deviation_kwh": {c: _round(float(deviation[c])) for c in END_USES},
        "largest_end_use": str(deviation.abs().idxmax()) if len(present) else None,
    }
    for name, series in context.items():
        during, reference, covered = same_hour_reference(series, times)
        record[name] = {"event_mean": during, "reference_mean": reference, "hours": covered}
    return record


# ---------------------------------------------------------------------------
# Dated events
# ---------------------------------------------------------------------------


def damper_minimum_days(dampers: pd.DataFrame) -> list[date]:
    """Local weekdays on which every RTU's outdoor-air damper was at its 10 % minimum for at
    least `MIN_DAMPER_HOURS` of the working hours (hourly means)."""
    hourly = dampers.resample("h").mean()
    at_minimum = (hourly - DAMPER_MINIMUM).abs().le(DAMPER_TOLERANCE).all(axis=1)
    at_minimum = at_minimum & hourly.notna().all(axis=1)
    local = at_minimum.tz_convert(TIMEZONE)
    stamps = pd.DatetimeIndex(local.index)
    work = local[(stamps.dayofweek < 5) & stamps.hour.isin(list(WORKDAY_HOURS))]
    per_day = work.groupby(pd.DatetimeIndex(work.index).date).sum()
    return sorted(cast(date, d) for d, n in per_day.items() if n >= MIN_DAMPER_HOURS)


def spans(days: Sequence[date], max_gap_days: int = 3) -> list[tuple[date, date, int]]:
    """Group days into spans; gaps of up to `max_gap_days` (a weekend) are bridged."""
    result: list[tuple[date, date, int]] = []
    for day in sorted(days):
        if result and (day - result[-1][1]).days <= max_gap_days:
            first, _, count = result[-1]
            result[-1] = (first, day, count + 1)
        else:
            result.append((day, day, 1))
    return result


def overlapping(events: pd.DataFrame, start: date, end: date) -> list[int]:
    """Rows of `events` whose local dates overlap [start, end]."""
    first = pd.Timestamp(start, tz=TIMEZONE)
    last = pd.Timestamp(end, tz=TIMEZONE) + pd.Timedelta(days=1)
    starts, ends = pd.to_datetime(events["start"]), pd.to_datetime(events["end"])
    return [i for i in range(len(events)) if starts.iloc[i] < last and ends.iloc[i] >= first]


# ---------------------------------------------------------------------------
# The case study
# ---------------------------------------------------------------------------


def baseline_accuracy(readings: pd.DataFrame) -> list[dict[str, Any]]:
    """Two baselines scored on each month of 2020 (chronological: both see only the past):
    the hour-of-week median profile (T012) learned on 2018-2019, and the detector's own rolling
    same-hour mean (the previous 14 days). The first measures how far 2020 departed from the
    earlier years; the second, how closely the baseline the detector uses kept up."""
    from wattwise.ml.baselines import HourOfWeekProfile

    profile = HourOfWeekProfile({BUILDING_ID: TIMEZONE})
    stamps = pd.DatetimeIndex(readings["timestamp"])
    profile.fit(readings[stamps < TRAIN_END])
    _, rolling = rolling_same_hour(readings)
    test = stamps >= TRAIN_END
    rows = readings[test]
    predicted = {
        "profile": profile.predict(rows.drop(columns="value"), readings).to_numpy(),
        "rolling": rolling[test].to_numpy(dtype=float),
    }
    months = pd.DatetimeIndex(rows["timestamp"]).tz_convert(TIMEZONE).strftime("%Y-%m")
    actual = rows["value"].to_numpy(dtype=float)
    result = []
    for month in sorted(set(months)):
        mask = np.asarray(months == month)
        record: dict[str, Any] = {"month": month}
        for name, values in predicted.items():
            m = compute_metrics(actual[mask], values[mask])
            record[name] = {"hours": m.scored, "mae_kwh": m.mae, "wape": m.wape, "bias_kwh": m.bias}
        result.append(record)
    return result


def yearly_levels(hourly: pd.DataFrame, grid: pd.DataFrame) -> list[dict[str, Any]]:
    """Per local year: hours used, each end use's mean kW (used hours), and the share of its
    clean-file values with at most two decimals (a change in it marks a change in recording)."""
    local = hourly.tz_convert(TIMEZONE)
    used = local.notna().all(axis=1)
    grid_local = grid.tz_convert(TIMEZONE)
    rows = []
    years = pd.DatetimeIndex(local.index).year
    grid_years = pd.DatetimeIndex(grid_local.index).year
    for year in sorted(set(years)):
        part = local[(years == year) & used]
        values = grid_local[grid_years == year]
        if part.empty:
            continue
        record: dict[str, Any] = {"year": int(year), "hours_used": len(part)}
        for column in END_USES:
            v = values[column].dropna().to_numpy(dtype=float)
            two_decimals = np.abs(v * 100 - np.round(v * 100)) < 1e-4
            record[column] = {
                "mean_kw": _round(float(part[column].mean())),
                "two_decimal_share": _round(float(two_decimals.mean())) if v.size else None,
            }
        rows.append(record)
    return rows


def weekly_around(total: pd.Series, start: date, weeks: int = 4) -> list[dict[str, Any]]:
    """Mean kW of the total in the `weeks` 7-day windows before and after `start` (local)."""
    first = pd.Timestamp(start, tz=TIMEZONE)
    rows = []
    for k in range(-weeks, weeks):
        a, b = first + pd.Timedelta(days=7 * k), first + pd.Timedelta(days=7 * (k + 1))
        part = total[(total.index >= a) & (total.index < b)]
        rows.append(
            {
                "week_from": a.strftime("%Y-%m-%d"),
                "mean_kw": _round(float(part.mean())) if part.notna().any() else None,
                "hours": int(part.notna().sum()),
            }
        )
    return rows


def window_weather(temperature: pd.Series, first: date, last: date) -> dict[str, Any]:
    """Mean outdoor temperature over local working hours during [first, last] and over the 14
    days before."""
    local = temperature.tz_convert(TIMEZONE)
    work = local[pd.DatetimeIndex(local.index).hour.isin(list(WORKDAY_HOURS))].dropna()
    days = np.asarray(pd.DatetimeIndex(work.index).date)
    during = work[(days >= first) & (days <= last)]
    before = work[(days >= first - timedelta(days=14)) & (days < first)]
    return {
        "event_mean": _round(float(during.mean())) if len(during) else np.nan,
        "reference_mean": _round(float(before.mean())) if len(before) else np.nan,
        "hours": len(during),
    }


def run(archive: Path) -> dict[str, Any]:
    """The whole case study, as a JSON-ready dict."""
    handle = zipfile.ZipFile(archive)
    grid = quarter_hour_grid(read_points(handle, "ele.csv"))
    hourly, masking = hourly_end_uses(grid)
    readings = readings_from(hourly)
    events, hours = detect_events(readings)
    baselines = rolling_baselines(hourly)

    dampers = read_points(handle, "rtu_oa_damper.csv")
    weather = read_points(handle, "site_weather.csv")
    occupancy = read_points(handle, "occ.csv")
    context = {
        "rtu_damper_pct": dampers.resample("h").mean().mean(axis=1),
        "outdoor_temp_c": weather["air_temp_set_1"].resample("h").mean(),
        "occupant_count": occupancy.sum(axis=1, min_count=1).resample("h").mean(),
    }
    described = [
        describe_event(event, hours[hours["event"] == i], hourly, baselines, context)
        for i, (_, event) in enumerate(events.iterrows())
    ]

    shelter_start = date.fromisoformat(SHELTER_IN_PLACE["start"])
    shelter_end = date.fromisoformat(SHELTER_IN_PLACE["end"])
    damper_spans = spans(damper_minimum_days(dampers))
    temperature = context["outdoor_temp_c"]
    windows = [
        {
            "kind": "shelter-in-place",
            "start": shelter_start.isoformat(),
            "end": shelter_end.isoformat(),
            "basis": "sourced date",
            "events": overlapping(events, shelter_start, shelter_end),
            "outdoor_temp_c": window_weather(temperature, shelter_start, shelter_end),
        }
    ] + [
        {
            "kind": "damper-at-minimum",
            "start": first.isoformat(),
            "end": last.isoformat(),
            "days": count,
            "basis": "observed in the RTU data",
            "in_smoke_alert_period": first <= SMOKE_PERIOD[1] and last >= SMOKE_PERIOD[0],
            "events": overlapping(events, first, last),
            "outdoor_temp_c": window_weather(temperature, first, last),
        }
        for first, last, count in damper_spans
    ]
    total = readings.set_index("timestamp")["value"].reindex(hourly.index)
    in_windows = {i for w in windows for i in cast(list[int], w["events"])}
    signatures = events.groupby(["signature", "direction"]).size() if len(events) else None
    total_hours = len(hourly)
    return {
        "case_study_version": CASE_STUDY_VERSION,
        "dataset": "LBNL Building 59 (Dryad doi:10.7941/D1N33Q, version 162054, CC0 1.0)",
        "series": {
            "meter": METER_ID,
            "definition": "sum of the five metered end uses "
            + ", ".join(END_USES)
            + " (kW, hourly mean = kWh); derived, not a whole-building meter",
            "first_local": _local(readings["timestamp"].min()),
            "last_local": _local(readings["timestamp"].max()),
            "hours_in_period": total_hours,
            "hours_used": len(readings),
            "hours_masked_or_missing": total_hours - len(readings),
        },
        "masking": masking,
        "detector": {
            "name": Detector.ROLLING_Z.value,
            "config": DetectorConfig(**DETECTOR_DEFAULTS[Detector.ROLLING_Z]).model_dump(),  # type: ignore[arg-type]
        },
        "yearly_levels": yearly_levels(hourly, grid),
        "baselines_2020_by_month": baseline_accuracy(readings),
        "weeks_around_shelter_in_place": weekly_around(total, shelter_start),
        "smoke_alert_period": [d.isoformat() for d in SMOKE_PERIOD],
        "events_total": len(described),
        "events_by_signature": (
            {
                f"{s} ({d})": int(n)
                for (s, d), n in cast(dict[tuple[str, str], int], signatures.to_dict()).items()
            }
            if signatures is not None
            else {}
        ),
        "dated_windows": windows,
        "smoke_alert_sources": list(SMOKE_ALERTS),
        "shelter_in_place_source": SHELTER_IN_PLACE,
        "events": described,
        "events_outside_windows": len(described) - len(in_windows),
    }


def to_markdown(report: dict[str, Any]) -> str:
    """The case study's results section (the narrative lives in the committed report)."""
    s = report["series"]
    lines = [
        "## Results (generated by `python -m wattwise.ml.lbnl59`)",
        "",
        f"- **Series:** {s['definition']}.",
        f"- **Period (local):** {s['first_local']} to {s['last_local']}; {s['hours_used']:,} of "
        f"{s['hours_in_period']:,} hours used ({s['hours_masked_or_missing']:,} masked or "
        "missing).",
        f"- **Detector:** `{report['detector']['name']}` with its default thresholds.",
        "",
        "### Masking: suspected interpolation against the authors' raw missing rates",
        "",
        "| End use | Raw missing rate (authors) | Masked as suspected interpolation | Unknown "
        "imputed share left (at least) |",
        "|---|---|---|---|",
    ]
    for column, m in report["masking"].items():
        left = max(m["raw_missing_rate"] - m["suspected_interpolation_share"], 0.0)
        lines.append(
            f"| `{column}` | {m['raw_missing_rate']:.1%} | {m['suspected_interpolation_share']:.1%}"
            f" | {left:.1%} |"
        )
    lines += [
        "",
        "### Level of each end use by year (mean kW over used hours)",
        "",
        "Share of the year's clean-file values with at most two decimals in brackets: a change in "
        "it marks a change in how values were recorded or processed.",
        "",
        "| Year | Hours used | " + " | ".join(f"`{c}`" for c in END_USES) + " |",
        "|---|---|" + "---|" * len(END_USES),
    ]
    for row in report["yearly_levels"]:
        cells = " | ".join(
            f"{_num(row[c]['mean_kw'])} ({_share(row[c]['two_decimal_share'])})" for c in END_USES
        )
        lines.append(f"| {row['year']} | {row['hours_used']:,} | {cells} |")
    lines += [
        "",
        "### Baselines scored on each month of 2020",
        "",
        "The profile learned 2018-2019; the rolling mean is the detector's own baseline "
        "(the same hour on the previous 14 days).",
        "",
        "| Month | Hours | Profile MAE (kWh) | Profile WAPE | Profile bias (kWh) | Rolling MAE "
        "(kWh) | Rolling WAPE |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["baselines_2020_by_month"]:
        p, r = row["profile"], row["rolling"]
        lines.append(
            f"| {row['month']} | {p['hours']} | {_num(p['mae_kwh'])} | {_share(p['wape'])} | "
            f"{_num(p['bias_kwh'])} | {_num(r['mae_kwh'])} | {_share(r['wape'])} |"
        )
    lines += [
        "",
        "### Weeks around the shelter-in-place order (7-day windows from 2020-03-17, local)",
        "",
        "| Week from | Mean kW | Hours |",
        "|---|---|---|",
    ]
    for row in report["weeks_around_shelter_in_place"]:
        lines.append(f"| {row['week_from']} | {_num(row['mean_kw'])} | {row['hours']} |")
    lines += [
        "",
        f"### Events: {report['events_total']} in total, "
        f"{report['events_outside_windows']} outside the dated windows",
        "",
        "| Signature (direction) | Events |",
        "|---|---|",
    ]
    for name, count in sorted(report["events_by_signature"].items()):
        lines.append(f"| {name} | {count} |")
    lines += [
        "",
        "### Dated windows and the events that overlap them",
        "",
        f"Smoke-alert period (sourced): {report['smoke_alert_period'][0]} to "
        f"{report['smoke_alert_period'][1]}. Outdoor temperature is the working-hours mean in the "
        "window and in the 14 days before it.",
        "",
        "| Window (local dates) | Basis | In smoke-alert period | Outdoor °C (window / before) "
        "| Overlapping events | Largest deviation by end use |",
        "|---|---|---|---|---|---|",
    ]
    for window in report["dated_windows"]:
        label = f"{window['kind']} {window['start']} to {window['end']}"
        smoke = {True: "yes", False: "no"}.get(window.get("in_smoke_alert_period"), "")
        head = f"| {label} | {window['basis']} | {smoke} | {_pair(window['outdoor_temp_c'])} |"
        if not window["events"]:
            lines.append(f"{head} none | |")
        for i in window["events"]:
            e = report["events"][i]
            lines.append(
                f"{head} {e['direction']} {e['signature']}, {e['start_local']} to "
                f"{e['end_local']}, {_num(e['deviation_kwh'])} kWh | `{e['largest_end_use']}` "
                f"{_num(e['end_use_deviation_kwh'][e['largest_end_use']])} kWh |"
            )
    lines += [
        "",
        "### The ten largest events by absolute deviation",
        "",
        "| Start to end (local) | Direction, signature | Deviation (kWh) | By end use (kWh) | "
        "Damper % (event / before) | Occupants (event / before) |",
        "|---|---|---|---|---|---|",
    ]
    largest = sorted(report["events"], key=lambda e: -abs(e["deviation_kwh"] or 0.0))[:10]
    for e in largest:
        parts = ", ".join(f"{k} {_num(v)}" for k, v in e["end_use_deviation_kwh"].items())
        lines.append(
            f"| {e['start_local']} to {e['end_local']} | {e['direction']}, {e['signature']} | "
            f"{_num(e['deviation_kwh'])} | {parts} | {_pair(e['rtu_damper_pct'])} | "
            f"{_pair(e['occupant_count'])} |"
        )
    return "\n".join(lines) + "\n"


def write(report: dict[str, Any], output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path, md_path = output / "case_study.json", output / "case_study.md"
    json_path.write_text(
        json.dumps(_finite(report), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(to_markdown(report), encoding="utf-8", newline="\n")
    return [json_path, md_path]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.ml.lbnl59",
        description="Run the LBNL Building 59 detector case study (T040).",
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--report", type=Path, help="also replace the generated section of this Markdown report"
    )
    args = parser.parse_args(argv)
    if not args.archive.exists():
        print(
            f"error: {args.archive} is missing. Run: uv run python -m wattwise.data.dryad fetch "
            "lbnl59",
            file=sys.stderr,
        )
        return 1
    report = run(args.archive)
    for path in write(report, args.output):
        print(f"wrote {path}")
    if args.report:
        update_report(args.report, to_markdown(report))
        print(f"updated {args.report}")
    return 0


MARKER: Final = "<!-- generated: python -m wattwise.ml.lbnl59 -->"


def update_report(path: Path, generated: str) -> None:
    """Replace everything after `MARKER` in `path` with `generated` (the narrative above the
    marker is written by hand)."""
    text = path.read_text(encoding="utf-8")
    if MARKER not in text:
        raise ValueError(f"{path} has no line {MARKER!r}.")
    head = text.split(MARKER, 1)[0]
    path.write_text(f"{head}{MARKER}\n\n{generated}", encoding="utf-8", newline="\n")


def _round(value: float) -> float:
    return round(value, 3)


def _num(value: float | None) -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:,.1f}"


def _share(value: float | None) -> str:
    return "n/a" if value is None or not np.isfinite(value) else f"{value:.0%}"


def _pair(values: dict[str, Any]) -> str:
    if not values["hours"]:
        return "no data"
    return f"{_num(values['event_mean'])} / {_num(values['reference_mean'])}"


def _local(value: Any) -> str:
    return pd.Timestamp(value).tz_convert(TIMEZONE).strftime("%Y-%m-%d %H:%M")


def _finite(value: Any) -> Any:
    """NaN becomes None, so the JSON is strict."""
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return _finite(float(value))
    return value


if __name__ == "__main__":
    raise SystemExit(main())
