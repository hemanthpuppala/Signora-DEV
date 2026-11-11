"""The agreement's text size beside each text place of an approved version (Phase 7b LLD), read
from its working copy once and kept in ``placement_text_sizes``: at approval, and by
``signora measure-text-sizes`` for versions approved before sizes were measured or whose file
could not be read then. A size is a refinement: without one a value is drawn by the fallback rule
(typesetting.fit), so a file that cannot be read never fails what asked for the sizes."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobRef, BlobStore
from signora.kernel.logging import get_logger
from signora.modules.typesetting import Measured, text_sizes

log = get_logger("signora.review.text_sizes")

# Places a value is written in: a PDF's text box or a blank line, of a field holding text; and a
# dropdown's or a list's box, where the chosen option's words go (envelopes.sending.written_in).
_WRITTEN = (
    "(p.kind IN ('combobox', 'listbox') OR (p.kind IN ('text', 'blank') "
    "AND f.holds NOT IN ('checkbox', 'choice', 'signature', 'initials')))"
)


def measure(session: Session, blobs: BlobStore, version_id: uuid.UUID, pdf: BlobRef) -> int:
    """Measure and keep one version's sizes; how many places were measured. One read of the
    places, one of the PDF, one insert."""
    places = [
        Measured(row.id, row.page, (row.x0, row.y0, row.x1, row.y1))
        for row in session.execute(
            text(
                # _WRITTEN is a constant of this module, never input.
                "SELECT p.id, p.page, p.x0, p.y0, p.x1, p.y1 FROM field_placements p "  # noqa: S608
                "JOIN version_fields f ON f.id = p.field_id WHERE p.version_id = :v AND " + _WRITTEN
            ),
            {"v": version_id},
        )
    ]
    if not places:
        return 0
    sizes = text_sizes(blobs.path(pdf).read_bytes(), places)
    if sizes:
        session.execute(
            text(
                "INSERT INTO placement_text_sizes (placement_id, workspace_id, version_id, size) "
                "SELECT x.id, :w, :v, x.size FROM jsonb_to_recordset(CAST(:rows AS jsonb)) "
                "AS x(id uuid, size float8) ON CONFLICT (placement_id) DO NOTHING"
            ),
            {
                "w": pdf.workspace_id,
                "v": version_id,
                "rows": json.dumps([{"id": str(k), "size": v} for k, v in sizes.items()]),
            },
        )
    return len(sizes)


def measure_if_readable(
    session: Session, blobs: BlobStore, version_id: uuid.UUID, pdf: BlobRef
) -> bool:
    """Measure one version in a savepoint of its own; whether it was measured. A version that
    cannot be read (its file gone, a PDF that does not open) is logged and left as it was, for
    the command to measure later: the caller's transaction goes on."""
    try:
        with session.begin_nested():
            measure(session, blobs, version_id, pdf)
    except Exception as error:  # whatever the file or the PDF library raises: sizes are optional
        log.warning("text_sizes.version_failed", version_id=str(version_id), error=repr(error))
        return False
    return True


@dataclass(frozen=True)
class Backfill:
    measured: int  # versions measured
    failed: list[uuid.UUID]  # versions that could not be read: left as they were


def measure_unmeasured(
    session: Session, blobs: BlobStore, workspace_id: uuid.UUID | None = None
) -> Backfill:
    """Every approved version (of one company, if given) with a written place not measured yet.
    A place with no words on its page (a scanned page) stays unmeasured and is drawn by the
    fallback rule; such a version is read again by the next run, which writes nothing.

    Each version is measured in a savepoint of its own (``measure_if_readable``): one that cannot
    be read is logged and left, and the others are still measured."""
    versions = session.execute(
        text(
            # _WRITTEN is a constant of this module, never input.
            "SELECT v.id, v.workspace_id, v.pdf_sha256, v.pdf_bytes FROM document_versions v "  # noqa: S608
            "WHERE v.status = 'approved' AND v.pdf_sha256 IS NOT NULL AND EXISTS "
            "(SELECT 1 FROM field_placements p JOIN version_fields f ON f.id = p.field_id "
            "WHERE p.version_id = v.id AND " + _WRITTEN + " "
            "AND NOT EXISTS (SELECT 1 FROM placement_text_sizes s WHERE s.placement_id = p.id)) "
            "AND (CAST(:w AS uuid) IS NULL OR v.workspace_id = :w)"
        ),
        {"w": workspace_id},
    ).all()
    failed = [
        row.id
        for row in versions
        if not measure_if_readable(
            session, blobs, row.id, BlobRef(row.workspace_id, row.pdf_sha256, row.pdf_bytes)
        )
    ]
    return Backfill(measured=len(versions) - len(failed), failed=failed)
