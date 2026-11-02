"""HKUST campus smart meters as WattWise readings (T041, D063).

Li, Wang, Qu, Chui and Leung-Shea (2024), *A 2.5-year campus-level smart meter database with
equipment data for energy analytics*, Dryad doi:10.5061/dryad.k3j9kd5h6 (CC0), obtained with
`python -m wattwise.data.dryad fetch hkust`; article in Scientific Data,
doi:10.1038/s41597-024-04106-1 (read through Europe PMC, PMC11599614).

What the files hold, and how they become hourly readings:

- **Cumulative registers in kWh** (the article's meter table and the Brick metadata's
  `unit:KiloW-HR`), one workbook per meter, two columns: an Excel date serial and the register.
  The clean dataset resamples each meter to its own interval (T15, T30, T60 or T1440). Missing
  values were "neither imputed nor subjected to outlier detection" (article), so nothing here
  needs to be unmasked.
- **Clock: Hong Kong local time** (UTC+8, no daylight saving), inferred: the article does not say.
  Two checks on the data: the padding rows begin at 1970-01-01 08:00, the Unix epoch in UTC+8; and
  campus consumption is lowest at 05:00 and rises from 06:00 on the parsed clock.
- **Hourly consumption** for the hour starting at h is the register at h+1 minus the register at
  h (local hour boundaries, from T15, T30 or T60 files), labelled with the hour's start in UTC.
  T1440 meters are daily only and are not used. A difference is **invalid**, and the hour
  missing, when it is negative (a register reset or device restart, which the article mentions)
  or above `SPIKE_FACTOR` times the meter's 99th percentile of non-negative differences (the jump
  that follows a restart). Nothing is filled.
- **Register step:** some registers count in coarse units (the article lists 0.01 and 0.1 kWh
  resolutions; some files step by 100 kWh). The smallest positive hourly difference is reported
  per meter, because a coarse register makes any hourly forecast lumpy.

Weather: the dataset has none. `fetch-weather` requests ERA5 reanalysis for the campus from
Open-Meteo (the T007d source, D023; free for non-commercial use, D022): temperature, dew point,
wind, global radiation and cloud cover. These are modelled values for a 0.25-degree grid cell,
substituted for the observed weather the model was trained with; the T041 report runs the model
both with and without them.

    uv run python -m wattwise.data.hkust prepare         # readings into ../data/processed/hkust
    uv run python -m wattwise.data.hkust fetch-weather   # ERA5 for the campus, ../data/raw/hkust
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from wattwise.data.acquisition import AcquisitionError, Opener, open_url, sha256_of
from wattwise.data.era5 import content_sha256, relative_humidity

SITE_ID: Final = "hkust"
TIMEZONE: Final = "Asia/Hong_Kong"
#: The campus location given in the dataset's README.
LATITUDE: Final = 22.3363
LONGITUDE: Final = 114.2634
FIRST_HOUR_LOCAL: Final = pd.Timestamp("2022-01-01 00:00")
END_LOCAL: Final = pd.Timestamp("2024-05-28 00:00")  # the README: collected to 2024-05-27
HOURLY_TIERS: Final = ("T15", "T30", "T60")
DAILY_TIER: Final = "T1440"
SPIKE_FACTOR: Final = 10.0
EXCEL_EPOCH: Final = pd.Timestamp("1899-12-30")
DEFAULT_ARCHIVE: Final = Path("../data/raw/hkust/All_Data.zip")
DEFAULT_OUTPUT: Final = Path("../data/processed/hkust")
DEFAULT_WEATHER: Final = Path("../data/raw/hkust/era5_campus.json")
DEFAULT_WEATHER_MANIFEST: Final = Path("../data/manifests/hkust_era5.json")
CLEAN_PREFIX: Final = "All Data/Clean Dataset/Resappled data/"  # the authors' spelling
METADATA_MEMBER: Final = "All Data/Clean Dataset/HKUST_Meter_Metadata.ttl"
WEATHER_ENDPOINT: Final = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_VARIABLES: Final = (
    ("temperature_2m", "°C"),
    ("dew_point_2m", "°C"),
    ("wind_speed_10m", "m/s"),
    ("shortwave_radiation", "W/m²"),
    ("cloud_cover", "%"),
)
WEATHER_START: Final = "2021-12-01"
WEATHER_END: Final = "2024-05-31"

_CELL = re.compile(
    rb'<c r="([AB])(\d+)"[^>]*?(?:/>|>(?:<v>([^<]*)</v>|<is><t>([^<]*)</t></is>)?</c>)'
)
_METERED = re.compile(r"bldg:(\S+) a brick:(\w+)\s*;\s*brick:isMeteredBy ([^.;]+)[.;]", re.S)


# ---------------------------------------------------------------------------
# Workbooks
# ---------------------------------------------------------------------------


def read_register(workbook: bytes) -> pd.Series:
    """The register of one meter workbook, indexed by local (naive) time. Empty or non-numeric
    cells (the authors' 'NAN') are NaN."""
    book = zipfile.ZipFile(io.BytesIO(workbook))
    xml = book.read("xl/worksheets/sheet1.xml")
    times: dict[int, float] = {}
    values: dict[int, float] = {}
    for column, row, number, text in _CELL.findall(xml):
        r = int(row)
        if r == 1:  # the header: time, number
            continue
        target = times if column == b"A" else values
        target[r] = _number(number or text)
    rows = sorted(r for r, t in times.items() if np.isfinite(t))
    serial = np.array([times[r] for r in rows], dtype=float)
    stamps = EXCEL_EPOCH + pd.to_timedelta(np.round(serial * 1440).astype(np.int64), unit="min")
    register = pd.Series([values.get(r, np.nan) for r in rows], index=stamps, dtype=float)
    return register[~register.index.duplicated()].sort_index()


def _number(raw: bytes) -> float:
    try:
        return float(raw) if raw else np.nan
    except ValueError:
        return np.nan


@dataclass(frozen=True)
class Hourly:
    kwh: pd.Series  # indexed by UTC hour start, NaN where missing or invalid
    stats: dict[str, Any]


def hourly_consumption(register: pd.Series) -> Hourly:
    """Hourly kWh from a register on local time, over the dataset's period."""
    hours = pd.date_range(FIRST_HOUR_LOCAL, END_LOCAL, freq="h", inclusive="left")
    boundaries = pd.date_range(FIRST_HOUR_LOCAL, END_LOCAL, freq="h")  # one more, for the last
    on_hour = (
        register[pd.DatetimeIndex(register.index).minute == 0]
        .reindex(boundaries)
        .to_numpy(dtype=float)
    )
    diff = on_hour[1:] - on_hour[:-1]
    present = np.isfinite(diff)
    negative = present & (diff < 0)
    usable = diff[present & ~negative]
    cap = SPIKE_FACTOR * float(np.quantile(usable, 0.99)) if usable.size else np.inf
    spike = present & ~negative & (diff > cap) & (cap > 0)
    valid = present & ~negative & ~spike
    kwh = np.where(valid, diff, np.nan)
    positive = kwh[valid & (kwh > 0)]
    index = hours.tz_localize(TIMEZONE).tz_convert("UTC")
    stats = {
        "hours": len(hours),
        "valid_hours": int(valid.sum()),
        "missing_hours": int((~present).sum()),
        "negative_hours": int(negative.sum()),
        "spike_hours": int(spike.sum()),
        "zero_share": _share(np.sum(kwh[valid] == 0), valid.sum()),
        "register_step_kwh": _round(float(positive.min())) if positive.size else None,
        "mean_kwh": _round(float(np.mean(kwh[valid]))) if valid.any() else None,
    }
    return Hourly(pd.Series(kwh, index=index, name="value"), stats)


def metered_classes(ttl: str) -> dict[str, str]:
    """Meter ID (e.g. 'D0001') -> the Brick class of what it meters (a room, switch, device)."""
    result: dict[str, str] = {}
    for _entity, brick_class, meters in _METERED.findall(ttl):
        for meter in re.findall(r"bldg:Meter_(\w+)", meters):
            result.setdefault(meter, brick_class)
    return result


def meter_members(names: Sequence[str]) -> dict[str, tuple[str, str]]:
    """Meter ID -> (tier, archive member) for the clean dataset's workbooks."""
    found: dict[str, tuple[str, str]] = {}
    for name in names:
        if not (name.startswith(CLEAN_PREFIX) and name.endswith(".xlsx")):
            continue
        tier = name[len(CLEAN_PREFIX) :].split("/")[0]
        meter = name.rsplit("/", 1)[-1].removeprefix("GUI_NO.").removesuffix(".xlsx")
        if meter in found:
            raise ValueError(f"meter {meter} appears in two tiers ({found[meter][0]}, {tier}).")
        found[meter] = (tier, name)
    return found


# ---------------------------------------------------------------------------
# Preparing readings
# ---------------------------------------------------------------------------


def prepare(archive: Path, output: Path) -> dict[str, Any]:
    """Write `readings.parquet` (canonical hourly readings, UTC) and `meters.csv` (one row per
    meter: tier, metered class, coverage), and return the summary."""
    handle = zipfile.ZipFile(archive)
    members = meter_members(handle.namelist())
    classes = metered_classes(handle.read(METADATA_MEMBER).decode("utf-8"))
    parts: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []
    for meter in sorted(members):
        tier, member = members[meter]
        row: dict[str, Any] = {
            "meter_id": meter,
            "tier": tier,
            "metered_class": classes.get(meter, "unknown"),
        }
        if tier not in HOURLY_TIERS:
            rows.append(row | {"used": False, "reason": "daily data only (T1440)"})
            continue
        hourly = hourly_consumption(read_register(handle.read(member)))
        row |= hourly.stats
        if hourly.stats["valid_hours"] == 0:
            rows.append(row | {"used": False, "reason": "no valid hourly consumption"})
            continue
        if hourly.stats["zero_share"] == 1.0:
            rows.append(row | {"used": False, "reason": "every valid hour is zero"})
            continue
        rows.append(row | {"used": True, "reason": ""})
        values = hourly.kwh.dropna()
        parts.append(
            pd.DataFrame(
                {
                    "meter_id": meter,
                    "building_id": meter,  # each meter is its own unit (D063)
                    "timestamp": values.index,
                    "value": values.to_numpy(dtype=float),
                }
            )
        )
    readings = pd.concat(parts, ignore_index=True)
    readings["meter_id"] = readings["meter_id"].astype("string")
    readings["building_id"] = readings["building_id"].astype("string")
    meters = pd.DataFrame(rows)
    output.mkdir(parents=True, exist_ok=True)
    readings.to_parquet(output / "readings.parquet", index=False)
    meters.to_csv(output / "meters.csv", index=False, lineterminator="\n")
    summary = {
        "archive_sha256": sha256_of(archive),
        "meters_in_archive": len(members),
        "meters_used": int(meters["used"].sum()),
        "not_used": meters.loc[~meters["used"], "reason"].value_counts().to_dict(),
        "readings": len(readings),
        "first_utc": str(readings["timestamp"].min()),
        "last_utc": str(readings["timestamp"].max()),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def buildings_table(meter_ids: Sequence[str]) -> pd.DataFrame:
    """One 'building' per meter on the HKUST site, for the feature pipeline."""
    return pd.DataFrame(
        {
            "building_id": list(meter_ids),
            "site_id": SITE_ID,
            "timezone": TIMEZONE,
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
        }
    )


# ---------------------------------------------------------------------------
# Weather (ERA5 through Open-Meteo)
# ---------------------------------------------------------------------------


def weather_url() -> str:
    params = [
        ("latitude", f"{LATITUDE:.4f}"),
        ("longitude", f"{LONGITUDE:.4f}"),
        ("start_date", WEATHER_START),
        ("end_date", WEATHER_END),
        ("hourly", ",".join(name for name, _ in WEATHER_VARIABLES)),
        ("models", "era5"),
        ("wind_speed_unit", "ms"),
        ("timezone", "GMT"),
        ("timeformat", "iso8601"),
    ]
    return f"{WEATHER_ENDPOINT}?{urlencode(params)}"


def fetch_weather(
    path: Path, manifest: Path, *, opener: Opener | None = None, now: datetime | None = None
) -> str:
    """Download the campus ERA5 response once, validate it, and record its hash. An existing
    file is verified against the manifest instead. Returns 'verified' or 'downloaded'."""
    url = weather_url()
    if path.exists():
        recorded = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        if recorded.get("url") == url and recorded.get("sha256") == sha256_of(path):
            return "verified"
        raise AcquisitionError(f"{path} exists but does not match {manifest}; left untouched.")
    try:
        with (opener or open_url)(url, 120.0) as handle:
            payload = handle.read()
    except OSError as exc:
        raise AcquisitionError(f"Could not read from Open-Meteo ({exc!r}).") from exc
    parse_weather(payload)  # validate before saving
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "source": "Open-Meteo historical archive, model ERA5 (Copernicus); CC BY 4.0, "
        "'Weather data by Open-Meteo.com'",
        "url": url,
        "local_path": f"data/raw/hkust/{path.name}",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content_sha256": content_sha256(payload),
        "fetched_at": stamp,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return "downloaded"


def parse_weather(payload: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The canonical weather table (temperature, dew point, wind; ERA5 substituted for
    observations) and the enrichment table (derived humidity, radiation, cloud cover), both on
    the HKUST site in UTC. Radiation is the mean over the hour ending at its label, so it is
    relabelled one hour earlier (as in T007d); instantaneous values keep their time."""
    data = json.loads(payload)
    if data.get("error"):
        raise ValueError(f"Open-Meteo returned an error: {data.get('reason')}")
    if data.get("utc_offset_seconds") != 0:
        raise ValueError("Expected UTC timestamps (timezone=GMT).")
    hourly, units = data["hourly"], data["hourly_units"]
    for name, unit in WEATHER_VARIABLES:
        if units.get(name) != unit:
            raise ValueError(f"{name}: expected unit {unit!r}, got {units.get(name)!r}.")
    naive = pd.DatetimeIndex(pd.to_datetime(hourly["time"], format="%Y-%m-%dT%H:%M"))
    steps = np.diff(naive.to_numpy().astype("datetime64[s]").astype(np.int64))
    if len(naive) < 2 or not (steps == 3600).all():
        raise ValueError("Expected a regular hourly time axis.")
    times = naive.tz_localize("UTC")

    def column(name: str) -> pd.Series:
        values = [np.nan if x is None else float(x) for x in hourly[name]]
        return pd.Series(values, index=times, dtype=float)

    temperature, dew = column("temperature_2m"), column("dew_point_2m")
    weather = pd.DataFrame(
        {
            "site_id": SITE_ID,
            "timestamp": times,
            "air_temperature_c": temperature.to_numpy(),
            "dew_temperature_c": dew.to_numpy(),
            "wind_speed_m_s": column("wind_speed_10m").to_numpy(),
        }
    )
    radiation = column("shortwave_radiation")
    radiation.index = pd.DatetimeIndex(radiation.index) - pd.Timedelta(hours=1)
    enrichment = pd.DataFrame(
        {
            "site_id": SITE_ID,
            "timestamp": times,
            "relative_humidity_pct_derived": relative_humidity(temperature, dew)[0],
            "ghi_w_m2_era5": radiation.reindex(times).to_numpy(),
            "cloud_cover_pct_era5": column("cloud_cover").to_numpy(),
        }
    )
    return weather, enrichment


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.hkust",
        description="Prepare the HKUST meters as hourly readings, and fetch campus weather.",
    )
    parser.add_argument("command", choices=["prepare", "fetch-weather"])
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--weather", type=Path, default=DEFAULT_WEATHER)
    parser.add_argument("--weather-manifest", type=Path, default=DEFAULT_WEATHER_MANIFEST)
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch-weather":
            print(fetch_weather(args.weather, args.weather_manifest), args.weather)
            return 0
        if not args.archive.exists():
            print(
                f"error: {args.archive} is missing. Run: uv run python -m wattwise.data.dryad "
                "fetch hkust",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(prepare(args.archive, args.output), indent=2))
    except AcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _share(count: Any, total: Any) -> float | None:
    return round(float(count) / float(total), 4) if total else None


def _round(value: float) -> float:
    return round(value, 4)


if __name__ == "__main__":
    raise SystemExit(main())
