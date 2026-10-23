"""Building Data Genome Project 2 (BDG2): pinned source definition and acquisition CLI.

The files are stored in Git LFS, so they are fetched from GitHub's LFS media endpoint at a pinned
commit and verified against the size and SHA-256 recorded in the repository's LFS pointers. See
docs/DATASETS.md for provenance, licence evidence and the data conventions (local-time
timestamps, units) that the BDG2 adapter (T009) must handle.

    uv run python -m wattwise.data.bdg2 list
    uv run python -m wattwise.data.bdg2 fetch            # explicit download, ~369 MB
    uv run python -m wattwise.data.bdg2 verify           # offline check of local copies
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from wattwise.data.acquisition import (
    AcquisitionError,
    FileResult,
    FileStatus,
    Opener,
    Progress,
    RemoteFile,
    ensure,
    verify,
)

REPOSITORY: Final = "buds-lab/building-data-genome-project-2"
#: The last commit that changed any data file (2020-06-24, "Correct weather.csv"). Its data files
#: are byte-identical to the repository's current master; the v1.0 tag predates two corrections.
COMMIT: Final = "753598e0a19400af950b1513e1daeb680658c1fd"
CITATION: Final = (
    "Miller, C., Kathirgamanathan, A., Picchetti, B. et al. The Building Data Genome Project 2, "
    "energy meter data from the ASHRAE Great Energy Predictor III competition. Sci Data 7, 368 "
    "(2020). https://doi.org/10.1038/s41597-020-00712-x"
)
LICENCE_STATUS: Final = (
    "Conflicting statements across sources; handled conservatively. No raw or derived BDG2 data "
    "is redistributed. See docs/DATASETS.md."
)
LICENCE_SOURCES: Final = (
    {"source": "GitHub LICENSE at the pinned commit (2020-06-24)", "licence": "MIT"},
    {"source": "GitHub LICENSE on master since 2023-10-14", "licence": "CC-BY-SA-4.0"},
    {"source": "Zenodo v1.0 deposit 10.5281/zenodo.3887306 (2020-06-10)", "licence": "CC-BY-4.0"},
    {"source": "ORNL Open Energy Data Portal record", "licence": "CC-BY-4.0"},
)

DEFAULT_DESTINATION: Final = Path("../data/raw/bdg2")
DEFAULT_MANIFEST: Final = Path("../data/manifests/bdg2.json")


def _media_url(path: str) -> str:
    return f"https://media.githubusercontent.com/media/{REPOSITORY}/{COMMIT}/{path}"


#: Sizes and SHA-256 values are copied from the Git LFS pointer files at COMMIT.
FILES: Final = (
    RemoteFile(
        key="metadata",
        url=_media_url("data/metadata/metadata.csv"),
        local_path="metadata/metadata.csv",
        size=272_024,
        sha256="992d0b29f24f96ad4332bc4dbb534b7bdd7dd2689aad093f94e93068ecddca02",
        description="Building metadata: site, time zone, floor area, primary use.",
    ),
    RemoteFile(
        key="weather",
        url=_media_url("data/weather/weather.csv"),
        local_path="weather/weather.csv",
        size=19_457_782,
        sha256="a8189f1c6acdf3b9933a9e6354b8e7c1278cd56a7075929623a17565d44f04bd",
        description="Hourly site weather (local time, after the 2020-06-24 correction).",
    ),
    RemoteFile(
        key="electricity_raw",
        url=_media_url("data/meters/raw/electricity.csv"),
        local_path="meters/raw/electricity.csv",
        size=174_239_039,
        sha256="039d909d8981e2d69eaeb366144e6ab7e84fa5e7e216aee42bddd95384a66418",
        description="Hourly electricity, kWh, as published (real anomalies retained).",
    ),
    RemoteFile(
        key="electricity_cleaned",
        url=_media_url("data/meters/cleaned/electricity_cleaned.csv"),
        local_path="meters/cleaned/electricity_cleaned.csv",
        size=174_977_911,
        sha256="b6ffc9b4dfcefe5c753594730a08ae822b0d50fec6815abb8f185591e6c630a3",
        description="Hourly electricity, kWh, with outliers and zero readings removed by BDG2.",
    ),
)

FILES_BY_KEY: Final = {remote.key: remote for remote in FILES}


def select(keys: Sequence[str] | None) -> tuple[RemoteFile, ...]:
    if not keys:
        return FILES
    unknown = sorted(set(keys) - set(FILES_BY_KEY))
    if unknown:
        raise AcquisitionError(
            f"Unknown BDG2 file(s): {', '.join(unknown)}. Choose from: {', '.join(FILES_BY_KEY)}."
        )
    return tuple(FILES_BY_KEY[key] for key in dict.fromkeys(keys))


def fetch(
    destination: Path,
    manifest: Path,
    keys: Sequence[str] | None = None,
    *,
    force: bool = False,
    opener: Opener | None = None,
    now: datetime | None = None,
    log: bool = False,
) -> list[FileResult]:
    """Download (or verify) the selected files, then record them in the manifest."""
    results = []
    for remote in select(keys):
        if log:
            print(f"{remote.key}: {remote.size / 1e6:.1f} MB -> {destination}", flush=True)
        result = ensure(
            remote,
            destination,
            force=force,
            opener=opener,
            progress=_progress_printer(remote.key) if log else None,
        )
        results.append(result)
        if log:
            print(f"{remote.key}: {result.status.value} (sha256 {result.sha256})", flush=True)
    write_manifest(manifest, results, now or datetime.now(UTC))
    return results


def write_manifest(path: Path, results: Sequence[FileResult], now: datetime) -> None:
    """Record provenance. Existing download dates are kept for files that were only verified."""
    previous: dict[str, object] = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    files: dict[str, object] = dict(previous)
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for result in results:
        remote = FILES_BY_KEY[result.key]
        earlier = previous.get(result.key)
        downloaded_at = (
            earlier.get("downloaded_at")
            if isinstance(earlier, dict) and result.status is FileStatus.VERIFIED
            else None
        )
        files[result.key] = {
            "url": remote.url,
            "local_path": remote.local_path,
            "bytes": result.size,
            "sha256": result.sha256,
            "downloaded_at": downloaded_at or stamp,
            "last_verified_at": stamp,
        }
    manifest = {
        "dataset": "Building Data Genome Project 2 (BDG2)",
        "repository": f"https://github.com/{REPOSITORY}",
        "commit": COMMIT,
        "citation": CITATION,
        "licence_status": LICENCE_STATUS,
        "licence_sources": list(LICENCE_SOURCES),
        "documentation": "docs/DATASETS.md",
        "files": dict(sorted(files.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))


def _progress_printer(key: str) -> Progress:
    state = {"next": 0.1}

    def report(received: int, total: int) -> None:
        if received / total >= state["next"] or received == total:
            print(f"  {key}: {received / 1e6:7.1f} / {total / 1e6:.1f} MB", flush=True)
            state["next"] = min(1.0, received / total + 0.1)

    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.bdg2",
        description="List, download or verify the pinned BDG2 files (see docs/DATASETS.md).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show the files, sizes and checksums; no network")
    for name, text in (
        ("fetch", "download missing files and verify all selected files"),
        ("verify", "check local copies against the pinned checksums; no network"),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--dest", type=Path, default=DEFAULT_DESTINATION)
        sub.add_argument("--only", nargs="+", metavar="KEY", help="subset of file keys")
        if name == "fetch":
            sub.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
            sub.add_argument("--force", action="store_true", help="replace mismatching files")
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            for remote in FILES:
                print(f"{remote.key:20s} {remote.size / 1e6:8.1f} MB  {remote.sha256}")
                print(f"{'':20s} {remote.description}")
            total = sum(remote.size for remote in FILES) / 1e6
            print(f"{'total':20s} {total:8.1f} MB   source {REPOSITORY}@{COMMIT[:10]}")
            return 0
        if args.command == "verify":
            missing = []
            for remote in select(args.only):
                result = verify(remote, args.dest)
                if result is None:
                    missing.append(remote.key)
                    print(f"{remote.key}: missing")
                else:
                    print(f"{remote.key}: verified")
            if missing:
                print("Download with: uv run python -m wattwise.data.bdg2 fetch", file=sys.stderr)
                return 1
            return 0
        fetch(args.dest, args.manifest, args.only, force=args.force, log=True)
        return 0
    except AcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
