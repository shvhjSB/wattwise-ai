"""Audit which clock BDG2 timestamps follow, per site (docs/DATASETS.md, D016).

BDG2 publishes naive "local" timestamps on a regular hourly grid. T007 showed that this cannot
be daylight-saving wall-clock time throughout, and this audit shows that the convention differs
between sites. For each site it collects evidence for electricity (human signal) and weather
(solar signal) and returns a verdict; UNDETERMINED sites must be excluded rather than guessed.

The verdicts are pinned in `ELECTRICITY_CLOCKS` and `WEATHER_CLOCKS`, so preprocessing is
deterministic and reviewable. Re-running the audit checks the pins against the data:

    uv run python -m wattwise.data.bdg2_audit          # needs the BDG2 download (T007)

The audit uses the corrected metadata (`wattwise.data.bdg2_sites`). A corrected time zone must
pass a zone check against the readings under the published zone, or the site is undetermined.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from wattwise.data.bdg2 import COMMIT, DEFAULT_DESTINATION, FILES_BY_KEY
from wattwise.data.bdg2_sites import CORRECTIONS, Correction, apply_corrections
from wattwise.data.time_convention import (
    DEFAULT_MARGINS,
    EXPECTED_LAG,
    MIN_USABLE,
    Clock,
    ClockVerdict,
    ShiftEvidence,
    Signal,
    classify,
    nonexistent_hours,
    profile_shift,
    repeated_hours,
    transitions,
)

PERIOD: Final = ("2016-01-01", "2018-01-01")
TIMESTAMP_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
#: A spring non-existent hour counts as a systematic gap if at least this share of live meters is
#: missing there while at most NEIGHBOUR_MISSING_MAX of them miss the adjacent hours.
GAP_MISSING_MIN: Final = 0.9
NEIGHBOUR_MISSING_MAX: Final = 0.5
#: Meters with at least this share of values over the period count as live for the gap check.
LIVE_SHARE: Final = 0.5
#: Daylight-saving fingerprints at a clock-change hour, against the same hour 1-3 weeks before and
#: after: a share of copied or interpolated readings this much above the control days, or a
#: change of this size in the hour's ratio to its neighbours (two hours merged into one).
FILL_EXCESS_MIN: Final = 0.2
RATIO_CHANGE_MIN: Final = 0.25
CONTROL_WEEKS: Final = (-3, -2, -1, 1, 2, 3)

#: Pinned verdicts from `audit()` on the BDG2 files at commit 753598e0 (run on 2026-10-23), with
#: the corrected metadata (T009c, 2026-10-24: Fox in America/Phoenix).
ELECTRICITY_CLOCKS: Final[Mapping[str, Clock]] = {
    "Bear": Clock.WALL_CLOCK,
    "Bobcat": Clock.WALL_CLOCK,
    "Bull": Clock.WALL_CLOCK,
    "Cockatoo": Clock.WALL_CLOCK,
    "Crow": Clock.WALL_CLOCK,
    "Eagle": Clock.STANDARD,
    "Fox": Clock.STANDARD,
    "Gator": Clock.WALL_CLOCK,
    "Hog": Clock.WALL_CLOCK,
    "Lamb": Clock.WALL_CLOCK,
    "Moose": Clock.STANDARD,
    "Mouse": Clock.WALL_CLOCK,
    "Panther": Clock.WALL_CLOCK,
    "Peacock": Clock.WALL_CLOCK,
    "Rat": Clock.UNDETERMINED,
    "Robin": Clock.UNDETERMINED,
    "Shrew": Clock.UNDETERMINED,
    "Swan": Clock.UNDETERMINED,
    "Wolf": Clock.STANDARD,
}
WEATHER_CLOCKS: Final[Mapping[str, Clock]] = dict.fromkeys(ELECTRICITY_CLOCKS, Clock.STANDARD)


class GapEvidence(BaseModel):
    """Missingness at a spring non-existent hour, among live meters."""

    model_config = ConfigDict(frozen=True)

    hour: str
    missing_share: float | None
    neighbour_missing_share: float | None

    @property
    def systematic(self) -> bool:
        return (
            self.missing_share is not None
            and self.neighbour_missing_share is not None
            and self.missing_share >= GAP_MISSING_MIN
            and self.neighbour_missing_share <= NEIGHBOUR_MISSING_MAX
        )


class HourEvidence(BaseModel):
    """Live meters at one clock-change hour of the published zone, against control days."""

    model_config = ConfigDict(frozen=True)

    hour: str
    kind: str
    live_meters: int
    missing_share: float | None = None
    neighbour_missing_share: float | None = None  # the emptier of the two adjacent hours
    fill_share: float | None = None  # readings equal to a neighbour or to their mean
    control_fill_share: float | None = None
    ratio: float | None = None  # median of reading / mean of the two neighbours
    control_ratio: float | None = None

    @property
    def fingerprint(self) -> str | None:
        """What marks this hour as daylight-saving wall-clock data on a grid, if anything."""
        if self.missing_share is None or self.neighbour_missing_share is None:
            return "no usable readings"
        if self.missing_share >= GAP_MISSING_MIN:
            return "the hour is empty"
        if self.neighbour_missing_share >= GAP_MISSING_MIN:
            return "an adjacent hour is empty"
        if (
            self.fill_share is not None
            and self.control_fill_share is not None
            and self.fill_share - self.control_fill_share >= FILL_EXCESS_MIN
        ):
            return "readings are copied or interpolated"
        if (
            self.ratio is not None
            and self.control_ratio is not None
            and abs(self.ratio - self.control_ratio) >= RATIO_CHANGE_MIN
        ):
            return "the reading is out of line with its neighbours (merged hours)"
        return None


class ZoneCheck(BaseModel):
    """Whether readings agree with a corrected time zone that has no daylight saving time.

    Under the published zone, occupants must not shift at its clock changes (standard-time data
    would show a 1 h shift) and no clock-change hour may show a fingerprint (wall-clock data on a
    regular grid would). Passing does not prove the zone; the correction's evidence does. Failing
    rejects it."""

    model_config = ConfigDict(frozen=True)

    published_timezone: str
    corrected_timezone: str
    correction_evidence: str
    published_zone_shifts: tuple[ShiftEvidence, ...]
    published_zone_hours: tuple[HourEvidence, ...]
    accepted: bool
    reason: str


class SiteAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    timezone: str
    published_timezone: str | None = None  # set when the time zone was corrected
    zone_check: ZoneCheck | None = None
    buildings: int
    electricity_evidence: tuple[ShiftEvidence, ...]
    spring_gaps: tuple[GapEvidence, ...]
    electricity: ClockVerdict
    weather_evidence: tuple[ShiftEvidence, ...]
    weather_rows_at_nonexistent_hours: bool
    weather_duplicate_timestamps: int
    weather_phase_shift_hours: float | None
    weather: ClockVerdict


class AuditReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_commit: str = COMMIT
    period: tuple[str, str] = PERIOD
    margins: tuple[float, ...] = DEFAULT_MARGINS
    sites: tuple[SiteAudit, ...]


# ---------------------------------------------------------------------------
# Verdict rules
# ---------------------------------------------------------------------------


def electricity_verdict(
    shifts: Sequence[ShiftEvidence], gaps: Sequence[GapEvidence]
) -> ClockVerdict:
    """The margin-stable schedule-shift verdict, overruled to UNDETERMINED when it says STANDARD
    but every spring non-existent hour is systematically missing: a wall-clock signature."""
    verdict = classify(shifts, Signal.HUMAN)
    if verdict.clock is Clock.STANDARD and gaps and all(g.systematic for g in gaps):
        return ClockVerdict(
            clock=Clock.UNDETERMINED,
            reason=(
                f"conflicting evidence: profile shifts indicate standard time ({verdict.reason}), "
                "but every spring non-existent hour is systematically missing, as in wall-clock "
                "data on a regular grid"
            ),
        )
    return verdict


def weather_verdict(
    shifts: Sequence[ShiftEvidence], rows_at_nonexistent_hours: bool, duplicates: int
) -> ClockVerdict:
    """Fixed-offset (standard) weather needs structural evidence (real rows at every spring
    non-existent hour, no duplicate timestamps) and no wall-clock majority among transitions."""
    rule = EXPECTED_LAG[Signal.SOLAR][Clock.WALL_CLOCK]
    middle = DEFAULT_MARGINS[len(DEFAULT_MARGINS) // 2]
    usable = [e for e in shifts if e.lag is not None and e.margin >= middle]
    wall_votes = sum(e.lag == rule[e.kind] for e in usable)
    structural = rows_at_nonexistent_hours and duplicates == 0
    if structural and (not usable or wall_votes / len(usable) < 0.5):
        return ClockVerdict(
            clock=Clock.STANDARD,
            reason=(
                "a real row exists at every spring non-existent hour and no timestamp repeats "
                f"(fixed offset); {wall_votes} of {len(usable)} usable transitions show the "
                "wall-clock pattern"
            ),
        )
    verdict = classify(shifts, Signal.SOLAR)
    if verdict.clock is Clock.WALL_CLOCK and not structural:
        return verdict
    return ClockVerdict(
        clock=Clock.UNDETERMINED,
        reason=f"structural and transition evidence disagree ({verdict.reason})",
    )


def zone_check(
    correction: Correction,
    shifts: Sequence[ShiftEvidence],
    hours: Sequence[HourEvidence],
) -> ZoneCheck:
    """Accept a correction to a zone without daylight saving only if, under the published zone,
    no usable transition shows occupants shifting and no clock-change hour shows a fingerprint."""
    rule = EXPECTED_LAG[Signal.HUMAN][Clock.STANDARD]
    middle = DEFAULT_MARGINS[len(DEFAULT_MARGINS) // 2]
    usable = [e for e in shifts if e.lag is not None and e.margin >= middle]
    standard_votes = sum(e.lag == rule[e.kind] for e in usable)
    marked = [f"{h.hour} ({h.fingerprint})" for h in hours if h.fingerprint]
    lags = ", ".join(f"{e.kind} {e.lag:+d}" for e in usable if e.lag is not None)
    if len(usable) < MIN_USABLE:
        accepted, reason = (
            False,
            f"only {len(usable)} usable transition(s) under the published zone",
        )
    elif standard_votes:
        accepted = False
        reason = (
            f"{standard_votes} of {len(usable)} usable transitions show occupants shifting with "
            f"the published zone's clock changes ({lags})"
        )
    elif marked or not hours:
        accepted, reason = False, f"daylight-saving fingerprints: {'; '.join(marked) or 'no hours'}"
    else:
        accepted = True
        reason = (
            f"under {correction.published}, occupants do not shift at its clock changes ({lags}) "
            f"and none of its {len(hours)} clock-change hours shows a daylight-saving fingerprint"
        )
    return ZoneCheck(
        published_timezone=str(correction.published),
        corrected_timezone=str(correction.corrected),
        correction_evidence=correction.evidence,
        published_zone_shifts=tuple(shifts),
        published_zone_hours=tuple(hours),
        accepted=accepted,
        reason=reason,
    )


def fixed_offset_verdict(timezone: str, check: ZoneCheck | None) -> ClockVerdict:
    """The verdict for a zone without daylight-saving transitions in the period."""
    if check is not None and not check.accepted:
        return ClockVerdict(
            clock=Clock.UNDETERMINED, reason=f"time-zone correction rejected: {check.reason}"
        )
    reason = (
        f"{timezone} has no daylight-saving transitions in the period, so local time is a fixed "
        "offset and standard and wall-clock time coincide"
    )
    if check is not None:
        reason += f"; time-zone correction accepted: {check.reason}"
    return ClockVerdict(clock=Clock.STANDARD, reason=reason)


# ---------------------------------------------------------------------------
# Evidence from the BDG2 files
# ---------------------------------------------------------------------------


def load_raw(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Metadata, wide raw electricity (naive local index) and long weather, as published."""
    metadata = pd.read_csv(
        raw_dir / FILES_BY_KEY["metadata"].local_path,
        usecols=["building_id", "site_id", "timezone"],
    )
    electricity = pd.read_csv(raw_dir / FILES_BY_KEY["electricity_raw"].local_path)
    electricity.index = pd.DatetimeIndex(
        pd.to_datetime(electricity.pop("timestamp"), format=TIMESTAMP_FORMAT)
    )
    weather = pd.read_csv(
        raw_dir / FILES_BY_KEY["weather"].local_path,
        usecols=["timestamp", "site_id", "airTemperature"],
    )
    weather["timestamp"] = pd.to_datetime(weather["timestamp"], format=TIMESTAMP_FORMAT)
    return metadata, electricity, weather


def audit(raw_dir: Path, corrections: Sequence[Correction] = CORRECTIONS) -> AuditReport:
    metadata, electricity, weather = load_raw(raw_dir)
    return audit_frames(metadata, electricity, weather, corrections)


def audit_frames(
    metadata: pd.DataFrame,
    electricity: pd.DataFrame,
    weather: pd.DataFrame,
    corrections: Sequence[Correction] = (),
) -> AuditReport:
    """Audit the published metadata after applying `corrections` (none by default)."""
    corrected, applied = apply_corrections(metadata, corrections)
    zone_corrections = {c.site_id: c for c in applied if c.field == "timezone"}
    sites = []
    for site_id, group in corrected.groupby("site_id", sort=True):
        timezone = str(group["timezone"].iloc[0])
        columns = [b for b in group["building_id"] if b in electricity.columns]
        load = electricity[columns]
        correction = zone_corrections.get(str(site_id))
        check = None if correction is None else _zone_check(load, correction)
        changes = transitions(timezone, *PERIOD)
        load_shifts = tuple(profile_shift(load, t, weekdays_only=True) for t in changes)
        gaps = tuple(_gap(load, hour) for hour in nonexistent_hours(timezone, *PERIOD))

        temperature = (
            weather[weather["site_id"] == site_id]
            .set_index("timestamp")[["airTemperature"]]
            .sort_index()
        )
        weather_shifts = tuple(profile_shift(temperature, t, weekdays_only=False) for t in changes)
        present = bool(
            all(
                hour in temperature.index and temperature.loc[[hour]].notna().all().all()
                for hour in nonexistent_hours(timezone, *PERIOD)
            )
        )
        duplicates = int(temperature.index.duplicated().sum())
        if changes:
            electricity_clock = electricity_verdict(load_shifts, gaps)
            weather_clock = weather_verdict(weather_shifts, present, duplicates)
        else:
            electricity_clock = fixed_offset_verdict(timezone, check)
            weather_clock = (
                fixed_offset_verdict(timezone, None)
                if duplicates == 0
                else ClockVerdict(
                    clock=Clock.UNDETERMINED,
                    reason=f"{duplicates} repeated timestamp(s) in a zone without clock changes",
                )
            )
        sites.append(
            SiteAudit(
                site_id=str(site_id),
                timezone=timezone,
                published_timezone=None if correction is None else str(correction.published),
                zone_check=check,
                buildings=len(columns),
                electricity_evidence=load_shifts,
                spring_gaps=gaps,
                electricity=electricity_clock,
                weather_evidence=weather_shifts,
                weather_rows_at_nonexistent_hours=present,
                weather_duplicate_timestamps=duplicates,
                weather_phase_shift_hours=_seasonal_phase_shift(temperature),
                weather=weather_clock,
            )
        )
    return AuditReport(sites=tuple(sites))


def _zone_check(load: pd.DataFrame, correction: Correction) -> ZoneCheck:
    published, corrected = str(correction.published), str(correction.corrected)
    if transitions(corrected, *PERIOD):
        raise ValueError(
            f"{correction.site_id}: only corrections to zones without daylight saving time can be "
            f"checked, and {corrected} has clock changes in the period."
        )
    shifts = [profile_shift(load, t, weekdays_only=True) for t in transitions(published, *PERIOD)]
    hours = [_hour_evidence(load, h, "spring") for h in nonexistent_hours(published, *PERIOD)]
    hours += [_hour_evidence(load, h, "autumn") for h in repeated_hours(published, *PERIOD)]
    return zone_check(correction, shifts, hours)


def _hour_evidence(load: pd.DataFrame, hour: pd.Timestamp, kind: str) -> HourEvidence:
    live = load.loc[:, load.notna().mean() >= LIVE_SHARE]
    step = pd.Timedelta(hours=1)
    if live.shape[1] == 0 or any(t not in live.index for t in (hour - step, hour, hour + step)):
        return HourEvidence(hour=str(hour), kind=kind, live_meters=int(live.shape[1]))
    fill, ratio = _hour_shape(live, hour)
    controls = []
    for weeks in CONTROL_WEEKS:
        day = hour + pd.Timedelta(weeks=weeks)
        if all(t in live.index for t in (day - step, day, day + step)):
            controls.append(_hour_shape(live, day))
    control_fills = [f for f, _ in controls if f is not None]
    control_ratios = [r for _, r in controls if r is not None]
    return HourEvidence(
        hour=str(hour),
        kind=kind,
        live_meters=int(live.shape[1]),
        missing_share=round(float(live.loc[[hour]].isna().to_numpy().mean()), 4),
        neighbour_missing_share=round(
            max(float(live.loc[[t]].isna().to_numpy().mean()) for t in (hour - step, hour + step)),
            4,
        ),
        fill_share=fill,
        control_fill_share=round(float(np.mean(control_fills)), 4) if control_fills else None,
        ratio=ratio,
        control_ratio=round(float(np.median(control_ratios)), 4) if control_ratios else None,
    )


def _hour_shape(live: pd.DataFrame, hour: pd.Timestamp) -> tuple[float | None, float | None]:
    """The share of readings equal to a neighbour or to the neighbours' mean, and the median ratio
    of the reading to that mean, over meters with all three readings."""
    step = pd.Timedelta(hours=1)
    value, before, after = (
        live.loc[t].to_numpy(dtype=float) for t in (hour, hour - step, hour + step)
    )
    ok = ~(np.isnan(value) | np.isnan(before) | np.isnan(after))
    if not ok.any():
        return None, None
    value, before, after = value[ok], before[ok], after[ok]
    middle = (before + after) / 2
    tolerance = 1e-9 + 1e-6 * np.abs(value)
    filled = (
        (np.abs(value - before) <= tolerance)
        | (np.abs(value - after) <= tolerance)
        | (np.abs(value - middle) <= tolerance)
    )
    positive = middle > 0
    ratio = float(np.median(value[positive] / middle[positive])) if positive.any() else None
    return round(float(filled.mean()), 4), None if ratio is None else round(ratio, 4)


def _gap(load: pd.DataFrame, hour: pd.Timestamp) -> GapEvidence:
    live = load.loc[:, load.notna().mean() >= LIVE_SHARE]
    step = pd.Timedelta(hours=1)
    neighbours = [hour - step, hour + step]
    if live.shape[1] == 0 or hour not in live.index or not all(n in live.index for n in neighbours):
        return GapEvidence(hour=str(hour), missing_share=None, neighbour_missing_share=None)
    return GapEvidence(
        hour=str(hour),
        missing_share=round(float(live.loc[[hour]].isna().to_numpy().mean()), 4),
        neighbour_missing_share=round(float(live.loc[neighbours].isna().to_numpy().mean()), 4),
    )


def _seasonal_phase_shift(temperature: pd.DataFrame) -> float | None:
    """Summer-minus-winter phase of the 24 h temperature cycle, in hours (informational).

    About 0 for a fixed offset; wall-clock storage would add about +1 h."""
    index = pd.DatetimeIndex(temperature.index)

    def phase(months: list[int]) -> float | None:
        selected = temperature[index.month.isin(months)]["airTemperature"].dropna()
        if selected.empty:
            return None
        hourly = selected.groupby(pd.DatetimeIndex(selected.index).hour).mean()
        if len(hourly) < 24:
            return None
        angle = np.arange(24) * 2 * np.pi / 24
        values = hourly.reindex(range(24)).to_numpy(dtype=float)
        return float(
            np.degrees(np.arctan2((values * np.sin(angle)).sum(), (values * np.cos(angle)).sum()))
            / 15.0
        )

    winter, summer = phase([12, 1, 2]), phase([6, 7, 8])
    if winter is None or summer is None:
        return None
    return round((summer - winter + 12) % 24 - 12, 2)


def mismatches(report: AuditReport) -> list[str]:
    """Differences between the audit and the pinned verdicts."""
    found = []
    for site in report.sites:
        for name, verdict, pinned in (
            ("electricity", site.electricity, ELECTRICITY_CLOCKS.get(site.site_id)),
            ("weather", site.weather, WEATHER_CLOCKS.get(site.site_id)),
        ):
            if verdict.clock is not pinned:
                found.append(
                    f"{site.site_id} {name}: audit says {verdict.clock.value}, pinned "
                    f"{pinned.value if pinned else 'nothing'} ({verdict.reason})"
                )
    return found


def to_markdown(report: AuditReport) -> str:
    lines = [
        "# BDG2 timestamp-convention audit",
        "",
        f"Data commit `{report.dataset_commit}` · period {report.period[0]} to "
        f"{report.period[1]} · margins {', '.join(f'{m:g}' for m in report.margins)}",
        "",
        "| Site | Time zone | Buildings | Electricity | Weather | Weather phase shift (h) |",
        "|---|---|---|---|---|---|",
    ]
    for s in report.sites:
        shift = (
            "-" if s.weather_phase_shift_hours is None else f"{s.weather_phase_shift_hours:+.2f}"
        )
        zone = (
            s.timezone
            if s.published_timezone is None
            else (f"{s.timezone} (published: {s.published_timezone})")
        )
        lines.append(
            f"| {s.site_id} | {zone} | {s.buildings} | {s.electricity.clock.value} | "
            f"{s.weather.clock.value} | {shift} |"
        )
    lines += ["", "## Reasons", ""]
    for s in report.sites:
        lines.append(
            f"- **{s.site_id}** electricity: {s.electricity.reason}. Weather: {s.weather.reason}."
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.bdg2_audit",
        description="Audit which clock BDG2 timestamps follow, per site.",
    )
    parser.add_argument("--raw", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output-dir", type=Path, default=Path("../data/processed/bdg2"))
    args = parser.parse_args(argv)
    try:
        report = audit(args.raw)
    except FileNotFoundError as exc:
        print(
            f"error: {exc}. Download BDG2 first: uv run python -m wattwise.data.bdg2 fetch",
            file=sys.stderr,
        )
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "time_convention.json").write_bytes(
        (json.dumps(report.model_dump(mode="json"), indent=2) + "\n").encode("utf-8")
    )
    (args.output_dir / "time_convention.md").write_bytes(to_markdown(report).encode("utf-8"))
    print(to_markdown(report))
    problems = mismatches(report)
    for problem in problems:
        print(f"MISMATCH: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
