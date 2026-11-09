"""Sending and following envelopes (Phase 7 LLD §2, §6, §10): transactions, access, audit."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import NotFound
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments import get_department, list_countersigners, load_access
from signora.modules.documents import VersionNotApproved, version_for_review
from signora.modules.envelopes import emails
from signora.modules.envelopes.errors import SamePerson
from signora.modules.envelopes.form import Colleague, FormSettings, SendForm, build_form
from signora.modules.envelopes.links import link_key, make_token, signing_url
from signora.modules.envelopes.sending import Person, SendRequest, plan_send
from signora.modules.envelopes.store import read_envelope, record_email, write_send
from signora.modules.envelopes.views import EnvelopeView
from signora.modules.identity_access import Actor, Permission, normalize_email
from signora.modules.notifications import send_email
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


# --- sending -------------------------------------------------------------------------------------


def _colleagues(
    session: Session, workspace_id: uuid.UUID, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Colleague]:
    """Active members of the company among ``user_ids`` (anyone may countersign, Phase 3 §4.2)."""
    rows = session.execute(
        text(
            "SELECT id, name, email FROM users WHERE workspace_id = :w AND id = ANY(:ids) "
            "AND deactivated_at IS NULL"
        ),
        {"w": workspace_id, "ids": list(user_ids)},
    )
    return {row.id: Colleague(user_id=row.id, name=row.name, email=row.email) for row in rows}


@dataclass(frozen=True)
class _From:
    """Who an email comes from: the company's name and the sender."""

    company: str
    sender: str
    sender_email: str


def _from(session: Session, actor: Actor, sent_by: uuid.UUID | None = None) -> _From:
    row = session.execute(
        text(
            "SELECT w.name AS company, u.name, u.email FROM users u "
            "JOIN workspaces w ON w.id = u.workspace_id WHERE u.id = :u AND u.workspace_id = :w"
        ),
        {"u": sent_by or actor.user_id, "w": actor.workspace_id},
    ).one()
    return _From(row.company, row.name, row.email)


def _link(recipient_id: uuid.UUID, link_version: int) -> str:
    settings = get_settings().app
    key = link_key(settings.secret_key.get_secret_value())
    return signing_url(str(settings.public_base_url), make_token(key, recipient_id, link_version))


def _audit(uow: UnitOfWork, actor: Actor, action: str, envelope_id: uuid.UUID, **data: Any) -> None:
    record(
        uow,
        chain=AuditChain.workspace(actor.workspace_id),
        actor=AuditActor("user", actor.user_id, actor.email),
        action=action,
        subject=Subject("envelope", envelope_id),
        data=data,
    )


def _email_sign_request(
    uow: UnitOfWork,
    *,
    sender: _From,
    workspace_id: uuid.UUID,
    recipient_id: uuid.UUID,
    link_version: int,
    person: Person,
    document: str,
    expires_at: datetime,
) -> None:
    letter = emails.sign_request(
        company=sender.company,
        sender=sender.sender,
        signer=person.name,
        document=document,
        url=_link(recipient_id, link_version),
        expires_at=expires_at,
    )
    email_id = send_email(
        uow,
        to=person.email,
        subject=letter.subject,
        text=letter.body.text,
        html=letter.body.html,
        category="sign_request",
        workspace_id=workspace_id,
        dedupe_key=f"sign_request:{recipient_id}:{link_version}",
        reply_to=sender.sender_email,
    )
    record_email(uow.session, recipient_id, email_id)


def send(
    uow: UnitOfWork, *, actor: Actor, document_id: uuid.UUID, request: SendRequest
) -> EnvelopeView:
    """Send an approved version (§2, §8.1 FR-E3): checked against its form, written in one
    transaction, every signer emailed their own link (the emails are queued, so a failure never
    undoes the send); countersigners wait for every signer (§3)."""
    session = uow.session
    form = send_form(session, actor, document_id, request.version_id)
    version = version_for_review(session, actor, document_id, request.version_id, edit=True)
    plan = plan_send(
        form,
        request,
        colleagues=_colleagues(
            session, actor.workspace_id, (c.user_id for c in request.countersigners)
        ),
        normalize_email=normalize_email,
    )
    if plan.shared_emails and not request.confirm_same_person:
        raise SamePerson(", ".join(plan.shared_emails))
    written = write_send(
        session,
        workspace_id=actor.workspace_id,
        department_id=version.department_id,
        document_id=document_id,
        version_id=request.version_id,
        sent_by=actor.user_id,
        plan=plan,
        settings=request.settings,
    )
    sender = _from(session, actor)
    for recipient_id, person in written.signers:
        _email_sign_request(
            uow,
            sender=sender,
            workspace_id=actor.workspace_id,
            recipient_id=recipient_id,
            link_version=1,
            person=person,
            document=form.document_name,
            expires_at=written.expires_at,
        )
    _audit(
        uow,
        actor,
        "envelope.sent",
        written.envelope_id,
        document_id=str(document_id),
        version_no=form.version_number,
        signers=len(plan.signers),
        countersigners=len(plan.countersigners),
        copies=len(plan.copies),
        values=len(plan.values),
    )
    view = read_envelope(session, actor.workspace_id, written.envelope_id)
    if view is None:  # written in this transaction
        raise NotFound
    return view


def get_envelope(session: Session, actor: Actor, envelope_id: uuid.UUID) -> EnvelopeView:
    """An envelope of the company, for someone who may see its department's sends (it holds
    clients' details); ``404`` for another company's."""
    view = read_envelope(session, actor.workspace_id, envelope_id)
    if view is None:
        raise NotFound
    load_access(session, actor).require(Permission.DOCUMENTS_VIEW_SENDS, view.department_id)
    return view
