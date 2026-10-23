"""Data-quality assessment for canonical readings (docs/DATA_QUALITY.md).

The contract (T005) rejects structurally broken data. This module *describes* data that passed
the contract: coverage, gaps, missing values, negative readings, zero runs, flatlines, extreme
values and implausible energy intensity. Findings never reject data, and they are not anomalies
in building behaviour; they flag where the data itself may be unreliable. Any cause mentioned is
a hypothesis to check, not a conclusion.

    uv run python -m wattwise.data.quality --readings ../data/sample/synthetic/readings.csv \
        --buildings ../data/sample/synthetic/buildings.csv --output-dir ../docs/reports \
        --name synthetic-data-quality
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from wattwise.data.contracts import BUILDINGS, READINGS, MeterType, Unit
from wattwise.data.csv_io import read_csv
from wattwise.data.validation import ValidationIssue, check_table

QUALITY_VERSION: Final = "1"

BoolArray = npt.NDArray[np.bool_]
FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

#: Meter types whose readings cannot be negative. Solar meters may record export as negative.
NON_NEGATIVE_TYPES: Final = frozenset(m.value for m in MeterType if m is not MeterType.SOLAR)
_MICROSECONDS_PER_YEAR: Final = 365.25 * 24 * 3600 * 1_000_000


class QualityCheck(StrEnum):
    GAPS = "gaps"
    IRREGULAR_INTERVAL = "irregular_interval"
    MISSING_VALUES = "missing_values"
    LOW_COVERAGE = "low_coverage"
    NEGATIVE_VALUES = "negative_values"
    ZERO_RUNS = "zero_runs"
    FLATLINES = "flatlines"
    EXTREME_VALUES = "extreme_values"
    IMPLAUSIBLE_INTENSITY = "implausible_intensity"


class FindingSeverity(StrEnum):
    INFO = "info"  # a fact worth knowing, e.g. a short gap
    WARNING = "warning"  # data likely unreliable here; check before use


class QualityThresholds(BaseModel):
    """Configurable thresholds. Defaults and their rationale are in docs/DATA_QUALITY.md."""

    model_config = ConfigDict(frozen=True)

    min_coverage_pct: float = Field(95.0, ge=0, le=100)
    flatline_min_intervals: int = Field(6, ge=2)
    flatline_tolerance: float = Field(0.0, ge=0)
    zero_run_min_intervals: int = Field(24, ge=2)
    extreme_ratio_to_p99: float = Field(5.0, gt=1)
    min_intensity_kwh_m2_year: float = Field(2.0, ge=0)
    max_intensity_kwh_m2_year: float = Field(2000.0, gt=0)


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    check: QualityCheck
    severity: FindingSeverity
    message: str
    count: int
    start: str | None = None  # first affected timestamp of the example window (UTC)
    end: str | None = None  # last affected timestamp of the example window (UTC)


class MeterQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    meter_id: str
    building_id: str
    meter_type: str
    unit: str
    interval_minutes: int | None
    first: str
    last: str
    expected_intervals: int
    present_rows: int
    absent_intervals: int
    missing_values: int
    available_values: int
    coverage_pct: float
    negative_values: int
    zero_values: int
    findings: tuple[Finding, ...]


class QualitySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    meters: int
    rows: int
    first: str
    last: str
    expected_intervals: int
    available_values: int
    coverage_pct: float
    meters_with_warnings: int
    meters_by_check: dict[str, int]


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    quality_version: str = QUALITY_VERSION
    contract_version: str
    valid: bool
    contract_issues: tuple[ValidationIssue, ...]
    thresholds: QualityThresholds
    summary: QualitySummary | None
    meters: tuple[MeterQuality, ...]


def assess(
    readings: pd.DataFrame,
    buildings: pd.DataFrame | None = None,
    thresholds: QualityThresholds | None = None,
) -> QualityReport:
    """Assess readings. Structural problems (contract errors) stop the assessment and are
    reported; otherwise every meter is assessed. `buildings` enables the intensity check."""
    limits = thresholds or QualityThresholds()
    contract, canonical = check_table(readings, READINGS)
    if not contract.ok:
        return QualityReport(
            contract_version=contract.contract_version,
            valid=False,
            contract_issues=contract.issues,
            thresholds=limits,
            summary=None,
            meters=(),
        )

    areas: dict[str, float] = {}
    if buildings is not None:
        building_report, canonical_buildings = check_table(buildings, BUILDINGS)
        if building_report.ok:
            known = canonical_buildings.dropna(subset=["floor_area_m2"])
            areas = dict(
                zip(
                    known["building_id"].astype(str).tolist(),
                    known["floor_area_m2"].astype(float).tolist(),
                    strict=True,
                )
            )

    meters = tuple(
        _assess_meter(group, areas, limits) for _, group in canonical.groupby("meter_id", sort=True)
    )
    return QualityReport(
        contract_version=contract.contract_version,
        valid=True,
        contract_issues=contract.issues,
        thresholds=limits,
        summary=_summarise(meters, len(canonical)),
        meters=meters,
    )


# ---------------------------------------------------------------------------
# Per-meter assessment
# ---------------------------------------------------------------------------


def _assess_meter(
    group: pd.DataFrame, areas: dict[str, float], limits: QualityThresholds
) -> MeterQuality:
    first_row = group.iloc[0]
    meter_type, unit = str(first_row["meter_type"]), str(first_row["unit"])
    building_id = str(first_row["building_id"])
    times = group["timestamp"].to_numpy(dtype="datetime64[us]").astype(np.int64)
    values = group["value"].to_numpy(dtype=float)
    missing = np.isnan(values)
    findings: list[Finding] = []

    diffs = np.diff(times)
    interval = _infer_interval(diffs)
    if interval is None:
        contiguous = np.zeros(len(times), dtype=bool)
        expected, absent = len(times), 0
    else:
        contiguous = np.concatenate(([False], diffs == interval))
        steps = diffs // interval
        regular = diffs % interval == 0
        absent = int((steps[regular] - 1).sum())
        expected = int((times[-1] - times[0]) // interval) + 1
        findings += _gap_findings(times, steps, regular, interval)

    available = int((~missing).sum())
    coverage = round(100.0 * available / expected, 2) if expected else 0.0
    findings += _missing_findings(times, missing, contiguous)
    if coverage < limits.min_coverage_pct:
        findings.append(
            Finding(
                check=QualityCheck.LOW_COVERAGE,
                severity=FindingSeverity.WARNING,
                message=(
                    f"Coverage is {coverage:.2f}% of the expected {expected} intervals, below the "
                    f"{limits.min_coverage_pct:g}% threshold. Models and benchmarks for this meter "
                    "rest on incomplete data."
                ),
                count=expected - available,
            )
        )

    present = ~missing
    negative = present & (values < 0)
    if meter_type in NON_NEGATIVE_TYPES and negative.any():
        findings.append(_negative_finding(times, values, negative))
    zero = present & (values == 0)
    findings += _zero_run_findings(times, zero, contiguous, limits)
    findings += _flatline_findings(times, values, present & ~zero, contiguous, limits)
    findings += _extreme_findings(times, values, present, limits)
    if meter_type == MeterType.ELECTRICITY.value and unit == Unit.KWH.value:
        findings += _intensity_findings(values, present, interval, areas.get(building_id), limits)

    return MeterQuality(
        meter_id=str(first_row["meter_id"]),
        building_id=building_id,
        meter_type=meter_type,
        unit=unit,
        interval_minutes=None if interval is None else int(interval // 60_000_000),
        first=_iso(times[0]),
        last=_iso(times[-1]),
        expected_intervals=expected,
        present_rows=len(times),
        absent_intervals=absent,
        missing_values=int(missing.sum()),
        available_values=available,
        coverage_pct=coverage,
        negative_values=int(negative.sum()),
        zero_values=int(zero.sum()),
        findings=tuple(findings),
    )


def _infer_interval(diffs: IntArray) -> int | None:
    """The most common positive step (ties: the shortest), in microseconds."""
    positive = diffs[diffs > 0]
    if positive.size == 0:
        return None
    steps, counts = np.unique(positive, return_counts=True)
    return int(steps[np.argmax(counts)])


def _gap_findings(
    times: IntArray, steps: IntArray, regular: BoolArray, interval: int
) -> list[Finding]:
    findings: list[Finding] = []
    irregular = ~regular
    if irregular.any():
        position = int(np.flatnonzero(irregular)[0])
        findings.append(
            Finding(
                check=QualityCheck.IRREGULAR_INTERVAL,
                severity=FindingSeverity.WARNING,
                message=(
                    f"{int(irregular.sum())} step(s) between readings are not a multiple of the "
                    f"meter's {_duration(interval)} interval, first after {_iso(times[position])}. "
                    "Timestamps may be shifted or mixed from different sources."
                ),
                count=int(irregular.sum()),
                start=_iso(times[position]),
                end=_iso(times[position + 1]),
            )
        )
    gaps = regular & (steps > 1)
    if gaps.any():
        sizes = steps[gaps] - 1
        longest = int(np.flatnonzero(gaps)[int(np.argmax(sizes))])
        missing_intervals = int(sizes.sum())
        findings.append(
            Finding(
                check=QualityCheck.GAPS,
                severity=FindingSeverity.INFO,
                message=(
                    f"{missing_intervals} interval(s) have no row, in {int(gaps.sum())} gap(s); "
                    f"the longest spans {int(sizes.max())} interval(s) "
                    f"({_iso(times[longest] + interval)} to {_iso(times[longest + 1] - interval)})."
                ),
                count=missing_intervals,
                start=_iso(times[longest] + interval),
                end=_iso(times[longest + 1] - interval),
            )
        )
    return findings


def _missing_findings(times: IntArray, missing: BoolArray, contiguous: BoolArray) -> list[Finding]:
    if not missing.any():
        return []
    runs = _segments(missing, contiguous)
    start, length = max(runs, key=lambda run: (run[1], -run[0]))
    return [
        Finding(
            check=QualityCheck.MISSING_VALUES,
            severity=FindingSeverity.INFO,
            message=(
                f"{int(missing.sum())} reading(s) are missing (empty value) in {len(runs)} run(s); "
                f"the longest is {length} interval(s) ({_iso(times[start])} to "
                f"{_iso(times[start + length - 1])})."
            ),
            count=int(missing.sum()),
            start=_iso(times[start]),
            end=_iso(times[start + length - 1]),
        )
    ]


def _negative_finding(times: IntArray, values: FloatArray, negative: BoolArray) -> Finding:
    first = int(np.flatnonzero(negative)[0])
    return Finding(
        check=QualityCheck.NEGATIVE_VALUES,
        severity=FindingSeverity.WARNING,
        message=(
            f"{int(negative.sum())} reading(s) are negative, which this meter type cannot measure "
            f"(first {values[first]:g} at {_iso(times[first])}). A sign, reset or export "
            "convention problem is possible; check before use."
        ),
        count=int(negative.sum()),
        start=_iso(times[first]),
        end=_iso(times[first]),
    )


def _zero_run_findings(
    times: IntArray, zero: BoolArray, contiguous: BoolArray, limits: QualityThresholds
) -> list[Finding]:
    runs = [r for r in _segments(zero, contiguous) if r[1] >= limits.zero_run_min_intervals]
    if not runs:
        return []
    start, length = max(runs, key=lambda run: (run[1], -run[0]))
    return [
        Finding(
            check=QualityCheck.ZERO_RUNS,
            severity=FindingSeverity.WARNING,
            message=(
                f"{len(runs)} run(s) of at least {limits.zero_run_min_intervals} consecutive zero "
                f"readings; the longest is {length} interval(s) ({_iso(times[start])} to "
                f"{_iso(times[start + length - 1])}). An outage, a disconnected meter or a logger "
                "fault is possible; a real shutdown is also possible."
            ),
            count=sum(run[1] for run in runs),
            start=_iso(times[start]),
            end=_iso(times[start + length - 1]),
        )
    ]


def _flatline_findings(
    times: IntArray,
    values: FloatArray,
    eligible: BoolArray,
    contiguous: BoolArray,
    limits: QualityThresholds,
) -> list[Finding]:
    same = np.zeros(len(values), dtype=bool)
    if len(values) > 1:
        same[1:] = (
            eligible[1:]
            & eligible[:-1]
            & (np.abs(values[1:] - values[:-1]) <= limits.flatline_tolerance)
        )
    runs = [
        (start - 1, length + 1)
        for start, length in _true_runs(same & contiguous)
        if length + 1 >= limits.flatline_min_intervals
    ]
    if not runs:
        return []
    start, length = max(runs, key=lambda run: (run[1], -run[0]))
    return [
        Finding(
            check=QualityCheck.FLATLINES,
            severity=FindingSeverity.WARNING,
            message=(
                f"{len(runs)} run(s) of at least {limits.flatline_min_intervals} consecutive "
                f"identical non-zero readings; the longest is {length} interval(s) at "
                f"{values[start]:g} ({_iso(times[start])} to {_iso(times[start + length - 1])}). "
                "A stuck meter or logger fault is likely; treat these readings as unreliable "
                "until checked."
            ),
            count=sum(run[1] for run in runs),
            start=_iso(times[start]),
            end=_iso(times[start + length - 1]),
        )
    ]


def _extreme_findings(
    times: IntArray, values: FloatArray, present: BoolArray, limits: QualityThresholds
) -> list[Finding]:
    """Readings far above the meter's own 99th percentile: magnitude errors such as a Wh/kWh
    slip or a counter reset. A ratio is used rather than a robust z-score, because building load
    is bimodal (occupied vs unoccupied) and a z-score flags plausible behaviour peaks too."""
    observed = values[present]
    if observed.size < 100:
        return []  # too few readings for a stable 99th percentile
    p99 = float(np.percentile(observed, 99))
    if p99 <= 0:
        return []
    ratio = np.where(present, values / p99, 0.0)
    extreme = ratio > limits.extreme_ratio_to_p99
    if not extreme.any():
        return []
    worst = int(np.argmax(ratio))
    return [
        Finding(
            check=QualityCheck.EXTREME_VALUES,
            severity=FindingSeverity.WARNING,
            message=(
                f"{int(extreme.sum())} reading(s) exceed {limits.extreme_ratio_to_p99:g}x the "
                f"meter's 99th-percentile reading ({p99:g}); the largest is {values[worst]:g} at "
                f"{_iso(times[worst])} ({ratio[worst]:.1f}x). A magnitude error such as a unit "
                "slip or a counter reset is likely; check before use."
            ),
            count=int(extreme.sum()),
            start=_iso(times[worst]),
            end=_iso(times[worst]),
        )
    ]


def _intensity_findings(
    values: FloatArray,
    present: BoolArray,
    interval: int | None,
    area: float | None,
    limits: QualityThresholds,
) -> list[Finding]:
    if interval is None or area is None or not present.any():
        return []
    per_year = float(np.mean(values[present])) * (_MICROSECONDS_PER_YEAR / interval) / area
    low, high = limits.min_intensity_kwh_m2_year, limits.max_intensity_kwh_m2_year
    if low <= per_year <= high:
        return []
    return [
        Finding(
            check=QualityCheck.IMPLAUSIBLE_INTENSITY,
            severity=FindingSeverity.WARNING,
            message=(
                f"Electricity intensity of about {per_year:,.1f} kWh/m2/year (from the mean "
                f"reading and a floor area of {area:g} m2) is outside the plausible range "
                f"{low:g}-{high:g}. A unit or scaling error (e.g. Wh recorded as kWh), a wrong "
                "floor area, or a meter serving more than this building is possible."
            ),
            count=int(present.sum()),
        )
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _true_runs(flags: BoolArray) -> list[tuple[int, int]]:
    """(start, length) of each maximal run of True."""
    if not flags.any():
        return []
    padded = np.concatenate(([False], flags, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    starts, ends = edges[0::2], edges[1::2]
    return [(int(s), int(e - s)) for s, e in zip(starts, ends, strict=True)]


def _segments(flags: BoolArray, contiguous: BoolArray) -> list[tuple[int, int]]:
    """(start, length) of runs of flagged rows that follow each other without a gap."""
    joined = np.zeros(len(flags), dtype=bool)
    if len(flags) > 1:
        joined[1:] = flags[1:] & flags[:-1] & contiguous[1:]
    starts = flags & ~joined
    runs = []
    for start in np.flatnonzero(starts):
        end = start + 1
        while end < len(flags) and joined[end]:
            end += 1
        runs.append((int(start), int(end - start)))
    return runs


def _iso(microseconds: int | np.int64) -> str:
    return pd.Timestamp(int(microseconds), unit="us", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _duration(microseconds: int) -> str:
    minutes = microseconds // 60_000_000
    return f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes} min"


def _summarise(meters: tuple[MeterQuality, ...], rows: int) -> QualitySummary:
    expected = sum(m.expected_intervals for m in meters)
    available = sum(m.available_values for m in meters)
    by_check = {
        check.value: sum(any(f.check is check for f in m.findings) for m in meters)
        for check in QualityCheck
    }
    return QualitySummary(
        meters=len(meters),
        rows=rows,
        first=min(m.first for m in meters),
        last=max(m.last for m in meters),
        expected_intervals=expected,
        available_values=available,
        coverage_pct=round(100.0 * available / expected, 2) if expected else 0.0,
        meters_with_warnings=sum(
            any(f.severity is FindingSeverity.WARNING for f in m.findings) for m in meters
        ),
        meters_by_check={k: v for k, v in by_check.items() if v},
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def to_json(report: QualityReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2) + "\n"


def to_markdown(report: QualityReport, title: str) -> str:
    lines = [f"# Data-quality report: {title}", ""]
    lines += [
        "> Findings describe the **data**, not building behaviour: they flag readings that may be",
        "> unreliable. They are not anomalies or confirmed faults, and any cause named is a",
        "> hypothesis to check. Generated by `wattwise.data.quality` "
        f"(version {report.quality_version}); see docs/DATA_QUALITY.md.",
        "",
    ]
    if not report.valid or report.summary is None:
        lines += [
            f"**Structural validation (contract {report.contract_version}): failed.** The data "
            "was not assessed. Fix these contract errors first:",
            "",
        ]
        lines += [f"- `{i.code.value}`: {i.message}" for i in report.contract_issues]
        return "\n".join(lines) + "\n"

    s = report.summary
    warnings = sum(1 for i in report.contract_issues if i.severity.value == "warning")
    lines += [
        f"- **Structural validation (contract {report.contract_version}):** passed"
        + (f" with {warnings} warning(s)" if warnings else ""),
        f"- **Meters:** {s.meters} · **rows:** {s.rows:,} · **period:** {s.first} to {s.last}",
        f"- **Coverage:** {s.coverage_pct:.2f}% ({s.available_values:,} of "
        f"{s.expected_intervals:,} expected values)",
        f"- **Meters with warnings:** {s.meters_with_warnings} of {s.meters}",
        "",
        "## Findings by check",
        "",
        "| Check | Meters affected |",
        "|---|---|",
    ]
    lines += [f"| `{check}` | {count} |" for check, count in s.meters_by_check.items()] or [
        "| (none) | 0 |"
    ]
    lines += [
        "",
        "## Meters",
        "",
        "| Meter | Interval | Coverage | Absent | Missing | Negative | Zero | Findings |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m in report.meters:
        interval = "-" if m.interval_minutes is None else f"{m.interval_minutes} min"
        checks = ", ".join(f"`{f.check.value}`" for f in m.findings) or "-"
        lines.append(
            f"| `{m.meter_id}` | {interval} | {m.coverage_pct:.2f}% | {m.absent_intervals} | "
            f"{m.missing_values} | {m.negative_values} | {m.zero_values} | {checks} |"
        )
    lines += ["", "## Details", ""]
    detailed = [m for m in report.meters if m.findings]
    if not detailed:
        lines.append("No findings.")
    for m in detailed:
        lines.append(f"### `{m.meter_id}`")
        lines.append("")
        lines += [f"- **{f.severity.value}** `{f.check.value}`: {f.message}" for f in m.findings]
        lines.append("")
    lines += ["## Thresholds", "", "| Threshold | Value |", "|---|---|"]
    lines += [f"| `{k}` | {v:g} |" for k, v in report.thresholds.model_dump().items()]
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: QualityReport, directory: Path, name: str, title: str) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"{name}.json", directory / f"{name}.md"]
    paths[0].write_bytes(to_json(report).encode("utf-8"))
    paths[1].write_bytes(to_markdown(report, title).encode("utf-8"))
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.quality",
        description="Assess the quality of a readings CSV and write JSON and Markdown reports.",
    )
    parser.add_argument("--readings", type=Path, required=True, help="readings CSV (contract)")
    parser.add_argument("--buildings", type=Path, help="buildings CSV, enables intensity check")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--name", default="data-quality", help="report file name, no extension")
    parser.add_argument("--title", help="report title (default: the readings file name)")
    args = parser.parse_args(argv)

    readings = read_csv(args.readings, READINGS)
    if readings.frame is None:
        report = QualityReport(
            contract_version=readings.report.contract_version,
            valid=False,
            contract_issues=readings.report.issues,
            thresholds=QualityThresholds(),
            summary=None,
            meters=(),
        )
    else:
        buildings = None
        if args.buildings is not None:
            buildings = read_csv(args.buildings, BUILDINGS).frame
        report = assess(readings.frame, buildings)
    title = args.title or args.readings.name
    for path in write_report(report, args.output_dir, args.name, title):
        print(path)
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
