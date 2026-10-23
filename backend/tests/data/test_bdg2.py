import dataclasses
import hashlib
import io
import json
import re
import urllib.error
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import pytest

from wattwise.data import acquisition, bdg2
from wattwise.data.acquisition import AcquisitionError, FileStatus

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def fake_files(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Replace the real (hundreds of MB) BDG2 files with small fakes served from memory."""
    contents = {remote.key: f"fake {remote.key}\n".encode() * 50 for remote in bdg2.FILES}
    fakes = tuple(
        dataclasses.replace(
            remote,
            size=len(contents[remote.key]),
            sha256=hashlib.sha256(contents[remote.key]).hexdigest(),
        )
        for remote in bdg2.FILES
    )
    monkeypatch.setattr(bdg2, "FILES", fakes)
    monkeypatch.setattr(bdg2, "FILES_BY_KEY", {remote.key: remote for remote in fakes})
    return {remote.url: contents[remote.key] for remote in fakes}


class FakeLfs:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.requests: list[str] = []

    @contextmanager
    def __call__(self, url: str, timeout: float) -> Generator[BinaryIO]:
        self.requests.append(url)
        yield io.BytesIO(self.bodies[url])


# ---------------------------------------------------------------------------
# The pinned source definition
# ---------------------------------------------------------------------------


def test_the_source_is_pinned_to_an_exact_commit() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", bdg2.COMMIT)


def test_files_come_from_the_lfs_media_endpoint_at_the_pinned_commit() -> None:
    prefix = f"https://media.githubusercontent.com/media/{bdg2.REPOSITORY}/{bdg2.COMMIT}/data/"
    for remote in bdg2.FILES:
        assert remote.url.startswith(prefix), remote.key


def test_file_keys_and_local_paths_are_unique() -> None:
    assert len({r.key for r in bdg2.FILES}) == len(bdg2.FILES)
    assert len({r.local_path for r in bdg2.FILES}) == len(bdg2.FILES)


def test_both_electricity_variants_and_their_context_are_defined() -> None:
    assert set(bdg2.FILES_BY_KEY) == {
        "metadata",
        "weather",
        "electricity_raw",
        "electricity_cleaned",
    }


def test_unknown_keys_are_rejected_with_the_choices() -> None:
    with pytest.raises(AcquisitionError, match="Choose from: metadata"):
        bdg2.select(["gas"])


def test_datasets_doc_matches_the_source_definition() -> None:
    doc = (REPO_ROOT / "docs" / "DATASETS.md").read_text(encoding="utf-8")

    assert bdg2.COMMIT in doc
    for remote in bdg2.FILES:
        assert f"| `{remote.key}` |" in doc, remote.key
        assert f"{remote.size:,}" in doc, f"{remote.key} size"
        assert remote.sha256[:8] in doc and remote.sha256[-6:] in doc, f"{remote.key} hash"


def test_raw_downloads_are_git_ignored() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "data/raw/" in ignored
    assert bdg2.DEFAULT_DESTINATION.as_posix().endswith("data/raw/bdg2")


# ---------------------------------------------------------------------------
# Fetching and the provenance manifest
# ---------------------------------------------------------------------------


def test_fetch_downloads_and_records_provenance(
    tmp_path: Path, fake_files: dict[str, bytes]
) -> None:
    manifest = tmp_path / "manifests" / "bdg2.json"
    when = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)

    results = bdg2.fetch(tmp_path / "raw", manifest, opener=FakeLfs(fake_files), now=when)

    assert [r.status for r in results] == [FileStatus.DOWNLOADED] * 4
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert record["commit"] == bdg2.COMMIT
    assert record["citation"].startswith("Miller, C.")
    assert {s["licence"] for s in record["licence_sources"]} == {"MIT", "CC-BY-4.0", "CC-BY-SA-4.0"}
    assert set(record["files"]) == set(bdg2.FILES_BY_KEY)
    weather = record["files"]["weather"]
    assert weather["sha256"] == bdg2.FILES_BY_KEY["weather"].sha256
    assert weather["downloaded_at"] == "2026-10-23T12:00:00Z"


def test_a_second_fetch_only_verifies_and_keeps_the_download_date(
    tmp_path: Path, fake_files: dict[str, bytes]
) -> None:
    manifest = tmp_path / "bdg2.json"
    first, second = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 23, tzinfo=UTC)
    bdg2.fetch(tmp_path / "raw", manifest, opener=FakeLfs(fake_files), now=first)
    server = FakeLfs(fake_files)

    results = bdg2.fetch(tmp_path / "raw", manifest, opener=server, now=second)

    assert server.requests == []
    assert {r.status for r in results} == {FileStatus.VERIFIED}
    entry = json.loads(manifest.read_text(encoding="utf-8"))["files"]["metadata"]
    assert entry["downloaded_at"] == "2026-10-01T00:00:00Z"
    assert entry["last_verified_at"] == "2026-10-23T00:00:00Z"


def test_fetch_can_be_limited_to_some_files(tmp_path: Path, fake_files: dict[str, bytes]) -> None:
    server = FakeLfs(fake_files)

    bdg2.fetch(tmp_path / "raw", tmp_path / "m.json", ["metadata", "weather"], opener=server)

    assert len(server.requests) == 2


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_cli_list_needs_no_network(capsys: pytest.CaptureFixture[str]) -> None:
    assert bdg2.main(["list"]) == 0

    out = capsys.readouterr().out
    assert "electricity_raw" in out
    assert "368.9 MB" in out


def test_cli_verify_reports_missing_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bdg2.main(["verify", "--dest", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "metadata: missing" in captured.out
    assert "fetch" in captured.err


def test_cli_fetch_failures_are_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    @contextmanager
    def offline(url: str, timeout: float) -> Generator[BinaryIO]:
        raise urllib.error.URLError("network unreachable")
        yield io.BytesIO()  # pragma: no cover

    monkeypatch.setattr(acquisition, "open_url", offline)

    code = bdg2.main(
        [
            "fetch",
            "--dest",
            str(tmp_path),
            "--manifest",
            str(tmp_path / "m.json"),
            "--only",
            "metadata",
        ]
    )

    assert code == 1
    assert "error: metadata: could not download" in capsys.readouterr().err
    assert not (tmp_path / "m.json").exists(), "no manifest for a failed download"
