"""Sending and following envelopes (Phase 7 LLD §2, §6, §10): transactions, access, audit."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from signora.modules.departments import get_department, list_countersigners
from signora.modules.documents import VersionNotApproved, version_for_review
from signora.modules.envelopes.form import Colleague, FormSettings, SendForm, build_form
from signora.modules.identity_access import Actor
from signora.modules.review import read_set


def send_form(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> SendForm:
    """What sending this version asks (§2), for someone with edit access; only an approved version
    is sent (platform FR-16)."""
    version = version_for_review(session, actor, document_id, version_id, edit=True)
    if version.status != "approved":
        raise VersionNotApproved
    parties, fields = read_set(session, version_id)
    department = get_department(session, actor.workspace_id, version.department_id)
    colleagues = [
        Colleague(user_id=person.id, name=person.name, email=person.email)
        for person in list_countersigners(session, actor.workspace_id, version.department_id)
    ]
    return build_form(
        document_id=document_id,
        document_name=version.document_name,
        version_id=version_id,
        version_number=version.version_no,
        parties=parties,
        fields=fields,
        countersigners=colleagues,
        settings=FormSettings(
            require_email_code=True,  # on by default (Phase 3 §5.1)
            reminder_interval_hours=department.reminder_interval_hours,
            max_reminders=department.max_reminders,
            expiry_days=department.expiry_days,
            notify_emails=list(department.notify_emails),
        ),
    )
