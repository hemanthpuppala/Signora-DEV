"""The agreement's text size beside each text place of an approved version (Phase 7b LLD), read
from its working copy once and kept in ``placement_text_sizes``: at approval, and by
``signora measure-text-sizes`` for versions approved before sizes were measured."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobRef, BlobStore
from signora.modules.typesetting import Measured, text_sizes

# Places a value is written in: a PDF's text box or a blank line, of a field holding text.
_WRITTEN = (
    "p.kind IN ('text', 'blank') AND f.holds NOT IN ('checkbox', 'choice', 'signature', 'initials')"
)


def measure(session: Session, blobs: BlobStore, version_id: uuid.UUID, pdf: BlobRef) -> int:
    """Measure and keep one version's sizes; how many places were measured. One read of the
    places, one of the PDF, one insert."""
    places = [
        Measured(row.id, row.page, (row.x0, row.y0, row.x1, row.y1))
        for row in session.execute(
            text(
                "SELECT p.id, p.page, p.x0, p.y0, p.x1, p.y1 FROM field_placements p "
                "JOIN version_fields f ON f.id = p.field_id WHERE p.version_id = :v "
                # Places a value is written in: a PDF's text box or a blank, of a field of text.
                "AND p.kind IN ('text', 'blank') "
                "AND f.holds NOT IN ('checkbox', 'choice', 'signature', 'initials')"
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


def measure_unmeasured(
    session: Session, blobs: BlobStore, workspace_id: uuid.UUID | None = None
) -> int:
    """Every approved version (of one company, if given) with a written place not measured yet;
    how many were measured.
    A place with no words on its page (a scanned page) stays unmeasured and is drawn by the
    fallback rule; such a version is read again by the next run, which writes nothing."""
    versions = session.execute(
        text(
            "SELECT v.id, v.workspace_id, v.pdf_sha256, v.pdf_bytes FROM document_versions v "
            "WHERE v.status = 'approved' AND v.pdf_sha256 IS NOT NULL AND EXISTS "
            "(SELECT 1 FROM field_placements p JOIN version_fields f ON f.id = p.field_id "
            "WHERE p.version_id = v.id AND p.kind IN ('text', 'blank') "
            "AND f.holds NOT IN ('checkbox', 'choice', 'signature', 'initials') "
            "AND NOT EXISTS (SELECT 1 FROM placement_text_sizes s WHERE s.placement_id = p.id)) "
            "AND (CAST(:w AS uuid) IS NULL OR v.workspace_id = :w)"
        ),
        {"w": workspace_id},
    ).all()
    for row in versions:
        measure(session, blobs, row.id, BlobRef(row.workspace_id, row.pdf_sha256, row.pdf_bytes))
    return len(versions)
