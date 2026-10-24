"""LEAD 1.0 anomaly labels for BDG2 meters: pinned acquisition and join (docs/DATASETS.md, D022).

LEAD 1.0 (Gulati & Arjunan, ACM e-Energy 2022) holds human anomaly labels for the 2016 hourly
electricity of 200 ASHRAE GEPIII buildings, which are BDG2 buildings. Its repository states no
licence, and the Kaggle rules forbid redistribution. The owner therefore decided (D022) that it is
used locally for evaluation only: never committed, never published, always cited.

Only LEAD's labels are used, never its readings, because some keep GEPIII's original units. Each
label is joined to its BDG2 meter through `building_id_kaggle` and the local timestamp, which LEAD
shares with BDG2 (T007b). It is then converted to UTC with the site's audited clock. A row is
excluded, with a reason, when:
- the building has no BDG2 match
- its site clock is undetermined
- LEAD blanked the reading (zeros and constant runs were not annotated)
- its local hour does not convert to UTC (daylight saving)

    uv run python -m wattwise.data.lead fetch      # ~10 MB into ../data/raw/lead
    uv run python -m wattwise.data.lead prepare    # labels into ../data/processed/lead
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from wattwise.data.acquisition import (
    AcquisitionError,
    FileResult,
    FileStatus,
    Opener,
    RemoteFile,
    ensure,
    sha256_of,
    verify,
)
from wattwise.data.bdg2 import COMMIT as BDG2_COMMIT
from wattwise.data.bdg2 import DEFAULT_DESTINATION as BDG2_DESTINATION
from wattwise.data.bdg2 import FILES_BY_KEY as BDG2_FILES
from wattwise.data.bdg2_audit import ELECTRICITY_CLOCKS, TIMESTAMP_FORMAT
from wattwise.data.bdg2_sites import CORRECTIONS, Correction, apply_corrections
from wattwise.data.contracts import MeterType
from wattwise.data.time_convention import Clock, to_utc

REPOSITORY: Final = "samy101/lead-dataset"
#: The only commit that added or changed the data file (2022-06-28, "Add files via upload").
COMMIT: Final = "80e1368228413d8550690ffbce67118bc4f6ea9d"
#: GitHub's git object id for the file at COMMIT. The download matched it, independently of the
#: SHA-256 pinned below.
GIT_BLOB_SHA1: Final = "867c4af643b887d10662a3739dd3dbe52846a054"
CITATION: Final = (
    "Gulati, M., Arjunan, P. LEAD1.0: A Large-scale Annotated Dataset for Energy Anomaly "
    "Detection in Commercial Buildings. In Proc. ACM e-Energy '22, 485-488 (2022). "
    "https://doi.org/10.1145/3538637.3539761"
)
LICENCE_STATUS: Final = (
    "No licence stated in the repository; the Kaggle competition rules forbid redistribution. "
    "Owner decision (D022): local evaluation only, never committed or redistributed, cited."
)
PIPELINE_VERSION: Final = "1"
DEFAULT_DESTINATION: Final = Path("../data/raw/lead")
DEFAULT_MANIFEST: Final = Path("../data/manifests/lead.json")
DEFAULT_OUTPUT: Final = Path("../data/processed/lead")
MEMBER: Final = "lead1.0-small.csv"
COLUMNS: Final = ("building_id", "timestamp", "meter_reading", "anomaly")
#: LEAD's reading "agrees" with BDG2 raw within this relative and absolute tolerance.
AGREEMENT_TOLERANCE: Final = 1e-3

FILE: Final = RemoteFile(
    key="lead_small",
    url=f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/data/lead1.0-small.zip",
    local_path="lead1.0-small.zip",
    size=10_027_589,
    sha256="b0e34c66c0c4ce780b7bb19b199d33e19210675f16be102a5ac32d6b22e39d8f",
    description="LEAD 1.0 public subset: 200 buildings, 2016, hourly electricity, 0/1 labels.",
)
OUTPUT_FILES: Final = ("labels.parquet", "exclusions.csv", "report.md")


class Reason(StrEnum):
    NO_BDG2_BUILDING = "no_bdg2_building"
    UNDETERMINED_CLOCK = "undetermined_clock"
    NOT_ANNOTATED = "not_annotated"  # LEAD blanked the reading, so annotators never judged it
    UNCONVERTIBLE_HOUR = "unconvertible_hour"  # a daylight-saving hour with no single UTC time


@dataclass(frozen=True)
class LabelSet:
    labels: pd.DataFrame
    exclusions: pd.DataFrame
    stats: dict[str, object] = field(default_factory=dict)
    corrections: tuple[Correction, ...] = ()


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------


def fetch(
    destination: Path,
    manifest: Path,
    *,
    force: bool = False,
    opener: Opener | None = None,
    now: datetime | None = None,
) -> FileResult:
    """Download (or verify) the pinned file, then record it in the manifest."""
    result = ensure(FILE, destination, force=force, opener=opener)
    write_manifest(manifest, result, now or datetime.now(UTC))
    return result


def write_manifest(path: Path, result: FileResult, now: datetime) -> None:
    """Record provenance. The download date is kept when the file was only verified."""
    previous: dict[str, object] = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    earlier = previous.get(result.key)
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    downloaded_at = (
        earlier.get("downloaded_at")
        if isinstance(earlier, dict) and result.status is FileStatus.VERIFIED
        else None
    )
    manifest = {
        "dataset": "LEAD 1.0 (public subset of the Large-scale Energy Anomaly Detection dataset)",
        "repository": f"https://github.com/{REPOSITORY}",
        "commit": COMMIT,
        "git_blob_sha1": GIT_BLOB_SHA1,
        "citation": CITATION,
        "licence_status": LICENCE_STATUS,
        "documentation": "docs/DATASETS.md",
        "files": {
            result.key: {
                "url": FILE.url,
                "local_path": FILE.local_path,
                "bytes": result.size,
                "sha256": result.sha256,
                "downloaded_at": downloaded_at or stamp,
                "last_verified_at": stamp,
            }
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))


def read_lead(path: Path) -> pd.DataFrame:
    """The LEAD table with naive local timestamps, checked for its documented shape."""
    with zipfile.ZipFile(path) as archive, archive.open(MEMBER) as handle:
        frame = pd.read_csv(
            handle,
            dtype={
                "building_id": "int64",
                "timestamp": "str",
                "meter_reading": "float64",
                "anomaly": "int64",
            },
        )
    if tuple(frame.columns) != COLUMNS:
        raise ValueError(f"{path}: expected columns {COLUMNS}, found {tuple(frame.columns)}.")
    if not frame["anomaly"].isin([0, 1]).all():
        raise ValueError(f"{path}: anomaly labels must be 0 or 1.")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], format=TIMESTAMP_FORMAT)
    if frame.duplicated(["building_id", "timestamp"]).any():
        raise ValueError(f"{path}: a building has two rows for one timestamp.")
    return frame


# ---------------------------------------------------------------------------
# Joining the labels to BDG2
# ---------------------------------------------------------------------------


def prepare_labels(
    lead: pd.DataFrame,
    metadata: pd.DataFrame,
    electricity_raw: pd.DataFrame,
    electricity_cleaned: pd.DataFrame | None = None,
    clocks: Mapping[str, Clock] = ELECTRICITY_CLOCKS,
    corrections: Sequence[Correction] = CORRECTIONS,
) -> LabelSet:
    """Join LEAD labels to BDG2 meters in UTC.

    `electricity_raw` (and optionally `electricity_cleaned`) is wide, with a naive local index,
    as published. It is used only to measure agreement and the effect of BDG2's cleaning."""
    corrected, applied = apply_corrections(metadata, corrections)
    known = corrected.dropna(subset=["building_id_kaggle"])
    sites = known.set_index(known["building_id_kaggle"].astype("int64"))
    frame = lead.reset_index(drop=True)
    building = frame["building_id"].map(sites["building_id"])
    site = frame["building_id"].map(sites["site_id"])
    timezone = frame["building_id"].map(sites["timezone"])
    # A plain dict, not Series.map: pandas would store the StrEnum members as plain strings, and
    # to_utc compares clocks by identity.
    site_clocks = {str(s): clocks.get(str(s), Clock.UNDETERMINED) for s in site.dropna().unique()}
    undetermined = [s for s, c in site_clocks.items() if c is Clock.UNDETERMINED]

    reason = np.full(len(frame), "", dtype=object)
    reason[building.isna().to_numpy()] = Reason.NO_BDG2_BUILDING.value
    pending = reason == ""
    reason[pending & site.isin(undetermined).to_numpy()] = Reason.UNDETERMINED_CLOCK.value
    pending = reason == ""
    reason[pending & frame["meter_reading"].isna().to_numpy()] = Reason.NOT_ANNOTATED.value

    utc = np.full(len(frame), np.datetime64("NaT", "us"), dtype="datetime64[us]")
    pending = reason == ""
    for site_id in sorted(set(site[pending].astype(str))):
        rows = pending & (site == site_id).to_numpy()
        converted = to_utc(
            pd.DatetimeIndex(frame.loc[rows, "timestamp"]),
            str(timezone[rows].iloc[0]),
            site_clocks[site_id],
        )
        utc[rows] = converted.tz_localize(None).to_numpy(dtype="datetime64[us]")
    reason[(reason == "") & np.isnat(utc)] = Reason.UNCONVERTIBLE_HOUR.value
    keep = reason == ""

    raw_values = _lookup(electricity_raw, building[keep], frame.loc[keep, "timestamp"])
    lead_values = frame.loc[keep, "meter_reading"].to_numpy(dtype=float)
    agrees = ~np.isnan(raw_values) & np.isclose(
        lead_values, raw_values, rtol=AGREEMENT_TOLERANCE, atol=AGREEMENT_TOLERANCE
    )
    labels = pd.DataFrame(
        {
            "timestamp": utc[keep],
            "meter_id": (building[keep] + f":{MeterType.ELECTRICITY.value}").to_numpy(),
            "building_id": building[keep].to_numpy(),
            "site_id": site[keep].astype(str).to_numpy(),
            "anomaly": frame.loc[keep, "anomaly"].to_numpy(dtype="int8"),
            "lead_reading_matches_bdg2_raw": agrees,
        }
    )
    labels["timestamp"] = labels["timestamp"].dt.tz_localize("UTC")
    labels = labels.sort_values(["meter_id", "timestamp"], kind="stable").reset_index(drop=True)

    excluded = frame.loc[~keep, ["building_id"]].assign(
        bdg2_building_id=building[~keep].fillna("").to_numpy(),
        site_id=site[~keep].fillna("").astype(str).to_numpy(),
        reason=reason[~keep],
    )
    exclusions = (
        excluded.groupby(["reason", "building_id", "bdg2_building_id", "site_id"], sort=True)
        .size()
        .rename("rows")
        .reset_index()
        .rename(columns={"building_id": "building_id_kaggle"})
    )

    cleaned_missing = None
    if electricity_cleaned is not None:
        anomalous = keep & (frame["anomaly"] == 1).to_numpy()
        cleaned = _lookup(
            electricity_cleaned, building[anomalous], frame.loc[anomalous, "timestamp"]
        )
        raw_at_anomalies = _lookup(
            electricity_raw, building[anomalous], frame.loc[anomalous, "timestamp"]
        )
        present = ~np.isnan(raw_at_anomalies)
        if present.any():
            cleaned_missing = _pct(float(np.isnan(cleaned[present]).mean()))
    stats = _stats(frame, reason, labels, cleaned_missing)
    return LabelSet(labels=labels, exclusions=exclusions, stats=stats, corrections=applied)


def _lookup(wide: pd.DataFrame, buildings: pd.Series, naive: pd.Series) -> np.ndarray:
    """Values of a wide naive-indexed table at (building, local time); NaN where absent."""
    rows = pd.DatetimeIndex(wide.index).get_indexer(pd.DatetimeIndex(naive))
    columns = wide.columns.get_indexer(pd.Index(buildings.astype(str)))
    values = np.full(len(rows), np.nan)
    found = (rows >= 0) & (columns >= 0)
    values[found] = wide.to_numpy(dtype=float)[rows[found], columns[found]]
    return values


def _stats(
    frame: pd.DataFrame, reason: np.ndarray, labels: pd.DataFrame, cleaned_missing: float | None
) -> dict[str, object]:
    by_site = labels.groupby("site_id")
    anomalies = labels["anomaly"] == 1
    matches = labels["lead_reading_matches_bdg2_raw"]
    return {
        "lead_rows": len(frame),
        "lead_buildings": int(frame["building_id"].nunique()),
        "lead_anomalies": int(frame["anomaly"].sum()),
        "label_rows": len(labels),
        "label_buildings": int(labels["building_id"].nunique()),
        "label_anomalies": int(anomalies.sum()),
        "label_anomaly_rate_pct": _pct(float(anomalies.mean())) if len(labels) else None,
        "excluded_rows_by_reason": {r.value: int((reason == r.value).sum()) for r in Reason},
        "buildings_by_site": {s: int(g["building_id"].nunique()) for s, g in by_site},
        "anomaly_rate_pct_by_site": {s: _pct(float(g["anomaly"].mean())) for s, g in by_site},
        "lead_reading_agreement_pct": _pct(float(matches.mean())) if len(labels) else None,
        "lead_reading_agreement_pct_at_anomalies": (
            _pct(float(matches[anomalies].mean())) if anomalies.any() else None
        ),
        "lead_reading_agreement_pct_by_site": {
            s: _pct(float(g["lead_reading_matches_bdg2_raw"].mean())) for s, g in by_site
        },
        "anomalies_without_a_cleaned_bdg2_reading_pct": cleaned_missing,
        "period_utc": [_iso(labels["timestamp"].min()), _iso(labels["timestamp"].max())]
        if len(labels)
        else None,
    }


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def write(
    label_set: LabelSet,
    inputs: Mapping[str, Path],
    output_dir: Path,
    inputs_verified: bool,
) -> dict[str, str]:
    """Write the labels, exclusions, report and manifest. Returns name -> SHA-256."""
    output_dir.mkdir(parents=True, exist_ok=True)
    label_set.labels.to_parquet(output_dir / "labels.parquet", index=False)
    (output_dir / "exclusions.csv").write_bytes(
        label_set.exclusions.to_csv(index=False, lineterminator="\n").encode("utf-8")
    )
    (output_dir / "report.md").write_bytes(to_markdown(label_set).encode("utf-8"))
    digests = {name: sha256_of(output_dir / name) for name in OUTPUT_FILES}
    manifest = {
        "pipeline": "wattwise.data.lead",
        "pipeline_version": PIPELINE_VERSION,
        "dataset": "LEAD 1.0 public subset, joined to BDG2",
        "lead_commit": COMMIT,
        "bdg2_commit": BDG2_COMMIT,
        "citation": CITATION,
        "licence_status": LICENCE_STATUS,
        "inputs_verified_against_pinned_checksums": inputs_verified,
        "inputs": {key: sha256_of(path) for key, path in sorted(inputs.items())},
        "metadata_corrections": [c.model_dump(mode="json") for c in label_set.corrections],
        "rules": {
            "labels_only": "LEAD readings are never used; BDG2 readings are.",
            "agreement_tolerance": AGREEMENT_TOLERANCE,
            "reasons": [r.value for r in Reason],
        },
        "stats": label_set.stats,
        "outputs": {name: {"sha256": digest} for name, digest in digests.items()},
    }
    (output_dir / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    )
    digests["manifest.json"] = sha256_of(output_dir / "manifest.json")
    return digests


def to_markdown(label_set: LabelSet) -> str:
    s = label_set.stats
    period = s["period_utc"]
    excluded = s["excluded_rows_by_reason"]
    assert isinstance(excluded, dict)
    lines = [
        "# LEAD 1.0 labels joined to BDG2",
        "",
        f"Source: {CITATION}",
        "",
        f"**Use:** {LICENCE_STATUS}",
        "",
        "Labels are human annotations of unusual readings. An anomaly label is **not** confirmed "
        "waste. Only LEAD's labels are used, with BDG2's readings.",
        "",
        "| | |",
        "|---|---|",
        f"| LEAD rows / buildings / anomalies | {s['lead_rows']:,} / {s['lead_buildings']} / "
        f"{s['lead_anomalies']:,} |",
        f"| Usable label rows / buildings | {s['label_rows']:,} / {s['label_buildings']} |",
        f"| Usable anomalies | {s['label_anomalies']:,} ({s['label_anomaly_rate_pct']}%) |",
        "| Excluded rows | "
        + ", ".join(f"{reason} {count:,}" for reason, count in excluded.items())
        + " |",
        f"| LEAD reading equals BDG2 raw | {s['lead_reading_agreement_pct']}% of usable rows, "
        f"{s['lead_reading_agreement_pct_at_anomalies']}% at anomalies |",
        f"| Anomalies without a cleaned BDG2 reading | "
        f"{s['anomalies_without_a_cleaned_bdg2_reading_pct']}% |",
        f"| Period (UTC) | {' to '.join(period) if isinstance(period, list) else '-'} |",
        "",
        "| Site | Buildings | Anomaly rate | LEAD reading equals BDG2 raw |",
        "|---|---|---|---|",
    ]
    buildings = s["buildings_by_site"]
    rates = s["anomaly_rate_pct_by_site"]
    agreement = s["lead_reading_agreement_pct_by_site"]
    assert isinstance(buildings, dict) and isinstance(rates, dict) and isinstance(agreement, dict)
    for site in sorted(buildings):
        lines.append(f"| {site} | {buildings[site]} | {rates[site]}% | {agreement[site]}% |")
    return "\n".join(lines) + "\n"


def _pct(share: float) -> float:
    return round(100.0 * share, 2)


def _iso(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _read_wide(path: Path, buildings: Sequence[str]) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns
    wanted = [b for b in buildings if b in header]
    wide = pd.read_csv(path, usecols=["timestamp", *wanted])
    wide.index = pd.DatetimeIndex(pd.to_datetime(wide.pop("timestamp"), format=TIMESTAMP_FORMAT))
    return wide


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.lead",
        description="Download LEAD 1.0 and join its labels to BDG2 (local use only; D022).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("fetch", "download the pinned file, or verify it if present"),
        ("verify", "check the local copy against the pinned checksum; no network"),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--dest", type=Path, default=DEFAULT_DESTINATION)
        if name == "fetch":
            sub.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
            sub.add_argument("--force", action="store_true", help="replace a mismatching file")
    prepare = commands.add_parser("prepare", help="join the labels to BDG2 meters, in UTC")
    prepare.add_argument("--lead", type=Path, default=DEFAULT_DESTINATION)
    prepare.add_argument("--bdg2", type=Path, default=BDG2_DESTINATION)
    prepare.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    prepare.add_argument(
        "--skip-input-verification",
        action="store_true",
        help="do not check the inputs against the pinned checksums (recorded in the manifest)",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "fetch":
            result = fetch(args.dest, args.manifest, force=args.force)
            print(f"{FILE.key}: {result.status.value} (sha256 {result.sha256})")
            return 0
        if args.command == "verify":
            if verify(FILE, args.dest) is None:
                print("missing. Download with: uv run python -m wattwise.data.lead fetch")
                return 1
            print(f"{FILE.key}: verified")
            return 0
        bdg2_files = {
            key: BDG2_FILES[key] for key in ("metadata", "electricity_raw", "electricity_cleaned")
        }
        if not args.skip_input_verification:
            if verify(FILE, args.lead) is None:
                raise AcquisitionError("LEAD is missing: uv run python -m wattwise.data.lead fetch")
            for remote in bdg2_files.values():
                if verify(remote, args.bdg2) is None:
                    raise AcquisitionError(f"BDG2 {remote.key} is missing: run bdg2 fetch first.")
    except AcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    lead_path = args.lead / FILE.local_path
    paths = {key: args.bdg2 / remote.local_path for key, remote in bdg2_files.items()}
    lead = read_lead(lead_path)
    metadata = pd.read_csv(paths["metadata"])
    needed = sorted(
        metadata.loc[
            metadata["building_id_kaggle"].isin(lead["building_id"].unique()), "building_id"
        ].astype(str)
    )
    label_set = prepare_labels(
        lead,
        metadata,
        _read_wide(paths["electricity_raw"], needed),
        _read_wide(paths["electricity_cleaned"], needed),
    )
    digests = write(
        label_set,
        {"lead": lead_path, **paths},
        args.output,
        inputs_verified=not args.skip_input_verification,
    )
    print(to_markdown(label_set))
    for name, digest in digests.items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
