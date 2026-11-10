"""Saving and approving a version's fields (Phase 6 LLD §6.2, §1.2-1.6): one transaction, one
revision, one audit entry listing the changes. A version in review is saved in place; an edit of an
approved version becomes the next version; approving records the warnings accepted and the review
metrics."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobStore
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import ValidationFailed
from signora.modules.documents import (
    FieldsApproved,
    VersionForReview,
    VersionNotApproved,
    approve_version,
    audit_document,
    derive_version,
    record_field_count,
    version_for_review,
)
from signora.modules.identity_access import Actor
from signora.modules.review.checks import warnings_for
from signora.modules.review.editing import Settled, Stored, changes, check, rekey, settle
from signora.modules.review.errors import FieldsChanged, VersionNotInReview, WarningsChanged
from signora.modules.review.fieldset import ApproveRequest, FieldSet, Revised
from signora.modules.review.metrics import ApprovedPlace, measure
from signora.modules.review.store import (
    begin_review,
    lock_review,
    read_baseline,
    read_review,
    read_set,
    read_stored,
    record_approval,
    write_set,
)
from signora.modules.review.text_sizes import measure as measure_text_sizes


@dataclass(frozen=True)
class _Edit:
    stored: Stored
    settled: Settled
    record: dict[str, Any]  # the changes, for the audit entry


def _edit(session: Session, version: VersionForReview, revision: int, fieldset: FieldSet) -> _Edit:
    """The editor's set checked against the stored one it started from (§10.5), settled (§11) and
    compared (§1.4). A different revision means someone saved since: refused, never merged."""
    if revision != fieldset.revision:
        raise FieldsChanged
    stored = read_stored(session, version.id)
    errors = check(fieldset, stored, version.pages)
    if errors:
        raise ValidationFailed(errors)
    settled = settle(fieldset)
    return _Edit(stored=stored, settled=settled, record=changes(stored, settled))


def save(
    uow: UnitOfWork,
    *,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    fieldset: FieldSet,
) -> int:
    """Save a version in review as the editor holds it; returns the new revision. The version's
    row lock and the revision's compare-and-set mean a stale save is refused, never merged."""
    session = uow.session
    version = version_for_review(session, actor, document_id, version_id, edit=True, lock=True)
    if version.status == "approved":
        raise FieldsApproved
    if version.status != "ready":
        raise VersionNotInReview
    edit = _edit(session, version, lock_review(session, version_id), fieldset)
    write_set(
        session,
        workspace_id=version.workspace_id,
        version_id=version_id,
        settled=edit.settled,
        stored=edit.stored,
    )
    new_revision: int = session.execute(
        text(
            "UPDATE version_reviews SET revision = revision + 1, updated_by = :by, "
            "updated_at = now() WHERE version_id = :v RETURNING revision"
        ),
        {"v": version_id, "by": actor.user_id},
    ).scalar_one()
    record_field_count(uow, version_id, len(edit.settled.fields))
    audit_document(
        uow,
        actor,
        "document.fields_saved",
        document_id,
        version_no=version.version_no,
        revision=new_revision,
        **edit.record,
    )
    return new_revision


def approve(
    uow: UnitOfWork,
    *,
    actor: Actor,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    approval: ApproveRequest,
    blobs: BlobStore,
) -> None:
    """Approve a version in review (§1.3): the revision the page shows, with the warnings the person
    saw. The warnings are recorded as accepted, never a block (§2.1); the metrics compare the set
    with the AI's proposal (§1.5). Documents freezes it, audits it and moves current."""
    session = uow.session
    version = version_for_review(session, actor, document_id, version_id, edit=True, lock=True)
    if version.status != "ready":
        raise VersionNotInReview
    revision = lock_review(session, version_id)
    if revision != approval.revision:
        raise FieldsChanged
    roles, fields = read_set(session, version_id)
    _, flags = read_review(session, version_id)
    warnings = warnings_for(roles, fields, flags)
    if {w.code for w in warnings} != approval.accepted:
        raise WarningsChanged
    baseline_id, proposed = read_baseline(session, version_id)
    approved = [
        ApprovedPlace(
            field_id=field.id,
            page=place.page,
            rect=place.rect,
            holds=field.holds,
            label=field.label,
            filled_by=field.filled_by,
            party_id=field.party_id,
        )
        for field in fields
        for place in field.placements
    ]
    metrics = measure(proposed, approved)
    flags_accepted = sum(1 for field in fields if field.needs_review)
    accepted = [w.model_dump(mode="json", exclude_none=True) for w in warnings]
    record_approval(
        session,
        workspace_id=version.workspace_id,
        version_id=version_id,
        baseline_version_id=baseline_id,
        metrics=metrics,
        flags_accepted=flags_accepted,
        accepted=accepted,
    )
    if version.pdf is not None:  # the text size beside each place, for drawing values (7b)
        measure_text_sizes(session, blobs, version_id, version.pdf)
    approve_version(
        uow,
        actor=actor,
        document_id=document_id,
        version_id=version_id,
        details={
            "revision": revision,
            "accepted": [w.code for w in warnings],
            # Counts only: the audit chain's canonical JSON has no floats, and the ratios follow
            # from the counts (review_metrics keeps them).
            "metrics": {
                **{k: v for k, v in asdict(metrics).items() if isinstance(v, int)},
                "flags_accepted": flags_accepted,
            },
        },
    )


def revise(
    uow: UnitOfWork,
    *,
    actor: Actor,
    document_id: uuid.UUID,
    source_id: uuid.UUID,
    fieldset: FieldSet,
) -> Revised:
    """Save an edit of an approved version as the next version (§1.2): checked against the source
    as a Save is, then written under fresh ids. The source never changes (it is frozen), so its
    revision is stable and no lock on it is needed; numbering takes the document's lock."""
    session = uow.session
    source = version_for_review(session, actor, document_id, source_id, edit=True)
    if source.status != "approved":
        raise VersionNotApproved
    revision, _ = read_review(session, source_id)
    edit = _edit(session, source, revision, fieldset)
    version = derive_version(uow, actor=actor, document_id=document_id, source_id=source_id)
    settled, stored, ids = rekey(edit.settled, edit.stored)
    write_set(
        session,
        workspace_id=version.workspace_id,
        version_id=version.id,
        settled=settled,
        stored=stored,
    )
    new_revision = begin_review(
        session,
        workspace_id=version.workspace_id,
        version_id=version.id,
        source_id=source_id,
        by=actor.user_id,
        party_ids=ids,
    )
    record_field_count(uow, version.id, len(settled.fields))
    audit_document(
        uow,
        actor,
        "document.fields_saved",
        document_id,
        version_no=version.version_no,
        revision=new_revision,
        derived_from=source.version_no,
        **edit.record,
    )
    return Revised(version_id=version.id, number=version.version_no, revision=new_revision)
