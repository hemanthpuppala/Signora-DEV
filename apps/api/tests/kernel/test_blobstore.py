"""BlobStore contract tests (backbone LLD §5.6).

Written against the interface and parametrised by backend; the S3 backend joins the parameter list
when it is implemented.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import pytest

from signora.kernel.blobstore import BlobNotFoundError, BlobRef, BlobStore, LocalBlobStore
from signora.kernel.errors import PayloadTooLarge

BACKENDS: dict[str, Callable[[Path], BlobStore]] = {"local": LocalBlobStore}


@pytest.fixture(params=sorted(BACKENDS))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> BlobStore:
    factory: Callable[[Path], BlobStore] = BACKENDS[request.param]
    return factory(tmp_path / "blobs")


def stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and ".tmp" not in p.parts]


def test_put_then_open_returns_identical_bytes_with_correct_ref(store: BlobStore) -> None:
    workspace = uuid.uuid4()
    content = b"%PDF-1.7 agreement" * 1000

    ref = store.put(workspace, io.BytesIO(content), max_bytes=1_000_000)

    assert ref.sha256 == hashlib.sha256(content).hexdigest()
    assert ref.size == len(content)
    h = ref.sha256
    assert ref.key == f"workspaces/{workspace}/blobs/sha256/{h[:2]}/{h[2:4]}/{h}"
    with store.open(ref) as handle:
        assert handle.read() == content
    assert store.exists(ref)


def test_same_bytes_deduplicate_within_a_workspace_only(store: BlobStore, tmp_path: Path) -> None:
    content = b"same content"
    first, second = uuid.uuid4(), uuid.uuid4()

    a1 = store.put(first, io.BytesIO(content), max_bytes=100)
    a2 = store.put(first, io.BytesIO(content), max_bytes=100)
    b1 = store.put(second, io.BytesIO(content), max_bytes=100)

    assert a1 == a2
    assert a1.key != b1.key
    assert len(stored_files(tmp_path / "blobs")) == 2


def test_existing_object_is_never_replaced(store: BlobStore, tmp_path: Path) -> None:
    workspace = uuid.uuid4()
    ref = store.put(workspace, io.BytesIO(b"original"), max_bytes=100)
    path = tmp_path / "blobs" / ref.key
    inode = path.stat().st_ino

    again = store.put(workspace, io.BytesIO(b"original"), max_bytes=100)

    assert again == ref
    assert path.stat().st_ino == inode  # same file, not replaced


def test_over_the_limit_raises_and_leaves_nothing_behind(store: BlobStore, tmp_path: Path) -> None:
    with pytest.raises(PayloadTooLarge):
        store.put(uuid.uuid4(), io.BytesIO(b"x" * 101), max_bytes=100)

    assert stored_files(tmp_path / "blobs") == []
    assert list((tmp_path / "blobs" / ".tmp").iterdir()) == []


class _FailingStream(io.RawIOBase):
    """Delivers one chunk, then fails like a dropped upload connection."""

    def __init__(self) -> None:
        self._sent = False

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self._sent:
            raise ConnectionResetError("client went away")
        self._sent = True
        return b"partial upload"


def test_interrupted_write_leaves_no_partial_object(store: BlobStore, tmp_path: Path) -> None:
    stream: BinaryIO = _FailingStream()  # type: ignore[assignment]

    with pytest.raises(ConnectionResetError):
        store.put(uuid.uuid4(), stream, max_bytes=1_000)

    assert stored_files(tmp_path / "blobs") == []
    assert list((tmp_path / "blobs" / ".tmp").iterdir()) == []


def test_missing_object_raises_not_found(store: BlobStore) -> None:
    ref = BlobRef(uuid.uuid4(), "a" * 64, 1)

    assert not store.exists(ref)
    with pytest.raises(BlobNotFoundError):
        store.open(ref)


@pytest.mark.parametrize(
    ("workspace", "digest"),
    [
        ("not-a-uuid", "a" * 64),
        (uuid.uuid4(), "../../.env"),
        (uuid.uuid4(), "A" * 64),
        (uuid.uuid4(), "a" * 63),
    ],
)
def test_invalid_references_are_rejected_before_touching_storage(
    workspace: object, digest: str
) -> None:
    with pytest.raises((TypeError, ValueError)):
        BlobRef(workspace, digest, 1)  # type: ignore[arg-type]


def test_put_rejects_a_non_uuid_workspace(store: BlobStore) -> None:
    with pytest.raises(TypeError):
        store.put("../escape", io.BytesIO(b"x"), max_bytes=10)  # type: ignore[arg-type]


def test_check_succeeds_on_a_writable_store(store: BlobStore) -> None:
    store.check()


def test_files_are_not_world_readable(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    ref = store.put(uuid.uuid4(), io.BytesIO(b"private"), max_bytes=100)

    assert (tmp_path / "blobs" / ref.key).stat().st_mode & 0o007 == 0


def test_path_points_at_the_stored_file_and_refuses_a_missing_one(store: BlobStore) -> None:
    workspace = uuid.uuid4()
    ref = store.put(workspace, io.BytesIO(b"hello"), max_bytes=100)
    assert store.path(ref).read_bytes() == b"hello"
    with pytest.raises(BlobNotFoundError):
        store.path(BlobRef(workspace, "0" * 64, 1))
