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

from wattwise.data import dryad
from wattwise.data.acquisition import AcquisitionError, FileStatus, Opener, RemoteFile

CONTENT = {"a.zip": b"zip bytes" * 100, "README.txt": b"read me"}
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
TOKEN = "secret-token-value"


def remote(name: str, file_id: int) -> RemoteFile:
    data = CONTENT[name]
    return RemoteFile(
        key=name,
        url=f"{dryad.API}/files/{file_id}/download",
        local_path=name,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        description=name,
    )


DATASET = dryad.DryadDataset(
    key="example",
    title="Example",
    doi="doi:10.0000/x",
    version=1,
    citation="Example citation",
    files=(remote("a.zip", 1), remote("README.txt", 2)),
)


def serving(content: dict[str, bytes], seen: list[str]) -> Opener:
    @contextmanager
    def opener(url: str, timeout: float) -> Generator[BinaryIO]:
        seen.append(url)
        file_id = int(url.split("/")[-2])
        name = {1: "a.zip", 2: "README.txt"}[file_id]
        yield io.BytesIO(content[name])

    return opener


def test_with_a_token_missing_files_are_downloaded_and_verified(tmp_path: Path) -> None:
    seen: list[str] = []

    results = dryad.fetch(
        DATASET,
        tmp_path / "raw",
        tmp_path / "m",
        token=TOKEN,
        opener=serving(CONTENT, seen),
        now=NOW,
    )

    assert [r.status for r in results] == [FileStatus.DOWNLOADED, FileStatus.DOWNLOADED]
    assert (tmp_path / "raw" / "example" / "a.zip").read_bytes() == CONTENT["a.zip"]
    assert len(seen) == 2


def test_without_a_token_missing_files_get_manual_instructions(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError) as raised:
        dryad.fetch(DATASET, tmp_path / "raw", tmp_path / "m", token=None, now=NOW)

    message = str(raised.value)
    assert dryad.TOKEN_ENV in message
    assert "https://datadryad.org/dataset/doi:10.0000/x" in message
    assert "a.zip" in message and "README.txt" in message
    assert not (tmp_path / "m" / "example.json").exists()


def test_files_downloaded_in_a_browser_are_verified_without_a_token(tmp_path: Path) -> None:
    folder = tmp_path / "raw" / "example"
    folder.mkdir(parents=True)
    for name, data in CONTENT.items():
        (folder / name).write_bytes(data)

    results = dryad.fetch(DATASET, tmp_path / "raw", tmp_path / "m", token=None, now=NOW)

    assert [r.status for r in results] == [FileStatus.VERIFIED, FileStatus.VERIFIED]
    manifest = json.loads((tmp_path / "m" / "example.json").read_text(encoding="utf-8"))
    assert manifest["licence"] == "CC0 1.0"
    assert manifest["files"]["a.zip"]["sha256"] == DATASET.files[0].sha256
    assert manifest["files"]["a.zip"]["local_path"] == "data/raw/example/a.zip"


def test_a_wrong_file_is_rejected_and_left_untouched(tmp_path: Path) -> None:
    folder = tmp_path / "raw" / "example"
    folder.mkdir(parents=True)
    (folder / "a.zip").write_bytes(b"not the published file")
    (folder / "README.txt").write_bytes(CONTENT["README.txt"])

    with pytest.raises(AcquisitionError, match="does not match"):
        dryad.fetch(DATASET, tmp_path / "raw", tmp_path / "m", token=None, now=NOW)

    assert (folder / "a.zip").read_bytes() == b"not the published file"


def test_a_corrupt_download_is_not_saved(tmp_path: Path) -> None:
    corrupt = {**CONTENT, "a.zip": b"x" * len(CONTENT["a.zip"])}

    with pytest.raises(AcquisitionError, match="published checksum"):
        dryad.fetch(
            DATASET, tmp_path / "raw", tmp_path / "m", token=TOKEN,
            opener=serving(corrupt, []), now=NOW,
        )  # fmt: skip

    assert not (tmp_path / "raw" / "example" / "a.zip").exists()


def test_the_token_never_reaches_the_manifest_or_an_error(tmp_path: Path) -> None:
    dryad.fetch(
        DATASET, tmp_path / "raw", tmp_path / "m", token=TOKEN, opener=serving(CONTENT, []), now=NOW
    )

    assert TOKEN not in (tmp_path / "m" / "example.json").read_text(encoding="utf-8")


def test_the_token_is_sent_only_to_the_dryad_api() -> None:
    opener = dryad.token_opener(TOKEN)

    with (
        pytest.raises(AcquisitionError, match="outside its API") as raised,
        opener("https://example.com/files/1/download", 5),
    ):
        pass
    assert TOKEN not in str(raised.value)


def test_the_token_goes_in_an_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, str] = {}

    def fake_urlopen(request: object, timeout: float) -> io.BytesIO:
        sent.update(dict(request.header_items()))  # type: ignore[attr-defined]
        return io.BytesIO(b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with dryad.token_opener(TOKEN)(f"{dryad.API}/files/1/download", 5):
        pass

    assert sent["Authorization"] == f"Bearer {TOKEN}"


def test_a_refused_download_is_explained(tmp_path: Path) -> None:
    @contextmanager
    def refusing(url: str, timeout: float) -> Generator[BinaryIO]:
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
        yield io.BytesIO()

    with pytest.raises(AcquisitionError, match="401"):
        dryad.fetch(DATASET, tmp_path / "raw", tmp_path / "m", token=TOKEN, opener=refusing)


@pytest.mark.parametrize("key", sorted(dryad.DATASETS))
def test_the_real_pins_are_well_formed(key: str) -> None:
    dataset = dryad.DATASETS[key]

    assert dataset.files
    assert len({f.key for f in dataset.files}) == len(dataset.files)
    for f in dataset.files:
        assert re.fullmatch(r"https://datadryad\.org/api/v2/files/\d+/download", f.url)
        assert re.fullmatch(r"[0-9a-f]{64}", f.sha256)
        assert "000000000000" not in f.sha256  # no placeholder digests


def test_the_command_line_lists_and_explains_without_a_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(dryad.TOKEN_ENV, raising=False)

    assert dryad.main(["list", "lbnl59"]) == 0
    assert "Building_59.zip" in capsys.readouterr().out
    code = dryad.main(
        ["fetch", "lbnl59", "--raw", str(tmp_path / "raw"), "--manifests", str(tmp_path / "m")]
    )
    assert code == 1
    assert "datadryad.org/dataset/doi:10.7941/D1N33Q" in capsys.readouterr().err
