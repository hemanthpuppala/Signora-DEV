"""The agreement's text size beside each place, kept when a version is approved (Phase 7b LLD)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import LocalBlobStore
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
    blobs = LocalBlobStore(settings.blob_store.dir)
    with committing_db.unit_of_work() as uow:
        assert measure_unmeasured(uow.session, blobs, workspace_id) == 1
    assert _sizes(_view(owner, document_id, version_id)) == measured
    with committing_db.unit_of_work() as uow:
        assert measure_unmeasured(uow.session, blobs, workspace_id) == 0
