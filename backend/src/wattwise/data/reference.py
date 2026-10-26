"""Sourced carbon-factor and price reference tables (docs/DATASETS.md, D037, T021a).

Real, cited electricity carbon factors and commercial/industrial prices, by country or US eGRID
subregion, so the cost and carbon estimates in T021 never invent a number. Every value in
`../data/reference/carbon_factors.csv` and `../data/reference/electricity_prices.csv` carries its
own source name, URL, retrieval date, licence and the SHA-256 of the file it was read from.

**Geography codes:** an eGRID subregion code prefixed `US-` for the US (from a point-in-polygon
lookup against the published eGRID subregion boundaries; see
`wattwise.data.bdg2_sites.EGRID_SUBREGION`), or an ISO 3166-1 alpha-2 code for the UK and Ireland
(`GB`, `IE`).

**Ontario is not configured**, on both sides:
- *Carbon:* docs/DATASETS.md (T007b) cites a 2016/2017 Ontario intensity from an older NIR
  edition ("1990-2017", Table A13-7), but that edition was not found at a stable public URL in
  this task; the only edition reachable here ("1990-2024", Annex 7) skips 2016/2017 in its
  Ontario table. Rather than commit a number without hashing its own source file, or interpolate
  across the gap (not a sourced factor either), Ontario has no committed row yet
  (docs/DECISIONS.md, D037).
- *Price:* T021a's scope has no Ontario price source.

`carbon_factor` and `price` return `None` for an unconfigured geography, an unlocated site, or a
year before any available vintage — never an invented or interpolated number. A source with no
edition for the exact requested year (eGRID publishes roughly every two years, so there is no
eGRID2017) is matched to its nearest *earlier* vintage, and the result says so explicitly
(`vintage_year` differs from the requested year) rather than silently reusing it as if it were a
fresh measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from wattwise.data.bdg2_sites import EGRID_SUBREGION, SITE_REGIONS

#: Repo-relative, matching every other module's `../data/...` default (run from `backend/`).
DEFAULT_REFERENCE_DIR: Final = Path("../data/reference")


@dataclass(frozen=True)
class CarbonFactor:
    """A carbon intensity, with its source and the vintage actually used."""

    geography: str
    geography_name: str
    requested_year: int
    vintage_year: int
    kg_co2e_per_kwh: float
    scope: str
    source_name: str
    source_url: str
    retrieved: str
    licence: str
    file_sha256: str


@dataclass(frozen=True)
class ElectricityPrice:
    """A published electricity price, with its source, band and tax basis."""

    geography: str
    geography_name: str
    year: int
    period: str
    sector: str
    band: str | None
    tax_basis: str
    value: float
    currency: str
    unit: str
    source_name: str
    source_url: str
    retrieved: str
    licence: str
    file_sha256: str


def load_carbon_factors(directory: Path = DEFAULT_REFERENCE_DIR) -> pd.DataFrame:
    """The committed carbon-factor table, one row per geography and vintage year."""
    return pd.read_csv(directory / "carbon_factors.csv")


def load_prices(directory: Path = DEFAULT_REFERENCE_DIR) -> pd.DataFrame:
    """The committed price table, one row per geography, year, period, band and tax basis."""
    frame = pd.read_csv(directory / "electricity_prices.csv", keep_default_na=True)
    return frame.astype({"band": "object"}).where(frame.notna(), None)


def geography_for_site(site_id: str) -> str | None:
    """The reference-table geography code for a BDG2 site, or `None` if it has no committed
    geography (no location, or a country/region this table does not yet cover)."""
    region = SITE_REGIONS.get(site_id)
    if region is None:
        return None
    if region.country == "US":
        subregion = EGRID_SUBREGION.get(site_id)
        return f"US-{subregion}" if subregion else None
    if region.country in ("GB", "IE"):
        return region.country
    return None  # e.g. CA: no committed geography yet (see the module docstring)


def carbon_factor(
    geography: str | None, year: int, table: pd.DataFrame | None = None
) -> CarbonFactor | None:
    """The carbon factor for `geography` at or before `year`: the latest vintage that is not
    later than the requested year. `None` if `geography` is `None`, unconfigured, or every
    vintage on record is later than `year`."""
    if geography is None:
        return None
    frame = table if table is not None else load_carbon_factors()
    rows = frame[(frame["geography"] == geography) & (frame["year"] <= year)]
    if rows.empty:
        return None
    row = rows.sort_values("year").iloc[-1]
    return CarbonFactor(
        geography=row["geography"],
        geography_name=row["geography_name"],
        requested_year=year,
        vintage_year=int(row["year"]),
        kg_co2e_per_kwh=float(row["kg_co2e_per_kwh"]),
        scope=row["scope"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        retrieved=row["retrieved"],
        licence=row["licence"],
        file_sha256=row["file_sha256"],
    )


def site_carbon_factor(
    site_id: str, year: int, table: pd.DataFrame | None = None
) -> CarbonFactor | None:
    """`carbon_factor` for a BDG2 site, via `geography_for_site`."""
    return carbon_factor(geography_for_site(site_id), year, table)


def prices(
    geography: str | None, year: int, table: pd.DataFrame | None = None
) -> list[ElectricityPrice]:
    """Every published price row for `geography` in exactly `year` (sources here publish
    annually, so no vintage fallback): different bands, periods and tax bases are all returned,
    since which one applies is a tariff-configuration choice, not something to guess here. Empty
    if `geography` is `None`, unconfigured, or has no row for `year`."""
    if geography is None:
        return []
    frame = table if table is not None else load_prices()
    rows = frame[(frame["geography"] == geography) & (frame["year"] == year)]
    return [
        ElectricityPrice(
            geography=row["geography"],
            geography_name=row["geography_name"],
            year=int(row["year"]),
            period=row["period"],
            sector=row["sector"],
            band=row["band"],
            tax_basis=row["tax_basis"],
            value=float(row["value"]),
            currency=row["currency"],
            unit=row["unit"],
            source_name=row["source_name"],
            source_url=row["source_url"],
            retrieved=row["retrieved"],
            licence=row["licence"],
            file_sha256=row["file_sha256"],
        )
        for _, row in rows.iterrows()
    ]


def site_prices(
    site_id: str, year: int, table: pd.DataFrame | None = None
) -> list[ElectricityPrice]:
    """`prices` for a BDG2 site, via `geography_for_site`."""
    return prices(geography_for_site(site_id), year, table)
