"""Sending and following envelopes (Phase 7 LLD §2, §6, §10): transactions, access, audit."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, NotFound, ValidationFailed
from signora.modules.audit import Actor as AuditActor
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.departments import get_department, list_countersigners, load_access
from signora.modules.documents import VersionForReview, VersionNotApproved, version_for_review
from signora.modules.envelopes import emails, store
from signora.modules.envelopes.document import EnvelopeDocument, build_document
from signora.modules.envelopes.errors import (
    EnvelopeClosed,
    NotTheirTurn,
    RecipientSigned,
    SamePerson,
)
from signora.modules.envelopes.form import Colleague, FormSettings, SendForm, build_form
from signora.modules.envelopes.links import link_key, make_token, signing_url
from signora.modules.envelopes.sending import Person, SendRequest, plan_send, split_name
from signora.modules.envelopes.store import read_envelope, record_email, write_send
from signora.modules.envelopes.views import EnvelopePage, EnvelopeSummary, EnvelopeView
from signora.modules.identity_access import Actor, Permission, normalize_email
from signora.modules.notifications import send_email
from signora.modules.review import read_set


def send_form(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> SendForm:
    """What sending this version asks (§2), for someone with edit access; only an approved version
    is sent (platform FR-16)."""
    return _sendable(session, actor, document_id, version_id)[1]


def _sendable(
    session: Session, actor: Actor, document_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[VersionForReview, SendForm]:
    """The approved version and its send form, from one read of the version."""
    version = version_for_review(session, actor, document_id, version_id, edit=True)
    if version.status != "approved":
        raise VersionNotApproved
    parties, fields = read_set(session, version_id)
    department = get_department(session, actor.workspace_id, version.department_id)
    defaults = [
        Colleague(user_id=person.id, name=person.name, email=person.email)
        for person in list_countersigners(session, actor.workspace_id, version.department_id)
    ]
    form = build_form(
        document_id=document_id,
        document_name=version.document_name,
        version_id=version_id,
        version_number=version.version_no,
        pages=version.pages,
        parties=parties,
        fields=fields,
        countersigners=defaults,
        colleagues=list(_colleagues(session, actor.workspace_id).values()),
        settings=FormSettings(
            require_email_code=True,  # on by default (Phase 3 §5.1)
            reminder_interval_hours=department.reminder_interval_hours,
            max_reminders=department.max_reminders,
            expiry_days=department.expiry_days,
            notify_emails=list(department.notify_emails),
        ),
    )
    return version, form


# --- sending -------------------------------------------------------------------------------------


def _colleagues(
    session: Session, workspace_id: uuid.UUID, user_ids: Iterable[uuid.UUID] | None = None
) -> dict[uuid.UUID, Colleague]:
    """Who may countersign: the company's active members (anyone may, Phase 3 §4.2), by name; all
    of them, or those among ``user_ids``. The one definition: the send form offers them, and a
    send checks its countersigners against them."""
    rows = session.execute(
        text(
            "SELECT id, name, email FROM users WHERE workspace_id = :w AND deactivated_at IS NULL "
            "AND (CAST(:ids AS uuid[]) IS NULL OR id = ANY(:ids)) ORDER BY name, id"
        ),
        {"w": workspace_id, "ids": list(user_ids) if user_ids is not None else None},
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
    undoes the send); countersigners wait for every signer (§3), and with no signer to wait for
    they are the ones emailed."""
    session = uow.session
    version, form = _sendable(session, actor, document_id, request.version_id)
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
        time_zone=request.time_zone,
    )
    sender = _from(session, actor)
    for recipient_id, person in written.first:
        _email_sign_request(
            uow,
            sender=sender,
            workspace_id=actor.workspace_id,
            recipient_id=recipient_id,
            link_version=1,
            person=person,
            document=form.document_name,
            expires_at=written.expires_at.astimezone(ZoneInfo(request.time_zone)),
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


def envelope_document(session: Session, actor: Actor, envelope_id: uuid.UUID) -> EnvelopeDocument:
    """The sent version's pages and where its values are drawn, for whoever may see the envelope.
    Read, never the send form: an envelope shows its document after the document or its
    department is archived (sends already out are unaffected, Phase 4 §1.4)."""
    envelope = get_envelope(session, actor, envelope_id)
    version = version_for_review(
        session, actor, envelope.document_id, envelope.version_id, edit=False
    )
    _, fields = read_set(session, envelope.version_id)
    return build_document(version.pages, fields)


# --- following a send (§6) -----------------------------------------------------------------------

CLOSED = frozenset({"completed", "declined", "expired", "cancelled"})
LIVE = frozenset({"sent", "opened", "viewed"})  # holds a working link and has not signed yet


@dataclass(frozen=True)
class _Locked:
    id: uuid.UUID
    status: str
    department_id: uuid.UUID
    document_name: str
    expires_at: datetime
    sent_by: uuid.UUID
    time_zone: str  # the sender's, for the dates in its emails

    @property
    def expires_local(self) -> datetime:
        return self.expires_at.astimezone(ZoneInfo(self.time_zone))


def _lock(session: Session, actor: Actor, envelope_id: uuid.UUID) -> _Locked:
    """The envelope under its row lock, for someone who may send in its department; ``404`` for
    another company's."""
    row = session.execute(
        text(
            "SELECT e.id, e.status, e.department_id, d.name AS document_name, e.expires_at, "
            "e.sent_by, e.time_zone FROM envelopes e JOIN documents d ON d.id = e.document_id "
            "WHERE e.id = :e AND e.workspace_id = :w FOR UPDATE OF e"
        ),
        {"e": envelope_id, "w": actor.workspace_id},
    ).one_or_none()
    if row is None:
        raise NotFound
    load_access(session, actor).require(Permission.DOCUMENTS_SEND, row.department_id)
    return _Locked(**row._mapping)


def _open(session: Session, actor: Actor, envelope_id: uuid.UUID) -> _Locked:
    envelope = _lock(session, actor, envelope_id)
    if envelope.status in CLOSED:
        raise EnvelopeClosed
    return envelope


@dataclass(frozen=True)
class _Recipient:
    id: uuid.UUID
    kind: str
    status: str
    name: str
    email: str
    link_version: int
    reminders_sent: int


def _recipients(
    session: Session, envelope_id: uuid.UUID, recipient_id: uuid.UUID | None = None
) -> list[_Recipient]:
    rows = session.execute(
        text(
            "SELECT id, kind, status, name, email, link_version, reminders_sent "
            "FROM envelope_recipients WHERE envelope_id = :e "
            + ("AND id = :r " if recipient_id else "")
            + "ORDER BY stage, position FOR UPDATE"
        ),
        {"e": envelope_id, "r": recipient_id},
    )
    return [_Recipient(**row._mapping) for row in rows]


def _one(session: Session, envelope_id: uuid.UUID, recipient_id: uuid.UUID) -> _Recipient:
    found = _recipients(session, envelope_id, recipient_id)
    if not found:
        raise NotFound
    return found[0]


def remind(
    uow: UnitOfWork,
    *,
    actor: Actor,
    envelope_id: uuid.UUID,
    recipient_id: uuid.UUID | None = None,
) -> int:
    """Remind now: everyone who still has to act and holds a link (signers; countersigners once
    it is their turn), or one of them. Returns how many were emailed."""
    session = uow.session
    envelope = _open(session, actor, envelope_id)
    if recipient_id is None:
        due = [r for r in _recipients(session, envelope_id) if r.status in LIVE]
    else:
        one = _one(session, envelope_id, recipient_id)
        if one.status == "signed":
            raise RecipientSigned
        if one.status not in LIVE:
            raise NotTheirTurn
        due = [one]
    sender = _from(session, actor, envelope.sent_by)
    for recipient in due:
        count = recipient.reminders_sent + 1
        letter = emails.sign_reminder(
            company=sender.company,
            signer=recipient.name,
            document=envelope.document_name,
            url=_link(recipient.id, recipient.link_version),
            expires_at=envelope.expires_local,
        )
        email_id = send_email(
            uow,
            to=recipient.email,
            subject=letter.subject,
            text=letter.body.text,
            html=letter.body.html,
            category="sign_reminder",
            workspace_id=actor.workspace_id,
            dedupe_key=f"sign_reminder:{recipient.id}:{count}",
            reply_to=sender.sender_email,
        )
        session.execute(
            text("UPDATE envelope_recipients SET reminders_sent = :n WHERE id = :r"),
            {"n": count, "r": recipient.id},
        )
        record_email(session, recipient.id, email_id)
    details = {"recipient_id": str(recipient_id)} if recipient_id else {}
    _audit(uow, actor, "envelope.reminded", envelope_id, recipients=len(due), **details)
    return len(due)


def resend(
    uow: UnitOfWork, *, actor: Actor, envelope_id: uuid.UUID, recipient_id: uuid.UUID
) -> None:
    """Email one person their link again (also how a failed email is retried, §15.3)."""
    session = uow.session
    envelope = _open(session, actor, envelope_id)
    recipient = _one(session, envelope_id, recipient_id)
    if recipient.status == "signed":
        raise RecipientSigned
    if recipient.status not in LIVE:
        raise NotTheirTurn
    sender = _from(session, actor, envelope.sent_by)
    letter = emails.sign_request(
        company=sender.company,
        sender=sender.sender,
        signer=recipient.name,
        document=envelope.document_name,
        url=_link(recipient.id, recipient.link_version),
        expires_at=envelope.expires_local,
    )
    email_id = send_email(
        uow,
        to=recipient.email,
        subject=letter.subject,
        text=letter.body.text,
        html=letter.body.html,
        category="sign_request",
        workspace_id=actor.workspace_id,
        reply_to=sender.sender_email,
    )
    record_email(session, recipient.id, email_id)
    _audit(uow, actor, "envelope.resent", envelope_id, recipient_id=str(recipient_id))


def change_recipient(
    uow: UnitOfWork,
    *,
    actor: Actor,
    envelope_id: uuid.UUID,
    recipient_id: uuid.UUID,
    email: str | None,
    name: str | None,
    confirm_same_person: bool = False,
) -> None:
    """Correct a signer's or a copy's email (their old link stops working and a new one is
    emailed) or, before they open it, their name. A countersigner is a colleague: their account
    has their email. A signer's new email that another party of the envelope already has is one
    person on two parties, refused as a send refuses it until the sender confirms it."""
    session = uow.session
    envelope = _open(session, actor, envelope_id)
    recipient = _one(session, envelope_id, recipient_id)
    if recipient.status == "signed":
        raise RecipientSigned
    errors: list[FieldError] = []
    if recipient.kind == "countersigner":
        errors.append(FieldError("email", "A countersigner's email is their account's"))
    new_email = recipient.email
    if email is not None:
        try:
            new_email = normalize_email(email)
        except ValueError:
            errors.append(FieldError("email", "Enter a valid email address"))
    new_name = recipient.name
    if name is not None:
        new_name = name.strip()
        if not 1 <= len(new_name) <= 120:
            errors.append(FieldError("name", "Enter a name"))
        elif new_name != recipient.name and recipient.status not in ("sent", "waiting"):
            errors.append(FieldError("name", "They have opened it: their name stays as sent"))
    if errors:
        raise ValidationFailed(errors)
    email_changed = new_email != recipient.email
    if not email_changed and new_name == recipient.name:
        return
    if email_changed and recipient.kind == "signer" and not confirm_same_person:
        shared = session.execute(
            text(
                "SELECT 1 FROM envelope_recipients WHERE envelope_id = :e AND id <> :r "
                "AND kind IN ('signer', 'countersigner') AND email = :email LIMIT 1"
            ),
            {"e": envelope_id, "r": recipient_id, "email": new_email},
        ).first()
        if shared is not None:
            raise SamePerson(new_email)
    live = recipient.kind == "signer" and recipient.status in LIVE
    link_version = recipient.link_version + 1 if email_changed and live else recipient.link_version
    session.execute(
        text(
            "UPDATE envelope_recipients SET email = :email, name = :name, link_version = :v, "
            "status = CASE WHEN :restart THEN 'sent' ELSE status END, "
            "opened_at = CASE WHEN :restart THEN NULL ELSE opened_at END, "
            "viewed_at = CASE WHEN :restart THEN NULL ELSE viewed_at END, "
            "sent_at = CASE WHEN :restart THEN now() ELSE sent_at END WHERE id = :r"
        ),
        {
            "email": new_email,
            "name": new_name,
            "v": link_version,
            "restart": email_changed and live,
            "r": recipient_id,
        },
    )
    _refill(session, recipient_id, new_name, new_email)
    if email_changed and live:
        _email_sign_request(
            uow,
            sender=_from(session, actor, envelope.sent_by),
            workspace_id=actor.workspace_id,
            recipient_id=recipient_id,
            link_version=link_version,
            person=Person(new_name, new_email),
            document=envelope.document_name,
            expires_at=envelope.expires_local,
        )
    _audit(
        uow,
        actor,
        "envelope.recipient_changed",
        envelope_id,
        recipient_id=str(recipient_id),
        email_changed=email_changed,
        name_changed=new_name != recipient.name,
    )


def _refill(session: Session, recipient_id: uuid.UUID, name: str, email: str) -> None:
    """Their prefilled fields follow a corrected name or email (§2). Since Phase 7b only Email
    fields are prefilled; name rows are those of envelopes sent before it."""
    first, last = split_name(name)
    session.execute(
        text(
            "UPDATE envelope_values v SET value = CASE f.holds WHEN 'email' THEN :email "
            "WHEN 'full_name' THEN :name WHEN 'first_name' THEN :first ELSE :last END "
            "FROM version_fields f WHERE f.id = v.field_id AND v.recipient_id = :r "
            "AND v.given_by = 'prefill'"
        ),
        {"r": recipient_id, "email": email, "name": name, "first": first, "last": last},
    )


def cancel(uow: UnitOfWork, *, actor: Actor, envelope_id: uuid.UUID) -> None:
    """Withdraw a send (repeat-safe): every link stops working, and signers who were emailed and
    have not signed are told (§6, §15)."""
    session = uow.session
    envelope = _lock(session, actor, envelope_id)
    if envelope.status == "cancelled":
        return
    if envelope.status in CLOSED:
        raise EnvelopeClosed
    session.execute(
        text(
            "UPDATE envelopes SET status = 'cancelled', cancelled_at = now(), cancelled_by = :by "
            "WHERE id = :e"
        ),
        {"e": envelope_id, "by": actor.user_id},
    )
    told = [r for r in _recipients(session, envelope_id) if r.kind == "signer" and r.status in LIVE]
    session.execute(
        text(
            "UPDATE envelope_recipients SET revoked_at = now(), next_reminder_at = NULL "
            "WHERE envelope_id = :e"
        ),
        {"e": envelope_id},
    )
    sender = _from(session, actor, envelope.sent_by)
    for recipient in told:
        letter = emails.sign_withdrawn(
            company=sender.company, signer=recipient.name, document=envelope.document_name
        )
        email_id = send_email(
            uow,
            to=recipient.email,
            subject=letter.subject,
            text=letter.body.text,
            html=letter.body.html,
            category="sign_withdrawn",
            workspace_id=actor.workspace_id,
            dedupe_key=f"sign_withdrawn:{recipient.id}",
            reply_to=sender.sender_email,
        )
        record_email(session, recipient.id, email_id)
    _audit(uow, actor, "envelope.cancelled", envelope_id, told=len(told))


def signing_link(
    uow: UnitOfWork, *, actor: Actor, envelope_id: uuid.UUID, recipient_id: uuid.UUID
) -> str:
    """Copy signing link: the person's current link, shown again unchanged (ADR-E1)."""
    envelope = _open(uow.session, actor, envelope_id)
    recipient = _one(uow.session, envelope_id, recipient_id)
    if recipient.status not in LIVE:
        raise RecipientSigned if recipient.status == "signed" else NotTheirTurn
    _audit(uow, actor, "envelope.link_copied", envelope.id, recipient_id=str(recipient_id))
    return _link(recipient.id, recipient.link_version)


# --- the list (§6) --------------------------------------------------------------------------------


def _cursor(summary: EnvelopeSummary) -> str:
    raw = f"{summary.sent_at.isoformat()}|{summary.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _after(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        at, _, envelope_id = (
            base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode().partition("|")
        )
        return datetime.fromisoformat(at), uuid.UUID(envelope_id)
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailed([FieldError("cursor", "Start the list again")]) from None


def list_envelopes(
    session: Session,
    actor: Actor,
    department_id: uuid.UUID,
    *,
    status: str | None,
    cursor: str | None,
) -> EnvelopePage:
    """A department's envelopes for someone who may see its sends, newest first, 50 a page."""
    get_department(session, actor.workspace_id, department_id)  # 404 for another company's
    load_access(session, actor).require(Permission.DOCUMENTS_VIEW_SENDS, department_id)
    found = store.list_envelopes(
        session, actor.workspace_id, department_id, status=status, after=_after(cursor)
    )
    page = found[: store.PAGE]
    more = len(found) > store.PAGE
    return EnvelopePage(envelopes=page, next_cursor=_cursor(page[-1]) if more and page else None)
