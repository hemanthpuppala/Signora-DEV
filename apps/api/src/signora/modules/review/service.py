"""Saving a version's fields (Phase 6 LLD §6.2, §1.4, §1.6): one transaction, one revision, one
audit entry listing the changes."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import ValidationFailed
from signora.modules.documents import (
    FieldsApproved,
    audit_document,
    record_field_count,
    version_for_review,
)
from signora.modules.identity_access import Actor
from signora.modules.review.editing import changes, check, settle
from signora.modules.review.errors import FieldsChanged, VersionNotInReview
from signora.modules.review.fieldset import FieldSet
from signora.modules.review.store import read_stored, write_set


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
    revision = session.execute(
        text("SELECT revision FROM version_reviews WHERE version_id = :v FOR UPDATE"),
        {"v": version_id},
    ).scalar_one_or_none()
    if revision != fieldset.revision:
        raise FieldsChanged
    stored = read_stored(session, version_id)
    errors = check(fieldset, stored, version.pages)
    if errors:
        raise ValidationFailed(errors)
    settled = settle(fieldset)
    record = changes(stored, settled)
    write_set(
        session,
        workspace_id=version.workspace_id,
        version_id=version_id,
        settled=settled,
        stored=stored,
    )
    new_revision: int = session.execute(
        text(
            "UPDATE version_reviews SET revision = revision + 1, updated_by = :by, "
            "updated_at = now() WHERE version_id = :v RETURNING revision"
        ),
        {"v": version_id, "by": actor.user_id},
    ).scalar_one()
    record_field_count(uow, version_id, len(settled.fields))
    audit_document(
        uow,
        actor,
        "document.fields_saved",
        document_id,
        version_no=version.version_no,
        revision=new_revision,
        **record,
    )
    return new_revision
