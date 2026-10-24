"""ERA5 radiation and cloud cover for BDG2 sites, with derived humidity (docs/DATASETS.md, D023).

BDG2's weather has no solar radiation and no humidity variable. This module adds, per site and
hour:
- **ERA5 reanalysis** radiation (global, direct and diffuse horizontal, direct normal) and cloud
  cover, from the Open-Meteo historical archive with the model pinned to ERA5. These are modelled
  values for a 0.25-degree grid cell, not observations at the site. Their columns end in `_era5`.
- **Relative humidity derived** from BDG2's observed temperature and dew point with the Magnus
  formula (Alduchov & Eskridge 1996). Its column ends in `_derived`.

Open-Meteo labels radiation with the end of the hour it averages. Readings are labelled with the
start of their hour (D012), so radiation is relabelled one hour earlier. Instantaneous values
(cloud cover) keep their time. Both conventions are checked on the data, over the whole period and
in every calendar quarter with enough data, and `prepare` writes nothing if a check fails:
- the median radiation-weighted centre of the solar days must lie within 30 min of solar noon
  (half of the one-hour error the check exists to catch)
- the temperature phase of ERA5 against BDG2's observed temperature must be stable across
  quarters (each within 0.5 h of the site's median) and within 0.75 h of zero

Nothing is gap-filled across sources, and sites without coordinates get no ERA5 data.

The free Open-Meteo API is for non-commercial use, and WattWise is non-commercial (owner decision,
D022). Data licence: CC BY 4.0, "Weather data by Open-Meteo.com", from Copernicus ERA5.

    uv run python -m wattwise.data.era5 fetch      # one request per located site, ../data/raw/era5
    uv run python -m wattwise.data.era5 prepare    # enrichment into ../data/processed/era5
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import sys
import time
import urllib.error
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

import numpy as np
import numpy.typing as npt
import pandas as pd

from wattwise.data.acquisition import AcquisitionError, Opener, open_url, sha256_of, verify
from wattwise.data.bdg2 import DEFAULT_DESTINATION as BDG2_DESTINATION
from wattwise.data.bdg2 import FILES_BY_KEY as BDG2_FILES
from wattwise.data.bdg2_audit import WEATHER_CLOCKS
from wattwise.data.bdg2_prepare import site_weather
from wattwise.data.bdg2_sites import CORRECTIONS, Correction, apply_corrections
from wattwise.data.solar import equation_of_time_min

FloatArray = npt.NDArray[np.float64]

ENDPOINT: Final = "https://archive-api.open-meteo.com/v1/archive"
MODEL: Final = "era5"
#: Requested days, inclusive. A day of margin on each side covers every BDG2 local hour in UTC.
START_DATE: Final = "2015-12-31"
END_DATE: Final = "2018-01-01"
PROCESSING_VERSION: Final = "1"
DEFAULT_DESTINATION: Final = Path("../data/raw/era5")
#: Kept with the responses, git-ignored: it holds BDG2 site coordinates (no redistribution, D014).
DEFAULT_MANIFEST: Final = DEFAULT_DESTINATION / "manifest.json"
DEFAULT_OUTPUT: Final = Path("../data/processed/era5")
#: Open-Meteo's licence asks for its credit and link and a note of changes. The ERA5 citation
#: and the Copernicus acknowledgement (with its disclaimer) are the CDS's own texts.
ATTRIBUTION: Final = (
    "Weather data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0 (Zippenfenig, P. "
    "(2023), Open-Meteo.com Weather API, https://doi.org/10.5281/zenodo.7970649). Contains "
    "modified Copernicus Climate Change Service information 2026 (Hersbach et al. (2023), ERA5 "
    "hourly data on single levels from 1940 to present, https://doi.org/10.24381/cds.adbb2d47). "
    "Neither the European Commission nor ECMWF is responsible for any use that may be made of "
    "the Copernicus information or data it contains. Changes: radiation relabelled to the start "
    "of its hour; values unchanged."
)
TERMS: Final = (
    "The free Open-Meteo API is for non-commercial use only. WattWise is non-commercial "
    "(owner decision, D022)."
)
REQUEST_PAUSE_S: Final = 1.0

#: Magnus form over water, Alduchov & Eskridge (1996): e_s(T) = 6.1094 exp(a T / (b + T)) hPa.
MAGNUS_A: Final = 17.625
MAGNUS_B: Final = 243.04  # degC
#: A dew point this far above the air temperature is a data error, not rounding: RH is unknown.
DEW_POINT_EXCESS_MAX: Final = 0.5  # degC
#: Alignment checks: solar days with less radiation than this are too cloudy to locate noon.
MIN_DAY_RADIATION: Final = 1000.0  # sum of hourly mean W/m2 over the day, i.e. Wh/m2
#: Half of the one-hour error the check exists to catch. Quarterly medians carry real cloud biases
#: (up to 16 min in convective Florida summers), so 15 min, tried first, was too tight.
CENTROID_TOLERANCE_MIN: Final = 30.0
TEMPERATURE_LAGS: Final = range(-3, 4)
MIN_LAG_PAIRS: Final = 48  # overlapping hours needed to measure a lag
#: A station's daily temperature cycle can run up to ~0.5 h from the ERA5 cell's (real data: site
#: medians -0.50 to +0.30 h, quarters within 0.33 h of their site's median). A quarter more than
#: PHASE_CONSISTENCY_H from its site's median phase is misaligned, and so is a site beyond
#: PHASE_MAX_H: halfway between the largest natural phase (0.5 h) and a one-hour error at a site
#: whose natural phase is 0 (1 h).
PHASE_CONSISTENCY_H: Final = 0.5
PHASE_MAX_H: Final = 0.75
#: The checks also run per calendar quarter; a quarter with less data than this is skipped.
QUARTER_MIN_SOLAR_DAYS: Final = 20
QUARTER_MIN_TEMPERATURE_HOURS: Final = 24 * 30
#: The final requested hour: its radiation mean would need the next day's label (by design).
LAST_HOUR: Final = pd.Timestamp(f"{END_DATE}T23:00:00Z")


@dataclass(frozen=True)
class Variable:
    name: str  # Open-Meteo variable
    column: str | None  # output column; None if only used for the alignment check
    unit: str
    preceding_hour: bool  # the value is the mean over the hour that ends at its label


VARIABLES: Final = (
    Variable("shortwave_radiation", "ghi_w_m2_era5", "W/m²", preceding_hour=True),
    Variable("direct_radiation", "direct_horizontal_w_m2_era5", "W/m²", preceding_hour=True),
    Variable("diffuse_radiation", "diffuse_horizontal_w_m2_era5", "W/m²", preceding_hour=True),
    Variable("direct_normal_irradiance", "dni_w_m2_era5", "W/m²", preceding_hour=True),
    Variable("cloud_cover", "cloud_cover_pct_era5", "%", preceding_hour=False),
    Variable("temperature_2m", None, "°C", preceding_hour=False),
)
HUMIDITY_COLUMN: Final = "relative_humidity_pct_derived"
OUTPUT_COLUMNS: Final = (
    "site_id",
    "timestamp",
    *(v.column for v in VARIABLES if v.column),
    HUMIDITY_COLUMN,
)


@dataclass(frozen=True)
class Site:
    site_id: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Response:
    times: pd.DatetimeIndex  # labels as returned, UTC
    values: Mapping[str, FloatArray]
    latitude: float  # the ERA5 grid cell Open-Meteo used
    longitude: float
    elevation_m: float  # Open-Meteo's terrain elevation for the requested point, not the cell


@dataclass(frozen=True)
class Enrichment:
    table: pd.DataFrame
    checks: dict[str, dict[str, object]]
    stats: dict[str, object] = field(default_factory=dict)
    corrections: tuple[Correction, ...] = ()

    @property
    def aligned(self) -> bool:
        """True only if at least one site was checked and every site passed."""
        return bool(self.checks) and all(bool(c["aligned"]) for c in self.checks.values())


# ---------------------------------------------------------------------------
# Sites and requests
# ---------------------------------------------------------------------------


def located_sites(
    metadata: pd.DataFrame, corrections: Sequence[Correction] = CORRECTIONS
) -> tuple[tuple[Site, ...], tuple[Correction, ...]]:
    """Sites with coordinates (after the metadata corrections), sorted by site ID."""
    corrected, applied = apply_corrections(metadata, corrections)
    known = corrected.dropna(subset=["lat", "lng"])
    if (known.groupby("site_id")[["lat", "lng"]].nunique() > 1).to_numpy().any():
        raise ValueError("A site has buildings with different coordinates; expected one per site.")
    first = known.groupby("site_id", sort=True)[["lat", "lng"]].first()
    sites = tuple(
        Site(str(site), round(float(row["lat"]), 4), round(float(row["lng"]), 4))
        for site, row in first.iterrows()
    )
    return sites, applied


def request_url(site: Site) -> str:
    params = [
        ("latitude", f"{site.latitude:.4f}"),
        ("longitude", f"{site.longitude:.4f}"),
        ("start_date", START_DATE),
        ("end_date", END_DATE),
        ("hourly", ",".join(v.name for v in VARIABLES)),
        ("models", MODEL),
        ("timezone", "GMT"),
        ("timeformat", "iso8601"),
    ]
    return f"{ENDPOINT}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------


def fetch(
    sites: Sequence[Site],
    destination: Path,
    manifest: Path,
    *,
    force: bool = False,
    opener: Opener | None = None,
    pause: float = REQUEST_PAUSE_S,
    now: datetime | None = None,
) -> dict[str, str]:
    """Fetch each site's response (or verify a recorded copy), recording each one in the manifest
    as soon as it is saved, so a failure part-way never orphans the files already fetched.

    Returns site -> status: "verified", "downloaded", or "changed" (a re-fetch of the same
    request whose content differs from the recorded one)."""
    files: dict[str, Any] = dict(_read_manifest(manifest).get("files", {}))
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    statuses: dict[str, str] = {}
    requested = 0
    for site in sites:
        path = destination / f"{site.site_id}.json"
        url = request_url(site)
        known: dict[str, Any] = files.get(site.site_id) or {}
        if path.exists() and not force:
            if known.get("url") == url and sha256_of(path) == known.get("sha256"):
                statuses[site.site_id] = "verified"
                continue
            raise AcquisitionError(
                f"{path} exists but is not recorded for this request in {manifest}. It was left "
                "untouched; re-run with --force to replace it."
            )
        if requested and pause:
            time.sleep(pause)
        requested += 1
        payload = _get(url, opener)
        try:
            response = parse_response(payload)  # validate before saving
        except (ValueError, KeyError, TypeError) as exc:
            raise AcquisitionError(
                f"{site.site_id}: Open-Meteo returned an invalid response ({exc}). Nothing was "
                "saved for this site."
            ) from exc
        _write_atomic(path, payload)
        content = content_sha256(payload)
        same_request = known.get("url") == url
        changed = same_request and known.get("content_sha256") not in (None, content)
        previous = {"previous_content_sha256": known.get("content_sha256")} if changed else {}
        files[site.site_id] = previous | {
            "url": url,
            "local_path": path.name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content_sha256": content,
            "site_latitude": site.latitude,
            "site_longitude": site.longitude,
            "grid_latitude": response.latitude,
            "grid_longitude": response.longitude,
            "dem_elevation_m": response.elevation_m,
            "grid_distance_km": round(_distance_km(site, response), 1),
            "fetched_at": stamp,
        }
        _write_manifest(manifest, files)  # record each file as soon as it is saved
        statuses[site.site_id] = "changed" if changed else "downloaded"
    _write_manifest(manifest, files)
    return statuses


def content_sha256(payload: bytes) -> str:
    """A hash of the data in a response, ignoring per-request fields like generationtime_ms."""
    data = json.loads(payload)
    kept = {
        k: data[k]
        for k in ("latitude", "longitude", "elevation", "utc_offset_seconds", "hourly_units")
    }
    kept["hourly"] = data["hourly"]
    return hashlib.sha256(
        json.dumps(kept, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def parse_response(payload: bytes) -> Response:
    """Validate and parse an Open-Meteo archive response."""
    data = json.loads(payload)
    if data.get("error"):
        raise ValueError(f"Open-Meteo returned an error: {data.get('reason')}")
    if data.get("utc_offset_seconds") != 0:
        raise ValueError("Expected UTC timestamps (timezone=GMT).")
    hourly, units = data["hourly"], data["hourly_units"]
    for variable in VARIABLES:
        if units.get(variable.name) != variable.unit:
            found = units.get(variable.name)
            raise ValueError(f"{variable.name}: expected unit {variable.unit!r}, got {found!r}.")
    times = pd.DatetimeIndex(pd.to_datetime(hourly["time"], format="%Y-%m-%dT%H:%M"))
    micros = np.asarray(times, dtype="datetime64[us]").astype(np.int64)
    if len(times) < 2 or not np.all(np.diff(micros) == 3_600_000_000):
        raise ValueError("Expected a regular hourly time axis.")
    values = {
        v.name: np.array([np.nan if x is None else x for x in hourly[v.name]], dtype=float)
        for v in VARIABLES
    }
    return Response(
        times=times.tz_localize("UTC").as_unit("us"),
        values=values,
        latitude=float(data["latitude"]),
        longitude=float(data["longitude"]),
        elevation_m=float(data["elevation"]),
    )


def _get(url: str, opener: Opener | None) -> bytes:
    try:
        with (opener or open_url)(url, 120.0) as handle:
            return handle.read()
    except urllib.error.HTTPError as exc:
        hint = "The free API's rate limit was reached; try again later. " if exc.code == 429 else ""
        raise AcquisitionError(
            f"Open-Meteo answered HTTP {exc.code} for {url}. {hint}{_error_reason(exc)}"
        ) from exc
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as exc:
        raise AcquisitionError(
            f"Could not read from Open-Meteo ({exc!r}). Check the connection and try again."
        ) from exc


def _error_reason(exc: urllib.error.HTTPError) -> str:
    """Open-Meteo explains errors in a JSON body ({"error": true, "reason": ...})."""
    try:
        reason = json.loads(exc.read()).get("reason")
    except (ValueError, AttributeError, OSError):
        return ""
    return f"Reason: {reason}" if reason else ""


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(payload)
    os.replace(partial, path)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return manifest


def _write_manifest(path: Path, files: Mapping[str, object]) -> None:
    manifest = {
        "dataset": "ERA5 hourly reanalysis via the Open-Meteo historical weather API",
        "endpoint": ENDPOINT,
        "model": MODEL,
        "period": [START_DATE, END_DATE],
        "variables": [v.name for v in VARIABLES],
        "attribution": ATTRIBUTION,
        "terms": TERMS,
        "documentation": "docs/DATASETS.md",
        "files": dict(sorted(files.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))


def _distance_km(site: Site, response: Response) -> float:
    lat1, lat2 = math.radians(site.latitude), math.radians(response.latitude)
    dlat = lat2 - lat1
    dlng = math.radians(response.longitude - site.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Physics: humidity and solar noon
# ---------------------------------------------------------------------------


def relative_humidity(
    temperature_c: npt.ArrayLike, dew_point_c: npt.ArrayLike
) -> tuple[FloatArray, int, int]:
    """RH in percent from the Magnus formula over water, with the counts of values set missing
    (dew point more than DEW_POINT_EXCESS_MAX above the air temperature) and capped at 100."""
    t = np.asarray(temperature_c, dtype=float)
    td = np.asarray(dew_point_c, dtype=float)
    rh = 100.0 * np.exp(MAGNUS_A * td / (MAGNUS_B + td) - MAGNUS_A * t / (MAGNUS_B + t))
    invalid = td > t + DEW_POINT_EXCESS_MAX
    capped = ~invalid & (rh > 100.0)
    rh = np.where(invalid, np.nan, np.minimum(rh, 100.0))
    return rh, int(invalid.sum()), int(capped.sum())


def solar_noon_offsets(radiation: pd.Series, longitude: float) -> pd.Series:
    """Per solar day: minutes by which the radiation-weighted centre of the day misses solar noon.

    `radiation` is indexed by the UTC start of each hourly interval and holds the interval's mean.
    Days are grouped in local mean solar time, so no day's daylight is split; only complete days
    with at least MIN_DAY_RADIATION are used. About 0 means the labels are right."""
    index = pd.DatetimeIndex(radiation.index)
    middle = index + pd.Timedelta(minutes=30)
    solar = middle + pd.to_timedelta(longitude / 15.0, unit="h")  # local mean solar time
    day = solar.floor("D")
    true_solar_hours = (
        np.asarray((solar - day) / pd.Timedelta(hours=1), dtype=float)
        + equation_of_time_min(middle) / 60.0
    )
    frame = pd.DataFrame(
        {
            "day": day,
            "w": radiation.to_numpy(dtype=float),
            "wt": radiation.to_numpy(dtype=float) * true_solar_hours,
        }
    )
    grouped = frame.groupby("day")
    complete = grouped["w"].count() == 24
    total = grouped["w"].sum()
    usable = complete & (total >= MIN_DAY_RADIATION)
    centre = grouped["wt"].sum()[usable] / total[usable]
    return (centre - 12.0) * 60.0


def best_lag(
    reference: pd.Series, other: pd.Series
) -> tuple[int | None, float | None, float | None]:
    """The lag in hours (other shifted by k) that best correlates with the reference, the best
    correlation and the correlation at lag 0. All None when no lag has MIN_LAG_PAIRS overlapping
    hours with some variation: nothing was measured, so nothing is reported."""
    scores = lag_scores(reference, other)
    if not scores:
        return None, None, None
    best = max(scores, key=lambda k: scores[k])
    return best, round(scores[best], 4), round(scores[0], 4) if 0 in scores else None


def lag_scores(reference: pd.Series, other: pd.Series) -> dict[int, float]:
    """Correlation of the reference with `other` shifted by k hours, for each measurable k."""
    scores: dict[int, float] = {}
    for k in TEMPERATURE_LAGS:
        shifted = other.reindex(pd.DatetimeIndex(reference.index) + pd.Timedelta(hours=k))
        pair = pd.DataFrame({"a": reference.to_numpy(), "b": shifted.to_numpy()}).dropna()
        if len(pair) >= MIN_LAG_PAIRS and pair["a"].std() > 0 and pair["b"].std() > 0:
            scores[k] = float(np.corrcoef(pair["a"], pair["b"])[0, 1])
    return scores


def phase_hours(reference: pd.Series, other: pd.Series) -> float | None:
    """The fractional lag at which `other` best matches the reference: the vertex of a parabola
    through the correlations at the best whole-hour lag and its two neighbours. Hourly data can
    then resolve half-hour phase differences that a whole-hour argmax turns into ties."""
    scores = lag_scores(reference, other)
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    if best - 1 not in scores or best + 1 not in scores:
        return float(best)
    left, centre, right = scores[best - 1], scores[best], scores[best + 1]
    curvature = left - 2 * centre + right
    return float(best) if curvature >= 0 else best + 0.5 * (left - right) / curvature


def _quarters(index: pd.Index) -> pd.PeriodIndex:
    return pd.DatetimeIndex(index).tz_convert("UTC").tz_localize(None).to_period("Q")


def quarterly_checks(
    offsets: pd.Series, observed: pd.Series, era5_temperature: pd.Series
) -> tuple[float | None, list[dict[str, object]]]:
    """Both alignment checks per calendar quarter, so a mislabel in part of the period cannot hide
    in a whole-period median. Returns the site's median quarterly temperature phase and the
    quarters; a quarter's check is skipped (and says so) without enough data.

    A quarter passes if its median solar-noon offset is within CENTROID_TOLERANCE_MIN and its
    temperature phase is within PHASE_CONSISTENCY_H of the site's median phase."""
    observed = observed.dropna()
    offset_quarters, observed_quarters = _quarters(offsets.index), _quarters(observed.index)
    measured = []
    for period in sorted(set(offset_quarters) | set(observed_quarters)):
        days = offsets[offset_quarters == period]
        hours = observed[observed_quarters == period]
        offset = float(days.median()) if len(days) >= QUARTER_MIN_SOLAR_DAYS else None
        phase = (
            phase_hours(hours, era5_temperature)
            if len(hours) >= QUARTER_MIN_TEMPERATURE_HOURS
            else None
        )
        measured.append((str(period), len(days), offset, len(hours), phase))
    phases = [p for *_, p in measured if p is not None]
    # Without a measurable quarter (a short period), fall back to the whole period's phase.
    site_phase = float(np.median(phases)) if phases else phase_hours(observed, era5_temperature)
    results: list[dict[str, object]] = []
    for quarter, days_count, offset, hours_count, phase in measured:
        solar_ok = offset is None or abs(offset) <= CENTROID_TOLERANCE_MIN
        phase_ok = phase is None or (
            site_phase is not None and abs(phase - site_phase) <= PHASE_CONSISTENCY_H
        )
        results.append(
            {
                "quarter": quarter,
                "solar_days": days_count,
                "noon_offset_min": _rounded(offset),
                "temperature_hours": hours_count,
                "temperature_phase_h": _rounded(phase, 2),
                "checked": offset is not None or phase is not None,
                "passed": solar_ok and phase_ok,
            }
        )
    return site_phase, results


def _rounded(value: float | None, digits: int = 1) -> float | None:
    """A rounded number for the manifest, or None (JSON null) for a missing or NaN value."""
    return None if value is None or math.isnan(value) else round(value, digits)


# ---------------------------------------------------------------------------
# The enrichment table
# ---------------------------------------------------------------------------


def era5_table(site_id: str, response: Response) -> pd.DataFrame:
    """ERA5 output columns indexed by the UTC start of each hour (radiation relabelled)."""
    columns = {}
    for v in VARIABLES:
        if v.column is None:
            continue
        stamps = response.times - pd.Timedelta(hours=1) if v.preceding_hour else response.times
        columns[v.column] = pd.Series(response.values[v.name], index=stamps)
    table = pd.DataFrame(columns).reindex(response.times)  # keep the requested hourly grid
    table.index.name = "timestamp"
    return table.reset_index().assign(site_id=site_id)


def enrich(
    responses: Mapping[str, Response],
    sites: Sequence[Site],
    weather: pd.DataFrame,
    corrections: tuple[Correction, ...] = (),
) -> Enrichment:
    """Combine ERA5 per located site with humidity derived from the observed `weather` (canonical,
    UTC) for every site, and run the alignment checks."""
    parts: list[pd.DataFrame] = []
    checks: dict[str, dict[str, object]] = {}
    for site in sites:
        response = responses[site.site_id]
        table = era5_table(site.site_id, response)
        radiation = table.set_index("timestamp")["ghi_w_m2_era5"]
        as_labelled = pd.Series(response.values["shortwave_radiation"], index=response.times)
        offsets = solar_noon_offsets(radiation, site.longitude)
        unshifted = solar_noon_offsets(as_labelled, site.longitude)
        observed = weather[weather["site_id"] == site.site_id].set_index("timestamp")
        temperature = observed["air_temperature_c"]
        era5_temperature = pd.Series(response.values["temperature_2m"], index=response.times)
        lag, best, at_zero = best_lag(temperature, era5_temperature)
        centre = float(offsets.median()) if len(offsets) else None
        site_phase, quarters = quarterly_checks(offsets, temperature, era5_temperature)
        whole_period = (
            centre is not None
            and abs(centre) <= CENTROID_TOLERANCE_MIN
            and site_phase is not None
            and abs(site_phase) <= PHASE_MAX_H
        )
        checks[site.site_id] = {
            "grid_latitude": response.latitude,
            "grid_longitude": response.longitude,
            "grid_distance_km": round(_distance_km(site, response), 1),
            "solar_days": len(offsets),
            "solar_noon_offset_min": _rounded(centre),
            "solar_noon_offset_min_if_labels_were_interval_starts": _rounded(
                float(unshifted.median()) if len(unshifted) else None
            ),
            "temperature_phase_h": _rounded(site_phase, 2),  # median over quarters
            "temperature_best_whole_hour_lag_h": lag,
            "temperature_correlation_best": best,
            "temperature_correlation_lag0": at_zero,
            "quarters_checked": sum(bool(q["checked"]) for q in quarters),
            "quarters_failed": [q["quarter"] for q in quarters if not q["passed"]],
            "quarters": quarters,
            "aligned": bool(whole_period and all(q["passed"] for q in quarters)),
        }
        parts.append(table)

    rh, invalid, capped = relative_humidity(
        weather["air_temperature_c"].to_numpy(dtype=float),
        weather["dew_temperature_c"].to_numpy(dtype=float),
    )
    humidity = pd.DataFrame(
        {
            "site_id": weather["site_id"].astype(str).to_numpy(),
            "timestamp": weather["timestamp"],
            HUMIDITY_COLUMN: np.round(rh, 2),
        }
    )
    era5_columns = [c for c in OUTPUT_COLUMNS[2:] if c != HUMIDITY_COLUMN]
    era5 = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(
            {"site_id": pd.Series(dtype="str"), "timestamp": pd.Series(dtype="datetime64[us, UTC]")}
            | {c: pd.Series(dtype="float64") for c in era5_columns}
        )
    )
    table = era5.merge(humidity, on=["site_id", "timestamp"], how="outer")
    table = table[list(OUTPUT_COLUMNS)].sort_values(["site_id", "timestamp"], kind="stable")
    table = table.reset_index(drop=True)
    located = table["site_id"].isin([s.site_id for s in sites]).to_numpy()
    missing_inputs = int(
        (weather["air_temperature_c"].isna() | weather["dew_temperature_c"].isna()).sum()
    )
    stats: dict[str, object] = {
        "rows": len(table),
        "sites_with_era5": len(parts),
        "sites_with_humidity_values": int(
            table.loc[table[HUMIDITY_COLUMN].notna(), "site_id"].nunique()
        ),
        "period_utc": [_iso(table["timestamp"].min()), _iso(table["timestamp"].max())]
        if len(table)
        else None,
        # Counted only where each source is meant to have a value.
        "era5_missing_at_located_sites": {
            c: int(table.loc[located, c].isna().sum()) for c in era5_columns
        },
        "era5_final_hours_without_radiation_by_design": int(
            (located & (table["timestamp"] == LAST_HOUR).to_numpy()).sum()
        ),
        "rows_without_era5_no_coordinates": int((~located).sum()),
        "humidity_observations": len(weather),
        "humidity_missing_temperature_or_dew_point": missing_inputs,
        "humidity_set_missing_dew_point_above_temperature": invalid,
        "humidity_capped_at_100": capped,
    }
    return Enrichment(table=table, checks=checks, stats=stats, corrections=corrections)


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def write(
    enrichment: Enrichment, inputs: Mapping[str, Path], output_dir: Path, inputs_verified: bool
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    enrichment.table.to_parquet(output_dir / "weather_enrichment.parquet", index=False)
    (output_dir / "report.md").write_bytes(to_markdown(enrichment).encode("utf-8"))
    digests = {n: sha256_of(output_dir / n) for n in ("weather_enrichment.parquet", "report.md")}
    manifest = {
        "pipeline": "wattwise.data.era5",
        "processing_version": PROCESSING_VERSION,
        "attribution": ATTRIBUTION,
        "terms": TERMS,
        "inputs_verified_against_recorded_checksums": inputs_verified,
        "inputs": {key: sha256_of(path) for key, path in sorted(inputs.items())},
        "metadata_corrections": [c.model_dump(mode="json") for c in enrichment.corrections],
        "columns": column_provenance(),
        "alignment_passed": enrichment.aligned,
        "checks": enrichment.checks,
        "stats": enrichment.stats,
        "outputs": {name: {"sha256": digest} for name, digest in digests.items()},
    }
    (output_dir / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    digests["manifest.json"] = sha256_of(output_dir / "manifest.json")
    return digests


def column_provenance() -> dict[str, dict[str, str]]:
    """Where each output column comes from, its unit and what its timestamp means."""
    columns = {
        v.column: {
            "source": f"modelled: ERA5 reanalysis via Open-Meteo ({v.name}), grid-cell value",
            "unit": v.unit,
            "timestamp": "start of the averaged hour (Open-Meteo labels its end)"
            if v.preceding_hour
            else "instant",
        }
        for v in VARIABLES
        if v.column
    }
    columns[HUMIDITY_COLUMN] = {
        "source": "derived: Magnus formula over water (Alduchov & Eskridge 1996) from BDG2's "
        "observed air temperature and dew point",
        "unit": "%",
        "timestamp": "instant (the BDG2 observation time)",
    }
    return columns


def to_markdown(enrichment: Enrichment) -> str:
    s = enrichment.stats
    lines = [
        "# Weather enrichment: ERA5 radiation and derived humidity",
        "",
        ATTRIBUTION,
        "",
        "ERA5 columns (`_era5`) are modelled values for a grid cell, not observations at the site. "
        "`relative_humidity_pct_derived` is computed from BDG2's observed temperature and dew "
        "point. Nothing is gap-filled across sources.",
        "",
        f"- Rows: {s['rows']:,}; sites with ERA5: {s['sites_with_era5']}; sites with humidity "
        f"values: {s['sites_with_humidity_values']}",
        f"- Humidity: {s['humidity_observations']:,} observations; "
        f"{s['humidity_missing_temperature_or_dew_point']:,} lack temperature or dew point; "
        f"{s['humidity_set_missing_dew_point_above_temperature']:,} set missing (dew point "
        f"above temperature); {s['humidity_capped_at_100']:,} capped at 100%",
        f"- Alignment: {'passed' if enrichment.aligned else '**FAILED**'}. Over the whole "
        f"period and in every calendar quarter with enough data, the median radiation-weighted "
        f"centre of the solar days must lie within {CENTROID_TOLERANCE_MIN:g} min of solar noon. "
        f"Each quarter's temperature phase (ERA5 vs observed) must lie within "
        f"{PHASE_CONSISTENCY_H:g} h of the site's median phase, which must lie within "
        f"{PHASE_MAX_H:g} h of zero.",
        "",
        "| Site | Grid cell | Distance (km) | Solar days | Median noon offset (min) | If labels "
        "were starts (min) | Temperature phase (h) | Correlation at lag 0 | Quarters checked "
        "| Quarters failed | Aligned |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for site, c in sorted(enrichment.checks.items()):
        failed = c["quarters_failed"]
        assert isinstance(failed, list)
        lines.append(
            f"| {site} | {c['grid_latitude']}, {c['grid_longitude']} | {c['grid_distance_km']} | "
            f"{c['solar_days']} | {c['solar_noon_offset_min']} | "
            f"{c['solar_noon_offset_min_if_labels_were_interval_starts']} | "
            f"{c['temperature_phase_h']} | {c['temperature_correlation_lag0']} | "
            f"{c['quarters_checked']} | {', '.join(failed) or 'none'} | "
            f"{'yes' if c['aligned'] else 'NO'} |"
        )
    return "\n".join(lines) + "\n"


def _iso(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.era5",
        description="Fetch ERA5 radiation for BDG2 sites and build the weather enrichment.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "verify", "prepare"):
        sub = commands.add_parser(name)
        sub.add_argument("--bdg2", type=Path, default=BDG2_DESTINATION)
        sub.add_argument("--dest", type=Path, default=DEFAULT_DESTINATION)
        sub.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        if name == "fetch":
            sub.add_argument("--force", action="store_true", help="re-fetch and replace copies")
        if name in ("verify", "prepare"):
            sub.add_argument(
                "--skip-input-verification",
                action="store_true",
                help="skip the BDG2 pinned-checksum check (ERA5 files are always checked)",
            )
        if name == "prepare":
            sub.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    metadata_file, weather_file = BDG2_FILES["metadata"], BDG2_FILES["weather"]
    try:
        verified = not getattr(args, "skip_input_verification", False)
        if verified:
            for remote in (metadata_file, weather_file):
                if verify(remote, args.bdg2) is None:
                    raise AcquisitionError(f"BDG2 {remote.key} is missing: run bdg2 fetch first.")
        metadata = pd.read_csv(args.bdg2 / metadata_file.local_path)
        sites, applied = located_sites(metadata)
        if args.command == "fetch":
            statuses = fetch(sites, args.dest, args.manifest, force=args.force)
            for site_id, status in statuses.items():
                print(f"{site_id}: {status}")
                if status == "changed":
                    print(
                        f"warning: {site_id}: the re-fetched data differs from the recorded data "
                        "(previous content hash kept in the manifest).",
                        file=sys.stderr,
                    )
            return 0
        recorded = _read_manifest(args.manifest).get("files", {})
        assert isinstance(recorded, dict)
        missing = []
        for site in sites:
            path = args.dest / f"{site.site_id}.json"
            entry = recorded.get(site.site_id, {})
            stale = entry.get("url") != request_url(site)  # recorded for a different request
            # Always checked: the ERA5 copy must be the one the manifest recorded.
            if not path.exists() or stale or sha256_of(path) != entry.get("sha256"):
                missing.append(site.site_id)
        if missing:
            raise AcquisitionError(
                f"Missing or unrecorded ERA5 responses for {missing}, or recorded for a different "
                "request: run era5 fetch (--force to replace)."
            )
        if args.command == "verify":
            print(f"{len(sites)} site responses verified against {args.manifest}")
            return 0
    except AcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    responses = {
        s.site_id: parse_response((args.dest / f"{s.site_id}.json").read_bytes()) for s in sites
    }
    timezones = dict(
        apply_corrections(metadata)[0].groupby("site_id")["timezone"].first().astype(str)
    )
    weather = site_weather(args.bdg2, timezones, WEATHER_CLOCKS)
    enrichment = enrich(responses, sites, weather, applied)
    print(to_markdown(enrichment))
    if not enrichment.aligned:
        print(
            f"error: the alignment checks failed; nothing was written to {args.output}.",
            file=sys.stderr,
        )
        return 1
    inputs = {f"era5/{s.site_id}": args.dest / f"{s.site_id}.json" for s in sites}
    inputs |= {"bdg2/metadata": args.bdg2 / metadata_file.local_path}
    inputs |= {"bdg2/weather": args.bdg2 / weather_file.local_path}
    for name, digest in write(enrichment, inputs, args.output, inputs_verified=verified).items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
