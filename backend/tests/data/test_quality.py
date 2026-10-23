import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import pydantic
import pytest

from wattwise.data.quality import (
    Finding,
    QualityCheck,
    QualityReport,
    QualityThresholds,
    assess,
    main,
    to_json,
    to_markdown,
)
from wattwise.data.synthetic import AnomalyType, generate
from wattwise.data.validation import IssueCode

REPO_ROOT = Path(__file__).resolve().parents[3]
HOURS = 14 * 24


def normal_load(n: int = HOURS, seed: int = 0) -> np.ndarray:
    """A bimodal, noisy daily load with no data problems."""
    hours = np.arange(n) % 24
    occupied = (hours >= 8) & (hours < 18)
    noise = np.random.default_rng(seed).normal(0.0, 1.5, n)
    return np.where(occupied, 110.0, 45.0) + noise


def meter(
    values: Sequence[float] | np.ndarray,
    *,
    meter_type: str = "electricity",
    unit: str = "kWh",
    building: str = "b1",
    drop: Sequence[int] = (),
) -> pd.DataFrame:
    timestamps = pd.date_range("2016-01-04T00:00:00Z", periods=len(values), freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "meter_id": f"{building}:{meter_type}",
            "building_id": building,
            "meter_type": meter_type,
            "unit": unit,
            "value": np.asarray(values, dtype=float),
        }
    )
    return frame.drop(index=list(drop)).reset_index(drop=True)


def checks(report: QualityReport) -> set[QualityCheck]:
    return {finding.check for m in report.meters for finding in m.findings}


def finding(report: QualityReport, check: QualityCheck) -> Finding:
    matching = [f for m in report.meters for f in m.findings if f.check is check]
    assert len(matching) == 1, [f.check for m in report.meters for f in m.findings]
    return matching[0]


def area(building: str = "b1", floor_area: float = 5000.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "building_id": [building],
            "site_id": ["s1"],
            "timezone": ["Europe/London"],
            "floor_area_m2": [floor_area],
        }
    )


# ---------------------------------------------------------------------------
# A clean meter produces no findings
# ---------------------------------------------------------------------------


def test_clean_data_has_no_findings() -> None:
    report = assess(meter(normal_load()), area())

    assert report.valid
    assert checks(report) == set()
    (quality,) = report.meters
    assert quality.coverage_pct == 100.0
    assert quality.interval_minutes == 60
    assert quality.expected_intervals == HOURS


# ---------------------------------------------------------------------------
# Structure (the contract) and duplicate timestamps
# ---------------------------------------------------------------------------


def test_duplicate_timestamps_are_reported_as_contract_errors() -> None:
    frame = meter(normal_load())
    duplicated = pd.concat([frame, frame.iloc[[10]]], ignore_index=True)

    report = assess(duplicated)

    assert not report.valid
    assert report.summary is None
    assert report.meters == ()
    assert IssueCode.DUPLICATE_KEY in {issue.code for issue in report.contract_issues}
    assert "failed" in to_markdown(report, "dup")


def test_structurally_invalid_data_is_not_assessed() -> None:
    frame = meter(normal_load())
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)

    report = assess(frame)

    assert not report.valid
    assert {issue.code for issue in report.contract_issues} == {IssueCode.NAIVE_TIMESTAMP}


# ---------------------------------------------------------------------------
# Coverage: gaps, irregular steps, missing values
# ---------------------------------------------------------------------------


def test_gaps_are_counted_with_the_longest_window() -> None:
    report = assess(meter(normal_load(), drop=range(100, 110)))

    gap = finding(report, QualityCheck.GAPS)
    assert gap.count == 10
    assert gap.start == "2016-01-08T04:00:00Z"
    assert gap.end == "2016-01-08T13:00:00Z"
    assert report.meters[0].absent_intervals == 10


def test_coverage_below_the_threshold_is_a_warning() -> None:
    report = assess(meter(normal_load(200), drop=range(50, 61)))  # 189 of 200

    assert finding(report, QualityCheck.LOW_COVERAGE).severity.value == "warning"


def test_coverage_exactly_at_the_threshold_is_not_a_warning() -> None:
    report = assess(meter(normal_load(200), drop=range(50, 60)))  # 190 of 200 = 95%

    assert report.meters[0].coverage_pct == 95.0
    assert QualityCheck.LOW_COVERAGE not in checks(report)


def test_steps_off_the_interval_grid_are_irregular() -> None:
    frame = meter(normal_load())
    shift = pd.to_timedelta(np.where(frame.index == 50, 30, 0), unit="min")
    frame["timestamp"] = frame["timestamp"] + shift

    report = assess(frame)

    assert finding(report, QualityCheck.IRREGULAR_INTERVAL).count == 2


def test_missing_values_report_the_longest_run() -> None:
    values = normal_load()
    values[[10, 11, 12, 200]] = np.nan

    report = assess(meter(values))

    missing = finding(report, QualityCheck.MISSING_VALUES)
    assert missing.count == 4
    assert (missing.start, missing.end) == ("2016-01-04T10:00:00Z", "2016-01-04T12:00:00Z")
    assert "in 2 run(s)" in missing.message


# ---------------------------------------------------------------------------
# Values: negatives, zero runs, flatlines, extremes
# ---------------------------------------------------------------------------


def test_negative_consumption_is_flagged() -> None:
    values = normal_load()
    values[30] = -5.0

    assert finding(assess(meter(values)), QualityCheck.NEGATIVE_VALUES).count == 1


def test_negative_solar_readings_are_not_flagged() -> None:
    values = normal_load()
    values[30] = -5.0

    report = assess(meter(values, meter_type="solar"))

    assert QualityCheck.NEGATIVE_VALUES not in checks(report)


@pytest.mark.parametrize(("length", "flagged"), [(24, True), (23, False)])
def test_zero_runs_from_the_threshold_length(length: int, flagged: bool) -> None:
    values = normal_load()
    values[100 : 100 + length] = 0.0

    report = assess(meter(values))

    assert (QualityCheck.ZERO_RUNS in checks(report)) is flagged
    assert QualityCheck.FLATLINES not in checks(report), "zeros are not a flatline"


@pytest.mark.parametrize(("length", "flagged"), [(6, True), (5, False)])
def test_flatlines_from_the_threshold_length(length: int, flagged: bool) -> None:
    values = normal_load()
    values[100 : 100 + length] = 77.7

    report = assess(meter(values))

    assert (QualityCheck.FLATLINES in checks(report)) is flagged
    if flagged:
        flat = finding(report, QualityCheck.FLATLINES)
        assert (flat.start, flat.end) == ("2016-01-08T04:00:00Z", "2016-01-08T09:00:00Z")


def test_identical_values_on_both_sides_of_a_gap_are_not_one_flatline() -> None:
    values = normal_load()
    values[100:108] = 77.7

    report = assess(meter(values, drop=[103, 104]))  # 3 + gap + 3

    assert QualityCheck.FLATLINES not in checks(report)


def test_flatline_tolerance_is_configurable() -> None:
    values = normal_load()
    values[100:106] = [50.0, 50.001, 50.0, 50.001, 50.0, 50.001]

    exact = assess(meter(values))
    tolerant = assess(meter(values), thresholds=QualityThresholds(flatline_tolerance=0.01))

    assert QualityCheck.FLATLINES not in checks(exact)
    assert QualityCheck.FLATLINES in checks(tolerant)


def test_a_magnitude_error_is_extreme() -> None:
    values = normal_load()
    values[150] = values[150] * 1000  # e.g. Wh recorded as kWh

    extreme = finding(assess(meter(values)), QualityCheck.EXTREME_VALUES)

    assert extreme.count == 1
    assert extreme.start == "2016-01-10T06:00:00Z"


def test_a_plausible_behaviour_spike_is_not_a_data_quality_finding() -> None:
    values = normal_load()
    values[150:152] = values[150:152] * 2.5  # a real-looking spike, as in the synthetic data

    assert QualityCheck.EXTREME_VALUES not in checks(assess(meter(values)))


def test_short_series_skip_the_extreme_check() -> None:
    values = normal_load(50)
    values[10] = 1e6

    assert QualityCheck.EXTREME_VALUES not in checks(assess(meter(values)))


# ---------------------------------------------------------------------------
# Units: implausible intensity
# ---------------------------------------------------------------------------


def test_implausible_intensity_suggests_a_unit_or_area_problem() -> None:
    report = assess(meter(normal_load()), area(floor_area=10.0))

    intensity = finding(report, QualityCheck.IMPLAUSIBLE_INTENSITY)
    assert "kWh/m2/year" in intensity.message


def test_plausible_intensity_and_unknown_area_are_not_flagged() -> None:
    assert QualityCheck.IMPLAUSIBLE_INTENSITY not in checks(assess(meter(normal_load()), area()))
    assert QualityCheck.IMPLAUSIBLE_INTENSITY not in checks(assess(meter(normal_load())))


def test_intensity_is_only_checked_for_electricity() -> None:
    report = assess(meter(normal_load(), meter_type="water", unit="m3"), area(floor_area=1.0))

    assert QualityCheck.IMPLAUSIBLE_INTENSITY not in checks(report)


# ---------------------------------------------------------------------------
# Thresholds, summaries, determinism
# ---------------------------------------------------------------------------


def test_thresholds_are_validated() -> None:
    with pytest.raises(pydantic.ValidationError):
        QualityThresholds(min_coverage_pct=120)
    with pytest.raises(pydantic.ValidationError):
        QualityThresholds(flatline_min_intervals=1)


def test_summary_counts_meters_per_check() -> None:
    a = normal_load()
    a[100:110] = 77.7
    b = normal_load(seed=1)
    b[5] = np.nan
    frame = pd.concat([meter(a, building="b1"), meter(b, building="b2")], ignore_index=True)

    summary = assess(frame).summary

    assert summary is not None
    assert summary.meters == 2
    assert summary.meters_by_check == {"missing_values": 1, "flatlines": 1}
    assert summary.meters_with_warnings == 1


def test_reports_are_deterministic() -> None:
    frame = meter(normal_load())

    assert to_json(assess(frame)) == to_json(assess(frame))
    assert json.loads(to_json(assess(frame)))["valid"] is True


# ---------------------------------------------------------------------------
# The synthetic fixture (acceptance: a report is generated for it)
# ---------------------------------------------------------------------------


def test_synthetic_fixture_flags_exactly_the_injected_data_faults() -> None:
    dataset = generate()
    report = assess(dataset.readings, dataset.buildings)
    found = {(m.meter_id, f.check) for m in report.meters for f in m.findings}

    assert found == {
        ("syn-lab-c:electricity", QualityCheck.MISSING_VALUES),
        ("syn-office-a:electricity", QualityCheck.FLATLINES),
    }, "data faults are found; behaviour anomalies (spike, excess, overnight, drift) are not"

    for anomaly, check in (
        (AnomalyType.MISSING_DATA, QualityCheck.MISSING_VALUES),
        (AnomalyType.FLATLINE, QualityCheck.FLATLINES),
    ):
        event = dataset.labels[dataset.labels["anomaly_type"] == anomaly.value]
        result = next(f for m in report.meters for f in m.findings if f.check is check)
        start = pd.Timestamp(event["start"].iloc[0])
        last_hour = pd.Timestamp(event["end"].iloc[0]) - pd.Timedelta(hours=1)  # end is exclusive
        assert result.start == start.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert result.end == last_hour.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_committed_synthetic_report_is_up_to_date(tmp_path: Path) -> None:
    sample = REPO_ROOT / "data" / "sample" / "synthetic"
    exit_code = main(
        [
            "--readings",
            str(sample / "readings.csv"),
            "--buildings",
            str(sample / "buildings.csv"),
            "--output-dir",
            str(tmp_path),
            "--name",
            "synthetic-data-quality",
            "--title",
            "synthetic sample (data/sample/synthetic)",
        ]
    )

    assert exit_code == 0
    for suffix in (".json", ".md"):
        committed = REPO_ROOT / "docs" / "reports" / f"synthetic-data-quality{suffix}"
        assert (tmp_path / f"synthetic-data-quality{suffix}").read_bytes() == committed.read_bytes()


def test_cli_reports_invalid_input_and_fails(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("timestamp,meter_id\n2016-01-01 00:00,m1\n", encoding="utf-8")

    assert main(["--readings", str(bad), "--output-dir", str(tmp_path), "--name", "r"]) == 1
    assert "failed" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_quality_doc_lists_every_check_and_threshold() -> None:
    doc = (REPO_ROOT / "docs" / "DATA_QUALITY.md").read_text(encoding="utf-8")

    for check in QualityCheck:
        assert f"| `{check.value}` |" in doc, check.value
    for name in QualityThresholds.model_fields:
        assert f"`{name}`" in doc, name
