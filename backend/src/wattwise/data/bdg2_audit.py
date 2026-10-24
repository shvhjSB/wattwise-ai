"""Audit which clock BDG2 timestamps follow, per site (docs/DATASETS.md, D016).

BDG2 publishes naive "local" timestamps on a regular hourly grid. T007 showed that this cannot
be daylight-saving wall-clock time throughout, and this audit shows that the convention differs
between sites. For each site it collects evidence for electricity (human signal) and weather
(solar signal) and returns a verdict; UNDETERMINED sites must be excluded rather than guessed.

The verdicts are pinned in `ELECTRICITY_CLOCKS` and `WEATHER_CLOCKS`, so preprocessing is
deterministic and reviewable. Re-running the audit checks the pins against the data:

    uv run python -m wattwise.data.bdg2_audit          # needs the BDG2 download (T007)
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
from wattwise.data.time_convention import (
    DEFAULT_MARGINS,
    EXPECTED_LAG,
    Clock,
    ClockVerdict,
    ShiftEvidence,
    Signal,
    classify,
    nonexistent_hours,
    profile_shift,
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

#: Pinned verdicts from `audit()` on the BDG2 files at commit 753598e0 (run on 2026-10-23).
ELECTRICITY_CLOCKS: Final[Mapping[str, Clock]] = {
    "Bear": Clock.WALL_CLOCK,
    "Bobcat": Clock.WALL_CLOCK,
    "Bull": Clock.WALL_CLOCK,
    "Cockatoo": Clock.WALL_CLOCK,
    "Crow": Clock.WALL_CLOCK,
    "Eagle": Clock.STANDARD,
    "Fox": Clock.UNDETERMINED,
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


class SiteAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    timezone: str
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


def audit(raw_dir: Path) -> AuditReport:
    metadata, electricity, weather = load_raw(raw_dir)
    return audit_frames(metadata, electricity, weather)


def audit_frames(
    metadata: pd.DataFrame, electricity: pd.DataFrame, weather: pd.DataFrame
) -> AuditReport:
    sites = []
    for site_id, group in metadata.groupby("site_id", sort=True):
        timezone = str(group["timezone"].iloc[0])
        columns = [b for b in group["building_id"] if b in electricity.columns]
        load = electricity[columns]
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
        sites.append(
            SiteAudit(
                site_id=str(site_id),
                timezone=timezone,
                buildings=len(columns),
                electricity_evidence=load_shifts,
                spring_gaps=gaps,
                electricity=electricity_verdict(load_shifts, gaps),
                weather_evidence=weather_shifts,
                weather_rows_at_nonexistent_hours=present,
                weather_duplicate_timestamps=duplicates,
                weather_phase_shift_hours=_seasonal_phase_shift(temperature),
                weather=weather_verdict(weather_shifts, present, duplicates),
            )
        )
    return AuditReport(sites=tuple(sites))


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
        lines.append(
            f"| {s.site_id} | {s.timezone} | {s.buildings} | {s.electricity.clock.value} | "
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
