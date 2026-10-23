"""Download dataset files explicitly and verifiably.

A file is only placed at its destination after its size and SHA-256 match the expected values,
so a destination path either holds verified data or nothing. Downloads stream to a `.part` file
next to the target and are renamed atomically. An existing file that already matches is not
downloaded again; an existing file that does not match is never overwritten unless `force` is set.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from wattwise import __version__

CHUNK_BYTES = 1024 * 1024
USER_AGENT = f"wattwise/{__version__} (dataset acquisition)"
_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/"

#: Opens a URL for reading and returns a binary stream. Injected in tests.
Opener = Callable[[str, float], AbstractContextManager[BinaryIO]]
#: Called with (bytes received so far, expected total bytes) while downloading.
Progress = Callable[[int, int], None]


class AcquisitionError(RuntimeError):
    """A dataset file could not be obtained or verified. The message says what to do."""


class FileStatus(StrEnum):
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"  # already present with the expected size and checksum


@dataclass(frozen=True)
class RemoteFile:
    """A file to acquire, with the size and SHA-256 published by its source."""

    key: str
    url: str
    local_path: str  # relative, POSIX-style, inside the destination directory
    size: int
    sha256: str
    description: str

    def __post_init__(self) -> None:
        relative = PurePosixPath(self.local_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"{self.key}: local_path must be relative: {self.local_path!r}")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError(f"{self.key}: sha256 must be 64 lowercase hex characters")
        if self.size <= 0:
            raise ValueError(f"{self.key}: size must be positive")


@dataclass(frozen=True)
class FileResult:
    key: str
    path: Path
    status: FileStatus
    size: int
    sha256: str


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches(path: Path, remote: RemoteFile) -> bool:
    """True if `path` exists with the expected size and checksum."""
    return (
        path.is_file() and path.stat().st_size == remote.size and sha256_of(path) == remote.sha256
    )


def target_path(remote: RemoteFile, destination: Path) -> Path:
    return destination.joinpath(*PurePosixPath(remote.local_path).parts)


def verify(remote: RemoteFile, destination: Path) -> FileResult | None:
    """Check a local copy without using the network. None if it is absent."""
    path = target_path(remote, destination)
    if not path.exists():
        return None
    if not matches(path, remote):
        raise AcquisitionError(
            f"{remote.key}: {path} does not match the expected size and SHA-256 "
            f"({remote.size} bytes, {remote.sha256}). Delete it, or re-run the download with "
            "--force to replace it."
        )
    return FileResult(remote.key, path, FileStatus.VERIFIED, remote.size, remote.sha256)


def ensure(
    remote: RemoteFile,
    destination: Path,
    *,
    force: bool = False,
    opener: Opener | None = None,
    timeout: float = 60.0,
    progress: Progress | None = None,
) -> FileResult:
    """Make sure `destination` holds a verified copy of `remote`, downloading only if needed."""
    path = target_path(remote, destination)
    if path.exists():
        if matches(path, remote):
            return FileResult(remote.key, path, FileStatus.VERIFIED, remote.size, remote.sha256)
        if not force:
            raise AcquisitionError(
                f"{remote.key}: {path} already exists but does not match the expected size and "
                f"SHA-256. It was left untouched. Re-run with --force to replace it."
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    try:
        digest, received = _download(remote, partial, opener or open_url, timeout, progress)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if received != remote.size or digest != remote.sha256:
        partial.unlink(missing_ok=True)
        raise AcquisitionError(
            f"{remote.key}: the downloaded file does not match the source's published checksum "
            f"(expected {remote.size} bytes, sha256 {remote.sha256}; got {received} bytes, "
            f"sha256 {digest}). Nothing was saved. Try again later; if it persists, the source "
            "may have changed."
        )
    os.replace(partial, path)
    return FileResult(remote.key, path, FileStatus.DOWNLOADED, received, digest)


def _download(
    remote: RemoteFile,
    partial: Path,
    opener: Opener,
    timeout: float,
    progress: Progress | None,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    received = 0
    try:
        with opener(remote.url, timeout) as response, partial.open("wb") as out:
            for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
                if received == 0 and chunk.startswith(_LFS_POINTER_PREFIX):
                    raise AcquisitionError(
                        f"{remote.key}: {remote.url} returned a Git LFS pointer file instead of "
                        "the data. Use the LFS media URL (media.githubusercontent.com)."
                    )
                received += len(chunk)
                if received > remote.size:
                    raise AcquisitionError(
                        f"{remote.key}: the server sent more than the expected {remote.size} "
                        "bytes. The download was stopped and nothing was saved."
                    )
                digest.update(chunk)
                out.write(chunk)
                if progress is not None:
                    progress(received, remote.size)
    except urllib.error.HTTPError as exc:
        raise AcquisitionError(_http_error_message(remote, exc)) from exc
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as exc:
        raise AcquisitionError(
            f"{remote.key}: could not download {remote.url} ({_reason(exc)}). Check the "
            "internet connection and try again; files already verified are not downloaded again."
        ) from exc
    return digest.hexdigest(), received


def _http_error_message(remote: RemoteFile, exc: urllib.error.HTTPError) -> str:
    hint = ""
    if exc.code in (403, 429):
        hint = (
            " GitHub may be rate-limiting, or the repository may be over its Git LFS bandwidth "
            "quota. Try again later."
        )
    elif exc.code == 404:
        hint = " The pinned source may have moved; check the source definition."
    return f"{remote.key}: {remote.url} returned HTTP {exc.code} {exc.reason}.{hint}"


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason if reason is not None else exc)


@contextmanager
def open_url(url: str, timeout: float) -> Generator[BinaryIO]:
    """Open an https URL with an identifying User-Agent."""
    if not url.startswith("https://"):
        raise AcquisitionError(f"Refusing to download over a non-HTTPS URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        yield response
