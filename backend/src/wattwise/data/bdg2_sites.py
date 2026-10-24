"""Pinned corrections and regions for BDG2 sites (docs/DATASETS.md, D020).

The published BDG2 metadata has errors that change what the data mean, found in T007b. Each
correction states the published value, the corrected value and the evidence. `apply_corrections`
refuses to run if the published value differs, so a correction never silently applies to other
data. The timestamp audit re-checks the time-zone correction against the readings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict


class Correction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: str
    field: Literal["timezone", "lng"]
    published: str | float
    corrected: str | float
    evidence: str


class Region(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    country: str  # ISO 3166-1 alpha-2
    subdivision: str | None = None  # ISO 3166-2 subdivision code, without the country prefix


CORRECTIONS: Final[tuple[Correction, ...]] = (
    Correction(
        site_id="Fox",
        field="timezone",
        published="US/Mountain",
        corrected="America/Phoenix",
        evidence=(
            "The site coordinates (33.4244, -111.9281) are in Arizona, which does not observe "
            "daylight saving time: America/Phoenix has no transitions in 2016-2017. The readings "
            "agree (zone check in the timestamp audit): occupants do not shift at the US/Mountain "
            "clock changes, and no clock-change hour shows a daylight-saving fingerprint."
        ),
    ),
    Correction(
        site_id="Wolf",
        field="lng",
        published=6.2603,
        corrected=-6.2603,
        evidence=(
            "With longitude 6.2603 the coordinates (53.3498) fall in the Netherlands, but the "
            "site's time zone is Europe/Dublin; 53.3498, -6.2603 is Dublin. The sign was lost."
        ),
    ),
)

#: Country and region of each site, from reverse-geocoding the (corrected) metadata coordinates
#: with OpenStreetMap Nominatim on 2026-10-24. None where the metadata has no coordinates: the
#: country of those sites is unknown, because a "US/..." zone name does not prove it (Crow and
#: Moose are in Canada).
SITE_REGIONS: Final[Mapping[str, Region | None]] = {
    "Bear": Region(country="US", subdivision="CA"),
    "Bobcat": None,
    "Bull": Region(country="US", subdivision="TX"),
    "Cockatoo": Region(country="US", subdivision="NY"),
    "Crow": Region(country="CA", subdivision="ON"),
    "Eagle": None,
    "Fox": Region(country="US", subdivision="AZ"),
    "Gator": None,
    "Hog": Region(country="US", subdivision="MN"),
    "Lamb": Region(country="GB", subdivision="WLS"),
    "Moose": Region(country="CA", subdivision="ON"),
    "Mouse": Region(country="GB", subdivision="ENG"),
    "Panther": Region(country="US", subdivision="FL"),
    "Peacock": Region(country="US", subdivision="NJ"),
    "Rat": Region(country="US", subdivision="DC"),
    "Robin": Region(country="GB", subdivision="ENG"),
    "Shrew": Region(country="GB", subdivision="ENG"),
    "Swan": None,
    "Wolf": Region(country="IE"),
}


def apply_corrections(
    metadata: pd.DataFrame, corrections: Sequence[Correction] = CORRECTIONS
) -> tuple[pd.DataFrame, tuple[Correction, ...]]:
    """A corrected copy of the metadata and the corrections that applied.

    A correction applies to every row of its site, if the site and the field are present. It
    raises ValueError if any of those rows holds a value other than the published one."""
    corrected = metadata.copy()
    applied = []
    for correction in corrections:
        if correction.field not in corrected.columns:
            continue
        rows = corrected["site_id"] == correction.site_id
        if not rows.any():
            continue
        values = corrected.loc[rows, correction.field]
        if not (values == correction.published).all():
            found = sorted({str(v) for v in values})
            raise ValueError(
                f"{correction.site_id}.{correction.field}: expected the published value "
                f"{correction.published!r} for every building, found {found}. The source data "
                "differs from the data this correction was made for."
            )
        if correction.field == "lng":
            corrected[correction.field] = corrected[correction.field].astype(float)
        corrected.loc[rows, correction.field] = correction.corrected
        applied.append(correction)
    return corrected, tuple(applied)
