from pathlib import Path

import pandas as pd

from wattwise.data.bdg2_sites import EGRID_SUBREGION
from wattwise.data.reference import (
    carbon_factor,
    geography_for_site,
    load_carbon_factors,
    load_prices,
    prices,
    site_carbon_factor,
    site_prices,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_DIR = REPO_ROOT / "data" / "reference"

CARBON = pd.DataFrame(
    [
        {
            "geography": "US-CAMX",
            "geography_name": "WECC California",
            "year": 2016,
            "kg_co2e_per_kwh": 0.24,
            "scope": "generation",
            "source_name": "s",
            "source_url": "u",
            "retrieved": "2026-10-26",
            "licence": "l",
            "file_sha256": "h",
        }
    ]
)
PRICE = pd.DataFrame(
    [
        {
            "geography": "GB",
            "geography_name": "United Kingdom",
            "year": 2016,
            "period": "annual",
            "sector": "industrial",
            "band": "medium",
            "tax_basis": "excl_ccl",
            "value": 9.57,
            "currency": "GBP",
            "unit": "pence_per_kwh",
            "source_name": "s",
            "source_url": "u",
            "retrieved": "2026-10-26",
            "licence": "l",
            "file_sha256": "h",
        },
        {
            "geography": "GB",
            "geography_name": "United Kingdom",
            "year": 2016,
            "period": "annual",
            "sector": "industrial",
            "band": "medium",
            "tax_basis": "incl_ccl",
            "value": 10.01,
            "currency": "GBP",
            "unit": "pence_per_kwh",
            "source_name": "s",
            "source_url": "u",
            "retrieved": "2026-10-26",
            "licence": "l",
            "file_sha256": "h",
        },
    ]
)


# -- geography resolution -------------------------------------------------------------------


def test_us_sites_resolve_to_their_egrid_subregion() -> None:
    assert geography_for_site("Bear") == "US-CAMX"
    assert geography_for_site("Fox") == "US-AZNM"


def test_uk_and_ireland_sites_resolve_to_their_country_code() -> None:
    assert geography_for_site("Mouse") == "GB"
    assert geography_for_site("Wolf") == "IE"


def test_sites_without_a_committed_geography_resolve_to_none() -> None:
    assert geography_for_site("Bobcat") is None  # no coordinates
    assert geography_for_site("Crow") is None  # Canada: not covered yet
    assert geography_for_site("Rat") is None  # a US site with no coordinates in this subset


def test_an_unknown_site_resolves_to_none() -> None:
    assert geography_for_site("NotASite") is None


# -- carbon factor ---------------------------------------------------------------------------


def test_carbon_factor_returns_the_matching_row() -> None:
    factor = carbon_factor("US-CAMX", 2016, CARBON)

    assert factor is not None
    assert factor.kg_co2e_per_kwh == 0.24
    assert factor.requested_year == 2016
    assert factor.vintage_year == 2016


def test_carbon_factor_falls_back_to_the_nearest_earlier_vintage_and_says_so() -> None:
    factor = carbon_factor("US-CAMX", 2017, CARBON)

    assert factor is not None
    assert factor.requested_year == 2017
    assert factor.vintage_year == 2016  # no 2017 edition: the fallback is explicit, not silent


def test_carbon_factor_is_not_configured_before_any_vintage() -> None:
    assert carbon_factor("US-CAMX", 2015, CARBON) is None


def test_carbon_factor_is_not_configured_for_an_unknown_geography() -> None:
    assert carbon_factor("CA-ON", 2016, CARBON) is None


def test_carbon_factor_is_not_configured_for_no_geography() -> None:
    assert carbon_factor(None, 2016, CARBON) is None


def test_site_carbon_factor_resolves_the_site_first() -> None:
    assert site_carbon_factor("Bear", 2016, CARBON) is not None
    assert site_carbon_factor("Bobcat", 2016, CARBON) is None


# -- prices -----------------------------------------------------------------------------------


def test_prices_returns_every_row_for_the_year_not_just_one() -> None:
    rows = prices("GB", 2016, PRICE)

    assert {r.tax_basis for r in rows} == {"excl_ccl", "incl_ccl"}
    assert {r.value for r in rows} == {9.57, 10.01}


def test_prices_is_empty_for_an_unconfigured_geography_or_year() -> None:
    assert prices("CA-ON", 2016, PRICE) == []
    assert prices("GB", 2015, PRICE) == []
    assert prices(None, 2016, PRICE) == []


def test_site_prices_resolves_the_site_first() -> None:
    assert len(site_prices("Mouse", 2016, PRICE)) == 2
    assert site_prices("Bobcat", 2016, PRICE) == []


# -- the committed tables themselves (T021a acceptance: checked by a recorded checksum) ------


def test_the_committed_carbon_table_loads_and_matches_its_recorded_checksums() -> None:
    frame = load_carbon_factors(REFERENCE_DIR)

    assert set(frame["geography"]) == {
        "US-CAMX", "US-ERCT", "US-NYUP", "US-AZNM", "US-MROW", "US-FRCC", "US-RFCE", "GB", "IE",
    }  # fmt: skip
    assert set(frame["year"]) == {2016, 2017}
    assert (frame["kg_co2e_per_kwh"] > 0).all()
    for recorded in frame["file_sha256"].unique():
        assert len(recorded) == 64


def test_the_committed_price_table_loads_and_matches_its_recorded_checksums() -> None:
    frame = load_prices(REFERENCE_DIR)

    assert set(frame["geography"]) == {
        "US-AZ", "US-CA", "US-DC", "US-FL", "US-MN", "US-NJ", "US-NY", "US-TX", "GB", "IE",
    }  # fmt: skip
    assert (frame["value"] > 0).all()
    for recorded in frame["file_sha256"].unique():
        assert len(recorded) == 64


def test_ontario_has_no_committed_row_for_2016_or_2017() -> None:
    """The documented gap (module docstring): no interpolated or guessed Ontario factor."""
    carbon = load_carbon_factors(REFERENCE_DIR)
    price = load_prices(REFERENCE_DIR)

    assert not carbon["geography"].str.startswith("CA").any()
    assert not price["geography"].str.startswith("CA").any()


def test_every_committed_source_url_is_https() -> None:
    for frame in (load_carbon_factors(REFERENCE_DIR), load_prices(REFERENCE_DIR)):
        assert frame["source_url"].str.startswith("https://").all()


def test_every_recorded_checksum_is_lowercase_hex() -> None:
    for frame in (load_carbon_factors(REFERENCE_DIR), load_prices(REFERENCE_DIR)):
        for recorded in frame["file_sha256"].unique():
            assert len(recorded) == 64
            assert all(c in "0123456789abcdef" for c in recorded)


def test_the_committed_price_table_has_no_duplicate_rows() -> None:
    frame = load_prices(REFERENCE_DIR)
    key = ["geography", "year", "period", "sector", "band", "tax_basis"]

    assert not frame.duplicated(subset=key).any()


def test_every_committed_us_site_has_a_matching_carbon_and_price_geography() -> None:
    """The eGRID carbon table and the EIA price table must cover the same US sites, or an estimate
    could silently show cost with no carbon factor (or the reverse)."""
    carbon_us = set(load_carbon_factors(REFERENCE_DIR)["geography"]) & {
        f"US-{code}" for code in {"CAMX", "ERCT", "NYUP", "AZNM", "MROW", "FRCC", "RFCE"}
    }
    sites_with_a_us_carbon_factor = {
        site for site, code in EGRID_SUBREGION.items() if code and f"US-{code}" in carbon_us
    }

    assert sites_with_a_us_carbon_factor == {
        "Bear", "Bull", "Cockatoo", "Fox", "Hog", "Panther", "Peacock",
    }  # fmt: skip
