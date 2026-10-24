import re
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from tests.data.conftest import BDG2Builder, SiteSpec
from wattwise.data.bdg2 import COMMIT
from wattwise.data.bdg2_audit import (
    ELECTRICITY_CLOCKS,
    WEATHER_CLOCKS,
    GapEvidence,
    HourEvidence,
    SiteAudit,
    audit,
    audit_frames,
    electricity_verdict,
    load_raw,
    main,
    mismatches,
    weather_verdict,
)
from wattwise.data.bdg2_sites import Correction
from wattwise.data.time_convention import Clock, ShiftEvidence

REPO_ROOT = Path(__file__).resolve().parents[3]
BDG2_SITES = {
    "Bear", "Bobcat", "Bull", "Cockatoo", "Crow", "Eagle", "Fox", "Gator", "Hog", "Lamb",
    "Moose", "Mouse", "Panther", "Peacock", "Rat", "Robin", "Shrew", "Swan", "Wolf",
}  # fmt: skip

Builder = Callable[[Sequence[SiteSpec]], Path]


def shifts(*lags: tuple[str, int]) -> tuple[ShiftEvidence, ...]:
    """Evidence where `lag` wins clearly over the other lags."""
    return tuple(
        ShiftEvidence(
            day="2016-03-13",
            kind=kind,
            series=10,
            scores={k: (0.99 if k == lag else 0.9) for k in (-1, 0, 1)},
        )
        for kind, lag in lags
    )


STANDARD_LOAD = shifts(("spring", -1), ("autumn", 1), ("spring", -1), ("autumn", 1))
SYSTEMATIC_GAP = GapEvidence(
    hour="2016-03-13 02:00:00", missing_share=1.0, neighbour_missing_share=0.0
)
NO_GAP = GapEvidence(hour="2016-03-13 02:00:00", missing_share=0.0, neighbour_missing_share=0.0)


# ---------------------------------------------------------------------------
# Verdict rules
# ---------------------------------------------------------------------------


def test_standard_load_with_normal_spring_hours_is_standard() -> None:
    assert electricity_verdict(STANDARD_LOAD, [NO_GAP, NO_GAP]).clock is Clock.STANDARD


def test_standard_load_with_a_wall_clock_gap_signature_is_a_conflict() -> None:
    result = electricity_verdict(STANDARD_LOAD, [SYSTEMATIC_GAP, SYSTEMATIC_GAP])

    assert result.clock is Clock.UNDETERMINED
    assert "conflicting evidence" in result.reason


def test_a_gap_signature_does_not_overrule_a_wall_clock_verdict() -> None:
    wall = shifts(("spring", 0), ("autumn", 0), ("spring", 0))

    assert electricity_verdict(wall, [SYSTEMATIC_GAP]).clock is Clock.WALL_CLOCK


def test_weather_with_structural_fixed_offset_evidence_is_standard() -> None:
    noisy = shifts(("spring", -1), ("autumn", 0), ("spring", 0), ("autumn", 0))

    assert (
        weather_verdict(noisy, rows_at_nonexistent_hours=True, duplicates=0).clock is Clock.STANDARD
    )


def test_weather_without_structural_evidence_is_not_assumed_standard() -> None:
    zero_lags = shifts(("spring", 0), ("autumn", 0), ("spring", 0), ("autumn", 0))

    assert (
        weather_verdict(zero_lags, rows_at_nonexistent_hours=False, duplicates=0).clock
        is Clock.UNDETERMINED
    )
    assert (
        weather_verdict(zero_lags, rows_at_nonexistent_hours=True, duplicates=3).clock
        is Clock.UNDETERMINED
    )


def test_weather_with_a_wall_clock_majority_is_not_standard() -> None:
    wall = shifts(("spring", 1), ("autumn", -1), ("spring", 1), ("autumn", 0))

    assert (
        weather_verdict(wall, rows_at_nonexistent_hours=True, duplicates=0).clock
        is not Clock.STANDARD
    )


# ---------------------------------------------------------------------------
# The audit on a mini dataset in BDG2's file format
# ---------------------------------------------------------------------------


def test_audit_recovers_known_conventions_from_bdg2_format_files(make_bdg2_raw: Builder) -> None:
    raw = make_bdg2_raw(
        [
            ("Std", "US/Eastern", Clock.STANDARD, 3, False),
            ("Wall", "US/Pacific", Clock.WALL_CLOCK, 3, False),
            ("Flat", "Europe/London", Clock.WALL_CLOCK, 2, True),
        ]
    )

    report = audit(raw)
    by_site = {s.site_id: s for s in report.sites}

    assert by_site["Std"].electricity.clock is Clock.STANDARD
    assert by_site["Wall"].electricity.clock is Clock.WALL_CLOCK
    assert by_site["Flat"].electricity.clock is Clock.UNDETERMINED, "a flat load proves nothing"
    assert all(s.weather.clock is Clock.STANDARD for s in report.sites)
    assert all(g.systematic for g in by_site["Wall"].spring_gaps)
    assert not any(g.systematic for g in by_site["Std"].spring_gaps)
    assert by_site["Std"].buildings == 3


def test_mismatches_report_disagreement_with_the_pins(make_bdg2_raw: Builder) -> None:
    report = audit(make_bdg2_raw([("Eagle", "US/Eastern", Clock.WALL_CLOCK, 3, False)]))

    (problem,) = mismatches(report)
    assert problem.startswith("Eagle electricity: audit says wall_clock, pinned standard")


def test_cli_explains_a_missing_download(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--raw", str(tmp_path / "absent"), "--output-dir", str(tmp_path)]) == 1

    assert "bdg2 fetch" in capsys.readouterr().err


def test_cli_writes_the_evidence_and_fails_on_mismatch(
    make_bdg2_raw: Builder, tmp_path: Path
) -> None:
    raw = make_bdg2_raw([("Eagle", "US/Eastern", Clock.STANDARD, 3, False)])

    assert main(["--raw", str(raw), "--output-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "time_convention.json").exists()
    assert "| Eagle |" in (tmp_path / "out" / "time_convention.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Time-zone corrections (T009c): a zone without daylight saving, mislabelled as one with it
# ---------------------------------------------------------------------------

TO_ARIZONA = Correction(
    site_id="Mt",
    field="timezone",
    published="US/Mountain",
    corrected="America/Phoenix",
    evidence="test",
)


def audited(raw: Path, *corrections: Correction) -> dict[str, SiteAudit]:
    metadata, electricity, weather = load_raw(raw)
    return {s.site_id: s for s in audit_frames(metadata, electricity, weather, corrections).sites}


def test_a_mislabelled_zone_without_daylight_saving_is_corrected(
    make_bdg2_raw: BDG2Builder,
) -> None:
    # Behaves and is stored in Arizona time, but the metadata says US/Mountain (as for Fox).
    raw = make_bdg2_raw(
        [("Mt", "America/Phoenix", Clock.STANDARD, 3, False)],
        published_timezones={"Mt": "US/Mountain"},
    )

    site = audited(raw, TO_ARIZONA)["Mt"]

    assert site.timezone == "America/Phoenix"
    assert site.published_timezone == "US/Mountain"
    check = site.zone_check
    assert check is not None
    assert check.accepted, check.reason
    assert len(check.published_zone_hours) == 4  # 2 spring and 2 autumn clock-change hours
    assert all(h.fingerprint is None for h in check.published_zone_hours)
    assert site.electricity.clock is Clock.STANDARD
    assert site.weather.clock is Clock.STANDARD


def test_without_the_correction_the_same_data_would_be_misread(make_bdg2_raw: BDG2Builder) -> None:
    raw = make_bdg2_raw(
        [("Mt", "America/Phoenix", Clock.STANDARD, 3, False)],
        published_timezones={"Mt": "US/Mountain"},
    )

    site = audited(raw)["Mt"]

    # Occupants do not shift, so the US/Mountain audit reads it as wall-clock time, which would
    # move every summer reading by an hour.
    assert site.electricity.clock is Clock.WALL_CLOCK


@pytest.mark.parametrize(
    ("clock", "reason"),
    [
        (Clock.WALL_CLOCK, "the hour is empty"),  # wall-clock data on a grid leaves fingerprints
        (Clock.STANDARD, "occupants shifting"),  # standard-time data shows the 1 h shift
    ],
)
def test_a_correction_is_rejected_when_the_readings_show_daylight_saving(
    make_bdg2_raw: BDG2Builder, clock: Clock, reason: str
) -> None:
    raw = make_bdg2_raw([("Mt", "US/Mountain", clock, 3, False)])

    site = audited(raw, TO_ARIZONA)["Mt"]

    assert site.zone_check is not None
    assert not site.zone_check.accepted
    assert reason in site.zone_check.reason
    assert site.electricity.clock is Clock.UNDETERMINED
    assert "correction rejected" in site.electricity.reason


def test_only_corrections_to_zones_without_daylight_saving_can_be_checked(
    make_bdg2_raw: BDG2Builder,
) -> None:
    raw = make_bdg2_raw([("Mt", "US/Mountain", Clock.WALL_CLOCK, 2, False)])
    to_pacific = TO_ARIZONA.model_copy(update={"corrected": "US/Pacific"})

    with pytest.raises(ValueError, match="only corrections to zones without daylight saving"):
        audited(raw, to_pacific)


@pytest.mark.parametrize(
    ("fields", "fingerprint"),
    [
        ({}, None),
        ({"missing_share": 0.95}, "the hour is empty"),
        ({"neighbour_missing_share": 1.0}, "an adjacent hour is empty"),
        ({"fill_share": 0.6, "control_fill_share": 0.3}, "readings are copied or interpolated"),
        ({"fill_share": 0.45, "control_fill_share": 0.3}, None),
        ({"ratio": 1.98, "control_ratio": 1.0}, "the reading is out of line"),
        ({"ratio": 1.1, "control_ratio": 1.0}, None),
        ({"missing_share": None}, "no usable readings"),
    ],
)
def test_clock_change_hour_fingerprints(
    fields: dict[str, float | None], fingerprint: str | None
) -> None:
    normal: dict[str, float | None] = {
        "missing_share": 0.0,
        "neighbour_missing_share": 0.0,
        "fill_share": 0.05,
        "control_fill_share": 0.05,
        "ratio": 1.0,
        "control_ratio": 1.0,
    }
    evidence = HourEvidence(hour="h", kind="spring", live_meters=5, **{**normal, **fields})

    if fingerprint is None:
        assert evidence.fingerprint is None
    else:
        assert evidence.fingerprint is not None
        assert evidence.fingerprint.startswith(fingerprint)


# ---------------------------------------------------------------------------
# Pinned verdicts and their documentation
# ---------------------------------------------------------------------------


def test_pins_cover_every_bdg2_site() -> None:
    assert set(ELECTRICITY_CLOCKS) == BDG2_SITES
    assert set(WEATHER_CLOCKS) == BDG2_SITES
    assert set(WEATHER_CLOCKS.values()) == {Clock.STANDARD}


def test_pinned_verdicts_are_documented() -> None:
    doc = (REPO_ROOT / "docs" / "DATASETS.md").read_text(encoding="utf-8")

    for site, clock in ELECTRICITY_CLOCKS.items():
        row = rf"\| {site} \| [^|]+ \| \d+ \| {clock.value} \| {WEATHER_CLOCKS[site].value} \|"
        assert re.search(row, doc), site
    assert COMMIT in doc
