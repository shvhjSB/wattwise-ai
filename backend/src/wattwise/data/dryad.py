"""Pinned, checksum-verified acquisition of the two Dryad datasets (T045, for T040 and T041).

Both datasets are CC0 and published on Dryad with a SHA-256 for every file. Dryad refuses
unauthenticated downloads (the API answers 401, the website's download links 403), so there are
two ways to obtain them, and both end with the same verification:

- **With a Dryad API token** in `WATTWISE_DRYAD_TOKEN`: `fetch` downloads each file through the
  Dryad API and keeps it only if its size and SHA-256 match the published values. The token is
  sent only to datadryad.org and is never printed, logged or written to a manifest.
- **Without a token:** download the files in a browser from the dataset page into the folder
  `fetch` names, then run `fetch` (or `verify`): it checks them against the same pins.

    uv run python -m wattwise.data.dryad list lbnl59
    uv run python -m wattwise.data.dryad fetch lbnl59     # into ../data/raw/lbnl59
    uv run python -m wattwise.data.dryad fetch hkust      # into ../data/raw/hkust (1.43 GB)

The data is never committed (`data/raw/` is git-ignored); the manifests in `data/manifests/` record
what was verified, without any secret.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Final

from wattwise.data.acquisition import (
    USER_AGENT,
    AcquisitionError,
    FileResult,
    FileStatus,
    Opener,
    RemoteFile,
    ensure,
    open_url,
    target_path,
    verify,
)

TOKEN_ENV: Final = "WATTWISE_DRYAD_TOKEN"
API: Final = "https://datadryad.org/api/v2"
DEFAULT_RAW: Final = Path("../data/raw")
DEFAULT_MANIFESTS: Final = Path("../data/manifests")


@dataclass(frozen=True)
class DryadDataset:
    key: str
    title: str
    doi: str
    version: int  # the Dryad version whose files and checksums are pinned
    citation: str
    files: tuple[RemoteFile, ...]

    @property
    def page(self) -> str:
        return f"https://datadryad.org/dataset/{self.doi}"


def _file(file_id: int, name: str, size: int, sha256: str, description: str) -> RemoteFile:
    return RemoteFile(
        key=name,
        url=f"{API}/files/{file_id}/download",
        local_path=name,
        size=size,
        sha256=sha256,
        description=description,
    )


#: Pins read from Dryad's API on 2026-11-01 (dataset, version and file records).
DATASETS: Final[dict[str, DryadDataset]] = {
    "lbnl59": DryadDataset(
        key="lbnl59",
        title=(
            "A three-year building operational performance "
            "dataset for informing energy efficiency"
        ),
        doi="doi:10.7941/D1N33Q",
        version=162054,
        citation=(
            "Hong, T., Luo, N., Blum, D., Wang, Z. (2022). A three-year building operational "
            "performance dataset for informing energy efficiency. Dryad, "
            "https://doi.org/10.7941/D1N33Q. Article: Scientific Data, "
            "https://doi.org/10.1038/s41597-022-01257-x. Licence: CC0 1.0."
        ),
        files=(
            _file(1305095, "Building_59.zip", 263_162_077,
                  "1e224dd7479bb196a8e0368fceb70aa6f699c1d39e1e895ceba7f3b25150b1b4",
                  "The building's three years of data"),
            _file(1305096, "data_description_table_3year_clean_data.xlsx", 75_069,
                  "6cf5be4565afe60ab17500c0d65d769df14b61e0c6447a7ff6b161b9eac0e63a",
                  "Description of every data point"),
            _file(1305094, "metadata_Dryad_Bldg59.docx", 17_917,
                  "104821176a2ff75a85259d5b0377e282ff00312b31e6521581725006a3295599",
                  "Dataset metadata"),
            _file(1305097, "README_Dryad_Bldg59.txt", 6_714,
                  "44c1b0834e087f2d277ffe11adca5141d260e2918facc746bba2a19cec0c77b2",
                  "Authors' README"),
        ),
    ),
    "hkust": DryadDataset(
        key="hkust",
        title=(
            "A 2.5-year campus-level smart meter database "
            "with equipment data for energy analytics"
        ),
        doi="doi:10.5061/dryad.k3j9kd5h6",
        version=308602,
        citation=(
            "Li, M., Wang, Z., Qu, Y., Chui, K. M., Leung-Shea, M. (2024). A 2.5-year campus-level "
            "smart meter database with equipment data for energy analytics. Dryad, "
            "https://doi.org/10.5061/dryad.k3j9kd5h6. Article: Scientific Data, "
            "https://doi.org/10.1038/s41597-024-04106-1. Licence: CC0 1.0."
        ),
        files=(
            _file(3365419, "All_Data.zip", 1_432_480_964,
                  "f2446158573311bda2b1fbd8a114bb1479ac8d4a0e11c395ca3b920676eb0c8a",
                  "All meters, 2022-2024"),
            _file(3365421, "README.md", 4_104,
                  "e7af1d78fccd7e16176ddc271957a1f44dec0ea3e663052a0350def3d2e8ca8a",
                  "Authors' README"),
        ),
    ),
}  # fmt: skip


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects: urllib would carry the Authorization header to the new host."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})


def token_opener(token: str) -> Opener:
    """An opener that sends the token to Dryad's API only, over HTTPS, and nowhere else.

    Dryad answers a download with a redirect to a pre-signed storage URL (Amazon S3). That URL is
    followed **without** the token: S3 rejects a request that carries both (HTTP 400), and the
    token must not reach another host anyway."""

    @contextmanager
    def open_with_token(url: str, timeout: float) -> Generator[BinaryIO]:
        if not url.startswith(f"{API}/"):
            raise AcquisitionError("Refusing to send the Dryad token to a URL outside its API.")
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"}
        )
        location = None
        try:
            response = urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in REDIRECTS:
                raise
            location = exc.headers.get("Location", "")
            exc.close()
        if location is None:
            with response:
                yield response
            return
        if not location.startswith("https://"):
            raise AcquisitionError("Dryad redirected the download to a non-HTTPS location.")
        with open_url(location, timeout) as redirected:  # no token
            yield redirected

    return open_with_token


def manual_instructions(dataset: DryadDataset, missing: Sequence[RemoteFile], folder: Path) -> str:
    names = "\n".join(f"  - {f.local_path} ({f.size:,} bytes)" for f in missing)
    return (
        f"{dataset.key}: {len(missing)} file(s) are not here yet, and no Dryad token is set "
        f"({TOKEN_ENV}). Dryad refuses unauthenticated downloads. Either set {TOKEN_ENV} to a "
        f"Dryad API token, or download these from {dataset.page} in a browser into "
        f"{folder.resolve()}:\n{names}\nthen run this command again to verify them."
    )


def fetch(
    dataset: DryadDataset,
    raw: Path,
    manifests: Path,
    *,
    token: str | None,
    opener: Opener | None = None,
    now: datetime | None = None,
) -> list[FileResult]:
    """Verify every pinned file, downloading the missing ones when a token is given."""
    folder = raw / dataset.key
    missing = [f for f in dataset.files if not target_path(f, folder).exists()]
    if missing and token is None:
        raise AcquisitionError(manual_instructions(dataset, missing, folder))
    results = []
    for remote in dataset.files:
        if remote in missing:
            assert token is not None
            results.append(ensure(remote, folder, opener=opener or token_opener(token)))
        else:
            checked = verify(remote, folder)
            assert checked is not None
            results.append(checked)
    write_manifest(dataset, manifests / f"{dataset.key}.json", results, now or datetime.now(UTC))
    return results


def write_manifest(
    dataset: DryadDataset, path: Path, results: Sequence[FileResult], now: datetime
) -> None:
    """Record what was verified. No token, no absolute paths."""
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    previous: dict[str, object] = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    files = {}
    for result, remote in zip(results, dataset.files, strict=True):
        earlier = previous.get(remote.key)
        kept = earlier.get("obtained_at") if isinstance(earlier, dict) else None
        files[remote.key] = {
            "dryad_url": remote.url,
            "local_path": f"data/raw/{dataset.key}/{remote.local_path}",
            "bytes": result.size,
            "sha256": result.sha256,
            "obtained_at": stamp if result.status is FileStatus.DOWNLOADED else kept or stamp,
            "last_verified_at": stamp,
        }
    manifest = {
        "dataset": dataset.title,
        "doi": dataset.doi,
        "dryad_version": dataset.version,
        "licence": "CC0 1.0",
        "citation": dataset.citation,
        "documentation": "docs/DATASETS.md",
        "files": files,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wattwise.data.dryad",
        description="Obtain and verify the pinned Dryad datasets (LBNL Building 59, HKUST).",
    )
    parser.add_argument("command", choices=["list", "fetch"])
    parser.add_argument("dataset", choices=sorted(DATASETS))
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--manifests", type=Path, default=DEFAULT_MANIFESTS)
    args = parser.parse_args(argv)
    dataset = DATASETS[args.dataset]
    if args.command == "list":
        print(f"{dataset.title}\n{dataset.page} (version {dataset.version}, CC0 1.0)")
        for f in dataset.files:
            print(f"  {f.local_path}  {f.size:,} bytes  sha256 {f.sha256}")
        return 0
    token = os.environ.get(TOKEN_ENV) or None
    try:
        results = fetch(dataset, args.raw, args.manifests, token=token)
    except AcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(f"{result.status.value:10} {result.path} ({result.size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
