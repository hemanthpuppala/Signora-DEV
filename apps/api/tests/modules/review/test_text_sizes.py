"""The agreement's text size beside each place, kept when a version is approved (Phase 7b LLD)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import BlobRef, LocalBlobStore
from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.modules.review import measure_unmeasured
from tests.modules.review.test_approve import _approve
from tests.modules.review.test_save import _in_review, _view


def _sizes(view: dict[str, object]) -> dict[str, float | None]:
    return {
        place["id"]: place["text_size"]
        for field in view["fields"]  # type: ignore[attr-defined]
        for place in field["placements"]
        if field["holds"] not in ("signature", "initials", "checkbox", "choice")
    }


def test_approval_measures_each_written_place_and_earlier_versions_are_measured_by_command(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    assert set(_sizes(_view(owner, document_id, version_id)).values()) == {None}  # in review

    assert _approve(owner, document_id, version_id).status_code == 204

    measured = _sizes(_view(owner, document_id, version_id))
    assert measured and all(size is not None and 0 < size <= 72 for size in measured.values())

    # A version approved before sizes were kept: the command measures it, once.
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("DELETE FROM placement_text_sizes WHERE version_id = :v"), {"v": version_id}
        )
        workspace_id = uow.session.execute(
            text("SELECT workspace_id FROM document_versions WHERE id = :v"), {"v": version_id}
        ).scalar_one()
    # A version whose file cannot be read is named and left; it never stops the run.
    with committing_db.unit_of_work() as uow:
        lost = measure_unmeasured(uow.session, LocalBlobStore(tmp_path), workspace_id)
    assert (lost.measured, [str(v) for v in lost.failed]) == (0, [version_id])
    blobs = LocalBlobStore(settings.blob_store.dir)
    with committing_db.unit_of_work() as uow:
        assert measure_unmeasured(uow.session, blobs, workspace_id).measured == 1
    assert _sizes(_view(owner, document_id, version_id)) == measured
    with committing_db.unit_of_work() as uow:
        assert measure_unmeasured(uow.session, blobs, workspace_id).measured == 0


def test_a_working_copy_that_cannot_be_read_never_refuses_the_approval(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
    settings: Settings,
) -> None:
    """A size is a refinement with a fallback rule. A file gone from the store, or one that no
    longer opens, failed the approval with a 500 and rolled it back."""
    document_id, version_id = _in_review(owner, run, detect)
    with committing_db.unit_of_work() as uow:
        row = uow.session.execute(
            text("SELECT workspace_id, pdf_sha256, pdf_bytes FROM document_versions WHERE id = :v"),
            {"v": version_id},
        ).one()
    blobs = LocalBlobStore(settings.blob_store.dir)
    path = blobs.path(BlobRef(row.workspace_id, row.pdf_sha256, row.pdf_bytes))
    original = path.read_bytes()
    path.write_bytes(b"%PDF-1.7 not a pdf at all")
    try:
        assert _approve(owner, document_id, version_id).status_code == 204
    finally:
        path.write_bytes(original)

    view = _view(owner, document_id, version_id)
    assert view["status"] == "approved"
    assert set(_sizes(view).values()) == {None}  # drawn by the fallback rule
    # The command measures it once the file can be read again.
    with committing_db.unit_of_work() as uow:
        assert measure_unmeasured(uow.session, blobs, row.workspace_id).measured == 1
    assert None not in _sizes(_view(owner, document_id, version_id)).values()
