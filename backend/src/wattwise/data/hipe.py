"""HIPE (High-resolution Industrial Production Energy): pinned source, acquisition, preparation.

**Real data.** Smart-meter readings of ten machines and the main terminal of a power-electronics
production plant (KIT, Karlsruhe), October to December 2017, published on Zenodo under CC BY 4.0.
It is the evidence base for the machine view (T066) and the big-load finder study (T065): the
only data here with a meter on every machine *and* on the main terminal. It is one plant over
three months, so results on it are evidence, not a guarantee for other factories.

Zenodo publishes each file's size and MD5. The SHA-256 values below were computed from downloads
whose size and MD5 matched Zenodo's; `fetch` and `verify` check all three.

`prepare` streams each meter's CSV out of the archive (only the timestamp, the three power
columns and the two energy counters are read) and writes the total active, reactive and apparent
power on a regular grid. The meters sample about every 5.5 seconds, not on a clock: a 5-second
grid would leave about 9 % of its bins empty, so the finest grid is **10 seconds**. Coarser grids
average the 10-second bins and keep the share of them present (`coverage`). Nothing is filled in.

    uv run python -m wattwise.data.hipe list
    uv run python -m wattwise.data.hipe fetch              # one week, 109 MB
    uv run python -m wattwise.data.hipe fetch --full       # also the three months, 1.33 GB
    uv run python -m wattwise.data.hipe verify
    uv run python -m wattwise.data.hipe prepare --archive week
    uv run python -m wattwise.data.hipe prepare --archive full
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from wattwise.data.acquisition import (
    CHUNK_BYTES,
    AcquisitionError,
    FileResult,
    FileStatus,
    Opener,
    Progress,
    RemoteFile,
    ensure,
    verify,
)
from wattwise.data.contracts import BUILDINGS, READINGS
from wattwise.data.validation import to_canonical

ZENODO_RECORD: Final = "14054902"
DOI: Final = "10.5281/zenodo.14054902"
VERSION: Final = "1.0.1"
LICENCE: Final = "CC-BY-4.0"
CITATION: Final = (
    "Bischof, S., Trittenbach, H., Vollmer, M., Werle, D., Blank, T., Böhm, K. (2018). HIPE - an "
    "Energy-Status-Data Set from Industrial Production. Proceedings of ACM e-Energy (e-Energy "
    "'18), 599-603. https://doi.org/10.1145/3208903.3210278. Data: version 1.0.1, "
    "https://doi.org/10.5281/zenodo.14054902, licensed under CC BY 4.0."
)
SITE_TIMEZONE: Final = "Europe/Berlin"
MAIN: Final = "MainTerminal"
#: The finest regular grid: the meters sample about every 5.5 s (see the module docstring).
GRID_SECONDS: Final = 10
RESOLUTIONS: Final = (("10s", 10), ("1min", 60), ("15min", 900), ("1h", 3600))
#: A gap is a pause between two samples longer than this.
GAP_SECONDS: Final = 60.0
#: The meters' energy counters are 16-bit whole kWh: the main terminal's rolls over from 65,535
#: to 0 (on 2017-10-14). A drop from near the top to near zero is a rollover, not a reset.
COUNTER_WRAP: Final = 65_536.0
#: The integrated power and the counters "disagree" when they differ by more than this factor
#: on a meter whose counters moved at least COUNTER_MIN_KWH (smaller counts are too coarse).
DISAGREEMENT_FACTOR: Final = 1.5
COUNTER_MIN_KWH: Final = 20.0
DEFAULT_RAW: Final = Path("../data/raw/hipe")
DEFAULT_OUTPUT: Final = Path("../data/processed/hipe")
DEFAULT_MANIFEST: Final = Path("../data/manifests/hipe.json")
_MEMBER = re.compile(r"^(?P<meter>[A-Za-z0-9]+)_PhaseCount_(?P<phases>[23])_geq_[^/]*\.csv$")
_SOURCE_COLUMNS: Final = ("SensorDateTime", "P_kW", "Q_kvar", "S_kVA", "E_PP_kWh", "E_PN_kWh")


@dataclass(frozen=True)
class Archive:
    """One published archive: the file to fetch and Zenodo's own MD5 for it."""

    remote: RemoteFile
    md5: str
    period: str


def _archive(
    key: str, name: str, size: int, md5: str, sha256: str, period: str, description: str
) -> Archive:
    url = f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/{name}/content"
    return Archive(RemoteFile(key, url, name, size, sha256, description), md5, period)


ARCHIVES: Final = (
    _archive(
        "week",
        "hipe_cleaned_v1.0.1_geq_2017-10-23_lt_2017-10-30.zip",
        109_297_827,
        "535683e5c98f534e5b6d6f286dbe6993",
        "a04344f7edf0593d9c35db68e606babfd77d28522ec0dc37ee081516836bbe2b",
        "2017-10-23 to 2017-10-30 (local time)",
        "One week of all eleven meters",
    ),
    _archive(
        "full",
        "hipe_cleaned_v1.0.1_geq_2017-10-01_lt_2018-01-01.zip",
        1_329_538_336,
        "9de58f4a2b2df3efb0ba29af84b55155",
        "37ef3e733ff3de2fb13525421d9524b1e9d81c88ac0e0c22497634a964384716",
        "2017-10-01 to 2018-01-01 (local time)",
        "Three months of all eleven meters",
    ),
)
ARCHIVES_BY_KEY: Final = {a.remote.key: a for a in ARCHIVES}


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------


def md5_of(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)  # Zenodo's published checksum, not a defence
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _check_md5(archive: Archive, path: Path) -> None:
    found = md5_of(path)
    if found != archive.md5:
        raise AcquisitionError(
            f"{archive.remote.key}: {path} has MD5 {found}, but Zenodo publishes {archive.md5}. "
            "The pinned SHA-256 and Zenodo's checksum disagree: do not use this file."
        )


def fetch(
    keys: Sequence[str],
    destination: Path,
    manifest: Path,
    *,
    opener: Opener | None = None,
    now: datetime | None = None,
    progress: Progress | None = None,
) -> list[FileResult]:
    """Make sure the named archives are present and match size, SHA-256 and Zenodo's MD5."""
    results = []
    for key in keys:
        archive = ARCHIVES_BY_KEY[key]
        result = ensure(archive.remote, destination, opener=opener, progress=progress)
        _check_md5(archive, result.path)
        results.append(result)
    write_manifest(manifest, results, now or datetime.now(UTC))
    return results


def verify_local(destination: Path) -> dict[str, FileResult | None]:
    """Each archive's verified local copy, or None if it is absent or does not match."""
    found: dict[str, FileResult | None] = {}
    for archive in ARCHIVES:
        result = verify(archive.remote, destination)
        if result is not None:
            _check_md5(archive, result.path)
        found[archive.remote.key] = result
    return found


def write_manifest(path: Path, results: Sequence[FileResult], now: datetime) -> None:
    """Record provenance. Download dates are kept for files that were only verified again."""
    previous: dict[str, Any] = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    files: dict[str, Any] = dict(previous)
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for result in results:
        archive = ARCHIVES_BY_KEY[result.key]
        earlier = previous.get(archive.remote.local_path)
        obtained = (
            earlier.get("obtained_at")
            if isinstance(earlier, dict) and result.status is FileStatus.VERIFIED
            else None
        )
        files[archive.remote.local_path] = {
            "url": archive.remote.url,
            "local_path": f"data/raw/hipe/{archive.remote.local_path}",
            "period": archive.period,
            "bytes": result.size,
            "sha256": result.sha256,
            "zenodo_md5": archive.md5,
            "obtained_at": obtained or stamp,
            "last_verified_at": stamp,
        }
    manifest = {
        "dataset": "High-resolution Industrial Production Energy (HIPE)",
        "doi": DOI,
        "version": VERSION,
        "licence": "CC BY 4.0",
        "citation": CITATION,
        "checksums": "Zenodo publishes size and MD5; SHA-256 was computed from a download "
        "that matched both.",
        "documentation": "docs/DATASETS.md",
        "files": dict(sorted(files.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# Reading and gridding
# ---------------------------------------------------------------------------


def meter_members(names: Sequence[str]) -> dict[str, tuple[str, int]]:
    """Meter name -> (archive member, phase count), from the authors' file names."""
    found: dict[str, tuple[str, int]] = {}
    for name in names:
        match = _MEMBER.match(name)
        if match:
            found[match["meter"]] = (name, int(match["phases"]))
    return found


def read_samples(handle: zipfile.ZipFile, member: str) -> pd.DataFrame:
    """One meter's samples, oldest first: `timestamp` (UTC), `p_kw`, `q_kvar`, `s_kva`, and the
    meter's own energy counters `forward_kwh` and `reverse_kwh` (one machine's counter runs in the
    reverse direction). Only these columns are parsed, in blocks, so a 3 GB file needs little
    memory. Repeated timestamps keep their first sample."""
    options = pacsv.ConvertOptions(
        include_columns=list(_SOURCE_COLUMNS), column_types={"SensorDateTime": pa.string()}
    )
    with handle.open(member) as stream:
        reader = pacsv.open_csv(
            stream, read_options=pacsv.ReadOptions(block_size=32 << 20), convert_options=options
        )
        table = reader.read_all()
    raw = table.to_pandas()
    samples = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(raw["SensorDateTime"], format="ISO8601", utc=True),
            "p_kw": raw["P_kW"].to_numpy(dtype=float),
            "q_kvar": raw["Q_kvar"].to_numpy(dtype=float),
            "s_kva": raw["S_kVA"].to_numpy(dtype=float),
            "forward_kwh": raw["E_PP_kWh"].to_numpy(dtype=float),
            "reverse_kwh": raw["E_PN_kWh"].to_numpy(dtype=float),
        }
    )
    samples = samples.sort_values("timestamp", kind="stable")
    return samples.drop_duplicates("timestamp", keep="first").reset_index(drop=True)


def to_grid(samples: pd.DataFrame, seconds: int = GRID_SECONDS) -> pd.DataFrame:
    """The mean of the samples in each `seconds` bin (UTC bin start) and how many there were.
    A bin without a sample is absent, never filled."""
    bins = samples["timestamp"].dt.floor(f"{seconds}s")
    grouped = samples.groupby(bins, sort=True)
    grid = grouped[["p_kw", "q_kvar", "s_kva"]].mean()
    grid["samples"] = grouped.size().astype("int32")
    grid.index.name = "timestamp"
    return grid.reset_index()


def coarsen(grid: pd.DataFrame, seconds: int, base_seconds: int = GRID_SECONDS) -> pd.DataFrame:
    """The mean of the fine bins inside each `seconds` bin, with `coverage`: the share of the
    fine bins that were present."""
    if seconds % base_seconds:
        raise ValueError(f"{seconds} s is not a multiple of the {base_seconds} s grid")
    bins = grid["timestamp"].dt.floor(f"{seconds}s")
    grouped = grid.groupby(bins, sort=True)
    coarse = grouped[["p_kw", "q_kvar", "s_kva"]].mean()
    coarse["coverage"] = (grouped.size() / (seconds // base_seconds)).astype("float32")
    coarse.index.name = "timestamp"
    return coarse.reset_index()


def counter_kwh(values: npt.NDArray[np.float64]) -> tuple[float, int, int]:
    """Energy counted by one counter over the samples: (kWh, rollovers, resets). Increments are
    added; a drop from near the top of the 16-bit range to near zero is a rollover (the counter
    went on counting); any other drop is a reset, and that step adds nothing."""
    values = values.astype(float)
    steps = np.diff(values)
    before, after = values[:-1], values[1:]
    rolled = (steps < 0) & (before >= COUNTER_WRAP - 100) & (after < 100)
    reset = (steps < 0) & ~rolled
    total = float(steps[steps > 0].sum() + (steps[rolled] + COUNTER_WRAP).sum())
    return total, int(rolled.sum()), int(reset.sum())


def grid_kwh(grid: pd.DataFrame, seconds: int = GRID_SECONDS) -> float:
    """Energy over the bins that are present (absent bins add nothing)."""
    return float(grid["p_kw"].sum() * seconds / 3600)


def meter_stats(samples: pd.DataFrame, grid: pd.DataFrame, phases: int) -> dict[str, Any]:
    stamps = samples["timestamp"]
    steps = stamps.diff().dt.total_seconds().dropna()
    expected = int(
        (
            stamps.iloc[-1].floor(f"{GRID_SECONDS}s") - stamps.iloc[0].floor(f"{GRID_SECONDS}s")
        ).total_seconds()
    )
    expected = expected // GRID_SECONDS + 1
    forward = counter_kwh(samples["forward_kwh"].to_numpy(dtype=float))
    reverse = counter_kwh(samples["reverse_kwh"].to_numpy(dtype=float))
    counted = forward[0] + reverse[0]
    energy = grid_kwh(grid)
    disagrees = counted >= COUNTER_MIN_KWH and not (
        1 / DISAGREEMENT_FACTOR <= energy / counted <= DISAGREEMENT_FACTOR
    )
    return {
        "phases": phases,
        "samples": len(samples),
        "first_utc": stamps.iloc[0].isoformat(),
        "last_utc": stamps.iloc[-1].isoformat(),
        "median_interval_s": round(float(steps.median()), 3),
        "grid_bins": len(grid),
        "grid_coverage": round(len(grid) / expected, 5),
        "gaps_over_60s": int((steps > GAP_SECONDS).sum()),
        "longest_gap_s": round(float(steps.max()), 1),
        "mean_kw": round(float(grid["p_kw"].mean()), 4),
        "max_kw": round(float(grid["p_kw"].max()), 3),
        "energy_kwh": round(energy, 2),
        "counter_kwh": round(counted, 2),
        "counter_rollovers": forward[1] + reverse[1],
        "counter_resets": forward[2] + reverse[2],
        "counter_disagrees": bool(disagrees),
    }


def plant_stats(grids: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """How much of the main terminal the metered machines explain, over the 10-second bins in
    which every meter has a value. The rest is plant load with no meter of its own."""
    power = pd.concat(
        {meter: grid.set_index("timestamp")["p_kw"] for meter, grid in grids.items()},
        axis=1,
        join="inner",
    )
    machines = [m for m in power.columns if m != MAIN]
    main = power[MAIN].to_numpy(dtype=float)
    metered = power[machines].to_numpy(dtype=float).sum(axis=1)
    rest = main - metered
    hours = GRID_SECONDS / 3600
    main_kwh = float(main.sum() * hours)
    shares = {
        m: round(float(power[m].sum() * hours / main_kwh), 4) if main_kwh else None
        for m in machines
    }
    return {
        "common_bins": len(power),
        "main_kwh": round(main_kwh, 2),
        "machines_kwh": round(float(metered.sum() * hours), 2),
        "explained_share": round(float(metered.sum() / main.sum()), 4) if main.sum() else None,
        "machine_shares_of_main": dict(sorted(shares.items(), key=lambda kv: -(kv[1] or 0))),
        "unmetered_kw": {
            "mean": round(float(rest.mean()), 3),
            "p05": round(float(np.quantile(rest, 0.05)), 3),
            "median": round(float(np.median(rest)), 3),
            "p95": round(float(np.quantile(rest, 0.95)), 3),
            "share_of_bins_below_zero": round(float((rest < 0).mean()), 5),
        },
    }


# ---------------------------------------------------------------------------
# Preparation
# ---------------------------------------------------------------------------


def _schema(last: str) -> pa.Schema:
    kind = pa.int32() if last == "samples" else pa.float32()
    return pa.schema(
        [
            ("meter_id", pa.string()),
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("p_kw", pa.float64()),
            ("q_kvar", pa.float64()),
            ("s_kva", pa.float64()),
            (last, kind),
        ]
    )


def _table(meter: str, frame: pd.DataFrame, last: str) -> pa.Table:
    return pa.table(
        {
            "meter_id": pa.array([meter] * len(frame), type=pa.string()),
            "timestamp": pa.array(frame["timestamp"], type=pa.timestamp("us", tz="UTC")),
            "p_kw": frame["p_kw"].to_numpy(dtype=float),
            "q_kvar": frame["q_kvar"].to_numpy(dtype=float),
            "s_kva": frame["s_kva"].to_numpy(dtype=float),
            last: frame[last].to_numpy(),
        },
        schema=_schema(last),
    )


def prepare(archive: Path, output: Path) -> dict[str, Any]:
    """Write `power_10s.parquet`, `power_1min.parquet`, `power_15min.parquet` and
    `power_1h.parquet` (one row per meter and bin, meters in name order), `summary.json` and
    `quality.md`, and return the summary. One meter is held in memory at a time."""
    handle = zipfile.ZipFile(archive)
    members = meter_members(handle.namelist())
    if MAIN not in members:
        raise ValueError(f"{archive} has no {MAIN} file: it is not a HIPE archive")
    output.mkdir(parents=True, exist_ok=True)
    writers = {
        name: pq.ParquetWriter(
            output / f"power_{name}.parquet", _schema("samples" if seconds == 10 else "coverage")
        )
        for name, seconds in RESOLUTIONS
    }
    meters: dict[str, Any] = {}
    grids: dict[str, pd.DataFrame] = {}
    try:
        for meter in sorted(members):
            member, phases = members[meter]
            samples = read_samples(handle, member)
            grid = to_grid(samples)
            meters[meter] = meter_stats(samples, grid, phases)
            grids[meter] = grid[["timestamp", "p_kw"]]
            for name, seconds in RESOLUTIONS:
                if seconds == GRID_SECONDS:
                    writers[name].write_table(_table(meter, grid, "samples"))
                else:
                    writers[name].write_table(_table(meter, coarsen(grid, seconds), "coverage"))
    finally:
        for writer in writers.values():
            writer.close()
    summary = {
        "dataset": "HIPE",
        "version": VERSION,
        "licence": "CC BY 4.0",
        "citation": CITATION,
        "archive": archive.name,
        "grid_seconds": GRID_SECONDS,
        "resolutions": [name for name, _ in RESOLUTIONS],
        "meters": meters,
        "plant": plant_stats(grids),
    }
    text = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    (output / "summary.json").write_bytes(text.encode("utf-8"))
    (output / "quality.md").write_bytes(to_markdown(summary).encode("utf-8"))
    return summary


def to_markdown(summary: dict[str, Any]) -> str:
    plant = summary["plant"]
    rest = plant["unmetered_kw"]
    lines = [
        "# HIPE preparation: quality report",
        "",
        f"**Real data.** {summary['citation']}",
        "",
        f"- Archive: `{summary['archive']}`",
        f"- Grid: {summary['grid_seconds']} seconds (the meters sample about every 5.5 s); "
        "absent bins are never filled",
        "",
        "| Meter | Phases | Samples | Median interval (s) | 10 s bins present | Gaps over 60 s "
        "| Longest gap (s) | Mean kW | Max kW | Energy (kWh) | Counters (kWh) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for meter, m in summary["meters"].items():
        lines.append(
            f"| {meter} | {m['phases']} | {m['samples']:,} | {m['median_interval_s']} | "
            f"{m['grid_coverage']:.2%} | {m['gaps_over_60s']} | {m['longest_gap_s']} | "
            f"{m['mean_kw']} | {m['max_kw']} | {m['energy_kwh']:,} | {m['counter_kwh']:,}"
            f"{' (disagrees)' if m['counter_disagrees'] else ''} |"
        )
    lines += [
        "",
        "Energy is the sum of the 10-second means over the bins present. Counters is what the "
        "meter's own whole-kWh energy counters added up over the same period (both directions, "
        "rollovers of the 16-bit counter counted). Where they differ by more than a factor of "
        f"{DISAGREEMENT_FACTOR} on at least {COUNTER_MIN_KWH:g} kWh, the row says *disagrees*: "
        "the cause is unknown, so results for that machine carry that uncertainty.",
        "",
        "## How much of the main terminal the ten machines explain",
        "",
        f"Over the {plant['common_bins']:,} ten-second bins in which all eleven meters have a "
        "value:",
        "",
        f"- Main terminal: {plant['main_kwh']:,} kWh",
        f"- The ten machines together: {plant['machines_kwh']:,} kWh, "
        f"**{plant['explained_share']:.1%} of the main terminal**",
        f"- Unmetered load (main minus machines): mean {rest['mean']} kW, median "
        f"{rest['median']} kW, 5th to 95th percentile {rest['p05']} to {rest['p95']} kW; below "
        f"zero in {rest['share_of_bins_below_zero']:.2%} of bins",
        "",
        "| Machine | Share of the main terminal's energy |",
        "|---|---|",
        *(
            f"| {meter} | {share:.1%} |"
            for meter, share in plant["machine_shares_of_main"].items()
            if share is not None
        ),
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Canonical tables, for loading into WattWise (T066)
# ---------------------------------------------------------------------------

BUILDING_ID: Final = "hipe-plant"
SITE_ID: Final = "hipe"
#: An hour becomes a reading only if this share of its 10-second bins is present; otherwise it
#: is a missing reading, never a filled one.
HOUR_COVERAGE: Final = 0.9


def canonical(prepared: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(buildings, readings) in the canonical form, from `power_1h.parquet`: one building, and
    each meter's hourly energy in kWh (mean kW over the hour times one hour), labelled with the
    meter's HIPE name."""
    hourly = pd.read_parquet(prepared / "power_1h.parquet")
    value = hourly["p_kw"].astype(float).where(hourly["coverage"] >= HOUR_COVERAGE)
    readings = pd.DataFrame(
        {
            "timestamp": hourly["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "meter_id": "hipe:" + hourly["meter_id"].astype(str),
            "building_id": BUILDING_ID,
            "meter_type": "electricity",
            "unit": "kWh",
            "value": value,
        }
    )
    buildings = pd.DataFrame(
        {
            "building_id": [BUILDING_ID],
            "site_id": [SITE_ID],
            "timezone": [SITE_TIMEZONE],
            "primary_use": ["Manufacturing (power electronics)"],
        }
    )
    return buildings, readings


def write_canonical(prepared: Path) -> Path:
    """Write the canonical tables next to the prepared data, for `wattwise.db.load`."""
    buildings, readings = canonical(prepared)
    folder = prepared / "canonical"
    folder.mkdir(parents=True, exist_ok=True)
    to_canonical(buildings, BUILDINGS).to_parquet(folder / "buildings.parquet", index=False)
    to_canonical(readings, READINGS).to_parquet(folder / "readings.parquet", index=False)
    return folder


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.hipe",
        description="Fetch, verify and prepare the HIPE factory data set (CC BY 4.0).",
    )
    parser.add_argument("command", choices=["list", "fetch", "verify", "prepare", "canonical"])
    parser.add_argument("--full", action="store_true", help="fetch the three-month archive too")
    parser.add_argument("--archive", choices=sorted(ARCHIVES_BY_KEY), default="week")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            for archive in ARCHIVES:
                r = archive.remote
                print(f"{r.key}: {r.local_path} ({r.size:,} bytes), {archive.period}")
            return 0
        if args.command == "fetch":
            keys = ["week", "full"] if args.full else ["week"]
            for result in fetch(keys, args.raw, args.manifest):
                print(f"{result.key}: {result.status.value} {result.path}")
            return 0
        if args.command == "verify":
            found = verify_local(args.raw)
            for key, local in found.items():
                print(f"{key}: {'verified' if local else 'absent or not matching'}")
            return 0 if all(found.values()) else 1
        if args.command == "canonical":
            prepared = args.output / args.archive
            if not (prepared / "power_1h.parquet").exists():
                print(
                    f"error: {prepared} has no prepared data. Run: uv run python -m "
                    f"wattwise.data.hipe prepare --archive {args.archive}",
                    file=sys.stderr,
                )
                return 1
            print(write_canonical(prepared))
            return 0
        path = args.raw / ARCHIVES_BY_KEY[args.archive].remote.local_path
        if not path.exists():
            print(
                f"error: {path} is missing. Run: uv run python -m wattwise.data.hipe fetch"
                + (" --full" if args.archive == "full" else ""),
                file=sys.stderr,
            )
            return 1
        summary = prepare(path, args.output / args.archive)
        print(to_markdown(summary))
    except (AcquisitionError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
