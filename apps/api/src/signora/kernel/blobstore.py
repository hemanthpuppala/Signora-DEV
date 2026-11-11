"""Immutable, content-addressed file storage (backbone LLD topic 5).

Objects are addressed by tenant-first object keys shared by every backend::

    workspaces/<workspace_id>/blobs/sha256/<h[0:2]>/<h[2:4]>/<h>

The local backend maps a key to a path under ``BLOB_STORE_DIR``; an S3 backend (added later) uses
the same key as the object name. Callers depend only on ``BlobStore`` and ``BlobRef``.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from signora.kernel.config import BlobStoreSettings
from signora.kernel.errors import PayloadTooLarge

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1024 * 1024
_FILE_MODE = 0o640


class BlobNotFoundError(LookupError):
    """The referenced object does not exist (a data-integrity problem, not a user error)."""


@dataclass(frozen=True)
class BlobRef:
    workspace_id: uuid.UUID
    sha256: str
    size: int

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, uuid.UUID):
            raise TypeError("workspace_id must be a UUID")
        if not _SHA256_HEX.match(self.sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        if self.size < 0:
            raise ValueError("size must not be negative")

    @property
    def key(self) -> str:
        h = self.sha256
        return f"workspaces/{self.workspace_id}/blobs/sha256/{h[0:2]}/{h[2:4]}/{h}"

    @property
    def token(self) -> str:
        """The object within its workspace, kept beside the workspace id: "sha256:size"."""
        return f"{self.sha256}:{self.size}"

    @classmethod
    def from_token(cls, workspace_id: uuid.UUID, token: str) -> BlobRef:
        sha256, _, size = token.partition(":")
        return cls(workspace_id, sha256, int(size))


class BlobStore(Protocol):
    def put(self, workspace_id: uuid.UUID, data: BinaryIO, *, max_bytes: int) -> BlobRef:
        """Store the stream; raises ``PayloadTooLarge`` over ``max_bytes``. Never overwrites."""
        ...

    def open(self, ref: BlobRef) -> BinaryIO:
        """Open for reading; raises ``BlobNotFoundError``."""
        ...

    def exists(self, ref: BlobRef) -> bool: ...

    def path(self, ref: BlobRef) -> Path:
        """A local file path for serving with HTTP ranges; raises ``BlobNotFoundError``. (An S3
        backend will serve through presigned URLs instead, added with it.)"""
        ...

    def check(self) -> None:
        """Readiness probe: raises when the store cannot be written."""
        ...


class LocalBlobStore:
    """Filesystem backend. Writes are atomic and put-if-absent (LLD §5.3 rule 3)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._tmp = self.root / ".tmp"

    def _path(self, ref: BlobRef) -> Path:
        path = (self.root / ref.key).resolve()
        if not path.is_relative_to(self.root):  # defence in depth; keys are already validated
            raise ValueError("object key escapes the store root")
        return path

    def put(self, workspace_id: uuid.UUID, data: BinaryIO, *, max_bytes: int) -> BlobRef:
        if not isinstance(workspace_id, uuid.UUID):
            raise TypeError("workspace_id must be a UUID")
        self._tmp.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(dir=self._tmp, prefix="upload-")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as tmp:
                while chunk := data.read(_CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise PayloadTooLarge(f"limit is {max_bytes} bytes")
                    digest.update(chunk)
                    tmp.write(chunk)
                tmp.flush()
                os.fsync(tmp.fileno())
            tmp_path.chmod(_FILE_MODE)
            ref = BlobRef(workspace_id=workspace_id, sha256=digest.hexdigest(), size=size)
            final = self._path(ref)
            final.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(tmp_path, final)  # fails instead of overwriting (rename would replace)
            except FileExistsError:
                pass  # identical content already stored: the key is the hash
            else:
                _fsync_directory(final.parent)
            return ref
        finally:
            with suppress(FileNotFoundError):
                tmp_path.unlink()

    def open(self, ref: BlobRef) -> BinaryIO:
        try:
            return self._path(ref).open("rb")
        except FileNotFoundError:
            raise BlobNotFoundError(ref.key) from None

    def exists(self, ref: BlobRef) -> bool:
        return self._path(ref).is_file()

    def path(self, ref: BlobRef) -> Path:
        path = self._path(ref)
        if not path.is_file():
            raise BlobNotFoundError(ref.key)
        return path

    def check(self) -> None:
        self._tmp.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self._tmp, prefix="health-") as probe:
            probe.write(b"ok")
            probe.flush()


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def blob_store_from_settings(settings: BlobStoreSettings) -> BlobStore:
    """Select the backend from configuration (only ``local`` exists for now)."""
    return LocalBlobStore(settings.dir)
