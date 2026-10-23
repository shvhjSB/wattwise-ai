import email.message
import hashlib
import io
import urllib.error
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

import pytest

from wattwise.data.acquisition import (
    AcquisitionError,
    FileStatus,
    RemoteFile,
    ensure,
    open_url,
    target_path,
    verify,
)

CONTENT = b"timestamp,value\n2016-01-01 00:00:00,1.0\n" * 1000


def remote_for(content: bytes = CONTENT, local_path: str = "nested/sample.csv") -> RemoteFile:
    return RemoteFile(
        key="sample",
        url="https://example.test/sample.csv",
        local_path=local_path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        description="test file",
    )


class FakeServer:
    """Stands in for the network: serves `body`, or raises `error`, and counts requests."""

    def __init__(self, body: bytes = CONTENT, error: BaseException | None = None) -> None:
        self.body = body
        self.error = error
        self.requests: list[str] = []

    @contextmanager
    def __call__(self, url: str, timeout: float) -> Generator[BinaryIO]:
        self.requests.append(url)
        if self.error is not None:
            raise self.error
        yield io.BytesIO(self.body)


class BrokenStream(io.BytesIO):
    """Delivers one chunk, then the connection drops."""

    def __init__(self) -> None:
        super().__init__(CONTENT)
        self.reads = 0

    def read(self, size: int | None = -1) -> bytes:
        self.reads += 1
        if self.reads > 1:
            raise ConnectionResetError("connection reset by peer")
        return super().read(1024)


def leftovers(destination: Path) -> list[str]:
    return sorted(p.name for p in destination.rglob("*.part"))


def test_downloads_a_missing_file_and_verifies_it(tmp_path: Path) -> None:
    server = FakeServer()

    result = ensure(remote_for(), tmp_path, opener=server)

    assert result.status is FileStatus.DOWNLOADED
    assert result.path == tmp_path / "nested" / "sample.csv"
    assert result.path.read_bytes() == CONTENT
    assert server.requests == ["https://example.test/sample.csv"]
    assert leftovers(tmp_path) == []


def test_a_verified_file_is_not_downloaded_again(tmp_path: Path) -> None:
    ensure(remote_for(), tmp_path, opener=FakeServer())
    server = FakeServer()

    result = ensure(remote_for(), tmp_path, opener=server)

    assert result.status is FileStatus.VERIFIED
    assert server.requests == []


def test_a_mismatching_existing_file_is_never_overwritten_silently(tmp_path: Path) -> None:
    path = target_path(remote_for(), tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"someone else's file")
    server = FakeServer()

    with pytest.raises(AcquisitionError, match=r"left untouched.*--force"):
        ensure(remote_for(), tmp_path, opener=server)

    assert path.read_bytes() == b"someone else's file"
    assert server.requests == []


def test_force_replaces_a_mismatching_file(tmp_path: Path) -> None:
    path = target_path(remote_for(), tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stale")

    result = ensure(remote_for(), tmp_path, force=True, opener=FakeServer())

    assert result.status is FileStatus.DOWNLOADED
    assert path.read_bytes() == CONTENT


def test_content_with_the_wrong_checksum_is_not_saved(tmp_path: Path) -> None:
    tampered = CONTENT[:-1] + b"X"

    with pytest.raises(AcquisitionError, match="does not match the source's published checksum"):
        ensure(remote_for(), tmp_path, opener=FakeServer(body=tampered))

    assert not target_path(remote_for(), tmp_path).exists()
    assert leftovers(tmp_path) == []


def test_a_truncated_download_is_not_saved(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match=rf"got {len(CONTENT) - 10} bytes"):
        ensure(remote_for(), tmp_path, opener=FakeServer(body=CONTENT[:-10]))

    assert not target_path(remote_for(), tmp_path).exists()


def test_an_oversized_download_is_stopped(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match="more than the expected"):
        ensure(remote_for(), tmp_path, opener=FakeServer(body=CONTENT + b"extra" * 500_000))

    assert leftovers(tmp_path) == []


def test_an_interrupted_download_leaves_no_partial_file(tmp_path: Path) -> None:
    @contextmanager
    def flaky(url: str, timeout: float) -> Generator[BinaryIO]:
        yield BrokenStream()

    with pytest.raises(AcquisitionError, match="connection reset"):
        ensure(remote_for(), tmp_path, opener=flaky)

    assert leftovers(tmp_path) == []
    assert not target_path(remote_for(), tmp_path).exists()


def test_being_offline_is_explained(tmp_path: Path) -> None:
    offline = FakeServer(error=urllib.error.URLError("Name or service not known"))

    with pytest.raises(AcquisitionError, match="Check the internet connection"):
        ensure(remote_for(), tmp_path, opener=offline)


def test_forbidden_responses_mention_the_lfs_quota(tmp_path: Path) -> None:
    error = urllib.error.HTTPError(
        "https://example.test/sample.csv", 403, "Forbidden", email.message.Message(), None
    )

    with pytest.raises(AcquisitionError, match=r"HTTP 403.*LFS bandwidth quota"):
        ensure(remote_for(), tmp_path, opener=FakeServer(error=error))


def test_a_git_lfs_pointer_is_recognised(tmp_path: Path) -> None:
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n"

    with pytest.raises(AcquisitionError, match="Git LFS pointer"):
        ensure(remote_for(), tmp_path, opener=FakeServer(body=pointer))


def test_progress_is_reported(tmp_path: Path) -> None:
    seen: list[tuple[int, int]] = []

    ensure(remote_for(), tmp_path, opener=FakeServer(), progress=lambda r, t: seen.append((r, t)))

    assert seen[-1] == (len(CONTENT), len(CONTENT))


def test_verify_works_offline(tmp_path: Path) -> None:
    assert verify(remote_for(), tmp_path) is None
    ensure(remote_for(), tmp_path, opener=FakeServer())

    result = verify(remote_for(), tmp_path)

    assert result is not None
    assert result.status is FileStatus.VERIFIED
    target_path(remote_for(), tmp_path).write_bytes(b"corrupted")
    with pytest.raises(AcquisitionError, match="does not match"):
        verify(remote_for(), tmp_path)


@pytest.mark.parametrize("local_path", ["../escape.csv", "/etc/passwd", "a/../../b.csv"])
def test_local_paths_must_stay_inside_the_destination(local_path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        remote_for(local_path=local_path)


def test_checksums_must_be_sha256_hex() -> None:
    with pytest.raises(ValueError, match="sha256"):
        RemoteFile("x", "https://example.test/x", "x.csv", 1, "NOT-A-HASH", "x")


def test_plain_http_is_refused() -> None:
    with pytest.raises(AcquisitionError, match="non-HTTPS"), open_url("http://example.test/x", 1):
        pass
