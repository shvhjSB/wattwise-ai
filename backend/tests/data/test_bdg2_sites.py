import re
from pathlib import Path

import pandas as pd
import pytest

from wattwise.data.bdg2_audit import ELECTRICITY_CLOCKS
from wattwise.data.bdg2_sites import CORRECTIONS, SITE_REGIONS, Correction, apply_corrections
from wattwise.data.time_convention import transitions

REPO_ROOT = Path(__file__).resolve().parents[3]
ZONE = Correction(
    site_id="Fox",
    field="timezone",
    published="US/Mountain",
    corrected="America/Phoenix",
    evidence="e",
)
LONGITUDE = Correction(
    site_id="Wolf", field="lng", published=6.2603, corrected=-6.2603, evidence="e"
)


def metadata() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "building_id": ["Fox_a", "Fox_b", "Wolf_a", "Bear_a"],
            "site_id": ["Fox", "Fox", "Wolf", "Bear"],
            "timezone": ["US/Mountain", "US/Mountain", "Europe/Dublin", "US/Pacific"],
            "lng": [-111.9281, -111.9281, 6.2603, -122.2607],
        }
    )


def test_corrections_apply_to_every_building_of_their_site_only() -> None:
    published = metadata()

    corrected, applied = apply_corrections(published, (ZONE, LONGITUDE))

    assert applied == (ZONE, LONGITUDE)
    assert list(corrected["timezone"]) == [
        "America/Phoenix",
        "America/Phoenix",
        "Europe/Dublin",
        "US/Pacific",
    ]
    assert list(corrected["lng"]) == [-111.9281, -111.9281, -6.2603, -122.2607]
    pd.testing.assert_frame_equal(published, metadata())  # the input is not modified


def test_a_correction_refuses_data_with_a_different_published_value() -> None:
    changed = metadata()
    changed.loc[1, "timezone"] = "US/Arizona"

    with pytest.raises(ValueError, match="expected the published value 'US/Mountain'"):
        apply_corrections(changed, (ZONE,))


def test_corrections_for_absent_sites_or_fields_are_skipped() -> None:
    without_lng = metadata().drop(columns="lng")
    only_bear = metadata().iloc[[3]]

    assert apply_corrections(without_lng, (LONGITUDE,))[1] == ()
    assert apply_corrections(only_bear, (ZONE, LONGITUDE))[1] == ()


def test_the_pinned_time_zone_correction_targets_a_zone_without_clock_changes() -> None:
    zones = [c for c in CORRECTIONS if c.field == "timezone"]

    assert zones, "Fox's correction is pinned"
    for correction in zones:
        assert transitions(str(correction.corrected), "2016-01-01", "2018-01-01") == []
        assert transitions(str(correction.published), "2016-01-01", "2018-01-01") != []


def test_every_audited_site_has_a_region_entry() -> None:
    assert set(SITE_REGIONS) == set(ELECTRICITY_CLOCKS)
    assert {s for s, r in SITE_REGIONS.items() if r is None} == {"Bobcat", "Eagle", "Gator", "Swan"}


def test_the_site_geography_table_matches_the_pinned_regions() -> None:
    doc = (REPO_ROOT / "docs" / "DATASETS.md").read_text(encoding="utf-8")
    # Four-column rows whose first cell is a site: the geography table, not the clock table.
    rows = {
        m.group(1): m.group(0)
        for m in re.finditer(r"^\| (\w+) \|[^|]+\|[^|]+\|[^|]*\|$", doc, re.MULTILINE)
        if m.group(1) in SITE_REGIONS
    }

    for site, region in SITE_REGIONS.items():
        row = rows.get(site, "")
        if region is None:
            assert "no coordinates" in row, site
        else:
            code = region.country + (f"-{region.subdivision}" if region.subdivision else "")
            assert f"({code})" in row, site
    for correction in CORRECTIONS:
        if correction.field == "timezone":
            assert f"corrected to {correction.corrected}" in rows[correction.site_id]
