"""BDG2 preprocessing: raw files to canonical, UTC, contract-validated tables (D017).

Electricity only. Each site's timestamps are converted with its audited clock (D016); sites with
an undetermined clock are excluded, as are non-electric meters and meters with too little data.
Every exclusion is recorded with a reason. A seeded sample keeps the output laptop-sized.

    uv run python -m wattwise.data.bdg2_prepare --variant cleaned --sample-meters 20 --seed 2016

Outputs (git-ignored, under data/processed/): readings, buildings and weather as Parquet, an
exclusion log, a data-quality report (T008) and a manifest with provenance and statistics.
Identical inputs and options produce byte-identical outputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from wattwise.data import quality
from wattwise.data.acquisition import AcquisitionError, sha256_of, verify
from wattwise.data.bdg2 import COMMIT, DEFAULT_DESTINATION, FILES_BY_KEY
from wattwise.data.bdg2_audit import ELECTRICITY_CLOCKS, TIMESTAMP_FORMAT, WEATHER_CLOCKS
from wattwise.data.contracts import BUILDINGS, READINGS, WEATHER, MeterType, Unit
from wattwise.data.time_convention import Clock, to_utc
from wattwise.data.validation import to_canonical

PIPELINE_VERSION: Final = "1"
DEFAULT_OUTPUT: Final = Path("../data/processed/bdg2")
#: Metadata columns that flag a building's other meters ("Yes"), named like MeterType values.
OTHER_METER_FLAGS: Final = tuple(m.value for m in MeterType if m is not MeterType.ELECTRICITY)
INTERVAL_ASSUMPTION: Final = (
    "Timestamps are taken as the start of each hourly interval. BDG2 does not document start vs "
    "end, and the data cannot distinguish them (D016)."
)


class Variant(StrEnum):
    CLEANED = "cleaned"
    RAW = "raw"


VARIANT_FILE: Final = {Variant.CLEANED: "electricity_cleaned", Variant.RAW: "electricity_raw"}
#: Why each variant is used; recorded in the manifest (D017).
VARIANT_PURPOSE: Final = {
    Variant.CLEANED: "BDG2 removed outliers and zero readings: used for training baselines and "
    "for synthetic-injection benchmarks, where unlabelled real anomalies would blur the score.",
    Variant.RAW: "As published, with real (unlabelled) anomalies kept: used for exploration "
    "and for showing the detector on real data. Its anomalies are not ground truth.",
}


class Reason(StrEnum):
    NOT_ELECTRICITY = "not_electricity"
    NO_METADATA = "no_metadata"
    UNDETERMINED_CLOCK = "undetermined_clock"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_SAMPLED = "not_sampled"


@dataclass(frozen=True)
class Options:
    variant: Variant = Variant.CLEANED
    sample_meters: int = 20  # 0 means every eligible meter
    seed: int = 2016
    min_coverage_pct: float = 50.0


@dataclass(frozen=True)
class Prepared:
    options: Options
    readings: pd.DataFrame
    buildings: pd.DataFrame
    weather: pd.DataFrame
    exclusions: pd.DataFrame
    stats: dict[str, object] = field(default_factory=dict)


def prepare(
    raw_dir: Path,
    options: Options,
    electricity_clocks: Mapping[str, Clock] = ELECTRICITY_CLOCKS,
    weather_clocks: Mapping[str, Clock] = WEATHER_CLOCKS,
) -> Prepared:
    metadata = pd.read_csv(raw_dir / FILES_BY_KEY["metadata"].local_path)
    wide = pd.read_csv(raw_dir / FILES_BY_KEY[VARIANT_FILE[options.variant]].local_path)
    naive = pd.DatetimeIndex(pd.to_datetime(wide.pop("timestamp"), format=TIMESTAMP_FORMAT))
    sites = metadata.set_index("building_id")
    exclusions: list[dict[str, str]] = []

    for row in metadata.sort_values("building_id").itertuples(index=False):
        for meter_type in OTHER_METER_FLAGS:
            if getattr(row, meter_type, None) == "Yes":
                exclusions.append(
                    _exclusion(
                        str(row.building_id),
                        meter_type,
                        Reason.NOT_ELECTRICITY,
                        "meter type not analysed in this version (D012)",
                    )
                )

    utc_by_site: dict[str, pd.DatetimeIndex] = {}
    dropped_hours: dict[str, int] = {}
    eligible: list[str] = []
    coverage_pct: dict[str, float] = {}
    for building in sorted(wide.columns):
        if building not in sites.index:
            exclusions.append(
                _exclusion(building, "electricity", Reason.NO_METADATA, "no metadata row")
            )
            continue
        site = str(sites.at[building, "site_id"])
        clock = electricity_clocks.get(site, Clock.UNDETERMINED)
        if clock is Clock.UNDETERMINED:
            exclusions.append(
                _exclusion(
                    building,
                    "electricity",
                    Reason.UNDETERMINED_CLOCK,
                    f"site {site}: timestamp clock undetermined by the audit (D016)",
                )
            )
            continue
        if site not in utc_by_site:
            utc_by_site[site] = to_utc(naive, str(sites.at[building, "timezone"]), clock)
            dropped_hours[site] = int(np.asarray(utc_by_site[site].isna()).sum())
        convertible = ~np.asarray(utc_by_site[site].isna())
        values = wide[building].to_numpy(dtype=float)[convertible]
        share = 100.0 * float(np.mean(~np.isnan(values))) if values.size else 0.0
        coverage_pct[building] = round(share, 2)
        if share < options.min_coverage_pct:
            exclusions.append(
                _exclusion(
                    building,
                    "electricity",
                    Reason.INSUFFICIENT_DATA,
                    f"{share:.1f}% of hours have a reading (minimum {options.min_coverage_pct:g}%)",
                )
            )
            continue
        eligible.append(building)

    if not eligible:
        raise ValueError(
            "No eligible electricity meters: every meter was excluded (see the exclusion reasons). "
            "Check the clocks, the variant and --min-coverage."
        )
    sampled = _sample(eligible, options)
    for building in eligible:
        if building not in sampled:
            exclusions.append(
                _exclusion(
                    building,
                    "electricity",
                    Reason.NOT_SAMPLED,
                    f"eligible; outside the seeded sample (seed {options.seed})",
                )
            )

    readings = _readings(wide, sites, sampled, utc_by_site)
    buildings = _buildings(sites, sampled)
    site_timezones = dict(zip(buildings["site_id"], buildings["timezone"], strict=True))
    weather = _weather(raw_dir, site_timezones, weather_clocks)
    log = pd.DataFrame(exclusions, columns=["building_id", "meter_type", "reason", "detail"])
    log = log.sort_values(["reason", "building_id", "meter_type"], kind="stable").reset_index(
        drop=True
    )

    stats: dict[str, object] = {
        "metadata_buildings": len(metadata),
        "electricity_meters": len(wide.columns),
        "eligible_meters": len(eligible),
        "sampled_meters": len(sampled),
        "excluded_by_reason": {r.value: int((log["reason"] == r.value).sum()) for r in Reason},
        "readings_rows": len(readings),
        "readings_missing_values": int(readings["value"].isna().sum()),
        "period_utc": [_iso(readings["timestamp"].min()), _iso(readings["timestamp"].max())]
        if len(readings)
        else None,
        "sampled_meters_by_site": {
            site: int(count) for site, count in sorted(buildings["site_id"].value_counts().items())
        },
        "clock_by_sampled_site": {
            site: electricity_clocks[site].value for site in sorted(set(buildings["site_id"]))
        },
        "dropped_unconvertible_hours_by_site": {
            site: dropped_hours[site] for site in sorted(set(buildings["site_id"]))
        },
        "weather_rows": len(weather),
        "weather_join_coverage_pct": _join_coverage(readings, buildings, weather),
        "sampled_coverage_pct": {b: coverage_pct[b] for b in sampled},
    }
    return Prepared(options, readings, buildings, weather, log, stats)


def _sample(eligible: Sequence[str], options: Options) -> list[str]:
    ordered = sorted(eligible)
    if options.sample_meters <= 0 or options.sample_meters >= len(ordered):
        return ordered
    rng = np.random.default_rng(options.seed)
    chosen = rng.choice(len(ordered), size=options.sample_meters, replace=False)
    return sorted(ordered[i] for i in chosen)


def _readings(
    wide: pd.DataFrame,
    sites: pd.DataFrame,
    sampled: Sequence[str],
    utc_by_site: Mapping[str, pd.DatetimeIndex],
) -> pd.DataFrame:
    parts = []
    for building in sampled:
        utc = utc_by_site[str(sites.at[building, "site_id"])]
        keep = ~np.asarray(utc.isna())
        parts.append(
            pd.DataFrame(
                {
                    "timestamp": utc[keep],
                    "meter_id": f"{building}:{MeterType.ELECTRICITY.value}",
                    "building_id": building,
                    "meter_type": MeterType.ELECTRICITY.value,
                    "unit": Unit.KWH.value,
                    "value": wide[building].to_numpy(dtype=float)[keep],
                }
            )
        )
    frame = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=READINGS.column_names)
    )
    return to_canonical(frame, READINGS)


def _buildings(sites: pd.DataFrame, sampled: Sequence[str]) -> pd.DataFrame:
    rows = sites.loc[list(sampled)]
    frame = pd.DataFrame(
        {
            "building_id": list(sampled),
            "site_id": rows["site_id"].astype(str).to_numpy(),
            "timezone": rows["timezone"].astype(str).to_numpy(),
            "primary_use": rows["primaryspaceusage"].to_numpy(dtype=object),
            "floor_area_m2": rows["sqm"].to_numpy(dtype=float),
            "latitude": rows["lat"].to_numpy(dtype=float),
            "longitude": rows["lng"].to_numpy(dtype=float),
        }
    )
    return to_canonical(frame, BUILDINGS)


def _weather(
    raw_dir: Path, site_timezones: Mapping[str, str], clocks: Mapping[str, Clock]
) -> pd.DataFrame:
    """Weather for the given sites, converted with each site's weather clock."""
    raw = pd.read_csv(
        raw_dir / FILES_BY_KEY["weather"].local_path,
        usecols=["timestamp", "site_id", "airTemperature", "dewTemperature", "windSpeed"],
    )
    parts = []
    for site, timezone in sorted(site_timezones.items()):
        rows = raw[raw["site_id"] == site]
        clock = clocks.get(site, Clock.UNDETERMINED)
        if rows.empty or clock is Clock.UNDETERMINED:
            continue  # reported through the weather join coverage
        naive = pd.DatetimeIndex(pd.to_datetime(rows["timestamp"], format=TIMESTAMP_FORMAT))
        utc = to_utc(naive, timezone, clock)
        keep = ~np.asarray(utc.isna())
        parts.append(
            pd.DataFrame(
                {
                    "site_id": site,
                    "timestamp": utc[keep],
                    "air_temperature_c": rows["airTemperature"].to_numpy(dtype=float)[keep],
                    "dew_temperature_c": rows["dewTemperature"].to_numpy(dtype=float)[keep],
                    "wind_speed_m_s": rows["windSpeed"].to_numpy(dtype=float)[keep],
                }
            )
        )
    frame = (
        pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=WEATHER.column_names)
    )
    return to_canonical(frame, WEATHER)


def _join_coverage(
    readings: pd.DataFrame, buildings: pd.DataFrame, weather: pd.DataFrame
) -> dict[str, float]:
    """Per site: share of reading hours that have an air temperature in the weather table."""
    if readings.empty:
        return {}
    site_of = dict(zip(buildings["building_id"], buildings["site_id"], strict=True))
    hours = readings[["building_id", "timestamp"]].assign(
        site_id=readings["building_id"].map(site_of)
    )
    hours = hours[["site_id", "timestamp"]].drop_duplicates()
    known = weather.dropna(subset=["air_temperature_c"])[["site_id", "timestamp"]]
    joined = hours.merge(known.assign(found=True), on=["site_id", "timestamp"], how="left")
    found = joined["found"].notna()
    return {
        str(site): round(100.0 * float(group.mean()), 2)
        for site, group in found.groupby(joined["site_id"], sort=True)
    }


def _exclusion(building: str, meter_type: str, reason: Reason, detail: str) -> dict[str, str]:
    return {
        "building_id": building,
        "meter_type": meter_type,
        "reason": reason.value,
        "detail": detail,
    }


def _iso(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Writing and the CLI
# ---------------------------------------------------------------------------

OUTPUT_FILES: Final = (
    "readings.parquet",
    "buildings.parquet",
    "weather.parquet",
    "exclusions.csv",
    "quality_report.json",
    "quality_report.md",
)


def write(
    prepared: Prepared,
    raw_dir: Path,
    output_dir: Path,
    inputs_verified: bool,
) -> dict[str, str]:
    """Write all outputs and the manifest. Returns file name -> SHA-256."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report = quality.assess(prepared.readings, prepared.buildings)
    prepared.readings.to_parquet(output_dir / "readings.parquet", index=False)
    prepared.buildings.to_parquet(output_dir / "buildings.parquet", index=False)
    prepared.weather.to_parquet(output_dir / "weather.parquet", index=False)
    (output_dir / "exclusions.csv").write_bytes(
        prepared.exclusions.to_csv(index=False, lineterminator="\n").encode("utf-8")
    )
    (output_dir / "quality_report.json").write_bytes(quality.to_json(report).encode("utf-8"))
    title = f"BDG2 {prepared.options.variant.value} sample"
    (output_dir / "quality_report.md").write_bytes(
        quality.to_markdown(report, title).encode("utf-8")
    )

    digests = {name: sha256_of(output_dir / name) for name in OUTPUT_FILES}
    inputs = {
        key: {
            "local_path": FILES_BY_KEY[key].local_path,
            "sha256": sha256_of(raw_dir / FILES_BY_KEY[key].local_path),
        }
        for key in ("metadata", "weather", VARIANT_FILE[prepared.options.variant])
    }
    manifest = {
        "pipeline": "wattwise.data.bdg2_prepare",
        "pipeline_version": PIPELINE_VERSION,
        "dataset": "Building Data Genome Project 2 (BDG2)",
        "dataset_commit": COMMIT,
        "inputs_verified_against_pinned_checksums": inputs_verified,
        "inputs": inputs,
        "options": {
            "variant": prepared.options.variant.value,
            "sample_meters": prepared.options.sample_meters,
            "seed": prepared.options.seed,
            "min_coverage_pct": prepared.options.min_coverage_pct,
        },
        "assumptions": {
            "variant": VARIANT_PURPOSE[prepared.options.variant],
            "interval": INTERVAL_ASSUMPTION,
            "clocks": "Per-site clocks from the T009a audit (D016); weather uses its own clock.",
        },
        "stats": prepared.stats,
        "outputs": _output_entries(prepared, digests),
        "licence": "BDG2-derived data: attribute the source and do not redistribute (D014).",
    }
    (output_dir / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    )
    digests["manifest.json"] = sha256_of(output_dir / "manifest.json")
    return digests


def _output_entries(prepared: Prepared, digests: Mapping[str, str]) -> dict[str, object]:
    rows = {
        "readings.parquet": len(prepared.readings),
        "buildings.parquet": len(prepared.buildings),
        "weather.parquet": len(prepared.weather),
        "exclusions.csv": len(prepared.exclusions),
    }
    entries: dict[str, object] = {}
    for name in OUTPUT_FILES:
        entry: dict[str, object] = {"sha256": digests[name]}
        if name in rows:
            entry["rows"] = rows[name]
        entries[name] = entry
    return entries


def verify_inputs(raw_dir: Path, variant: Variant) -> None:
    """Check the input files against the pinned BDG2 checksums (raises AcquisitionError)."""
    for key in ("metadata", "weather", VARIANT_FILE[variant]):
        if verify(FILES_BY_KEY[key], raw_dir) is None:
            raise AcquisitionError(
                f"{key}: {raw_dir / FILES_BY_KEY[key].local_path} is missing. Download it with: "
                "uv run python -m wattwise.data.bdg2 fetch"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.bdg2_prepare",
        description="Convert BDG2 electricity to canonical UTC tables for a seeded sample.",
    )
    parser.add_argument("--raw", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output", type=Path, help="default: ../data/processed/bdg2/<variant>")
    parser.add_argument("--variant", choices=[v.value for v in Variant], default="cleaned")
    parser.add_argument("--sample-meters", type=int, default=20, help="0 = all eligible meters")
    parser.add_argument("--seed", type=int, default=2016)
    parser.add_argument("--min-coverage", type=float, default=50.0, help="percent of hours")
    parser.add_argument(
        "--skip-input-verification",
        action="store_true",
        help="do not check inputs against the pinned checksums (tests and experiments only)",
    )
    args = parser.parse_args(argv)
    options = Options(Variant(args.variant), args.sample_meters, args.seed, args.min_coverage)
    output = args.output or DEFAULT_OUTPUT / options.variant.value
    try:
        if not args.skip_input_verification:
            verify_inputs(args.raw, options.variant)
        prepared = prepare(args.raw, options)
    except (AcquisitionError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    digests = write(prepared, args.raw, output, inputs_verified=not args.skip_input_verification)
    print(json.dumps(prepared.stats["excluded_by_reason"]))
    stats = prepared.stats
    print(
        f"{stats['sampled_meters']} of {stats['eligible_meters']} eligible meters, "
        f"{stats['readings_rows']} readings -> {output}"
    )
    for name, digest in digests.items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
