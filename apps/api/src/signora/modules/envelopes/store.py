"""Writing and reading envelopes (Phase 7 LLD §9, §11): a constant number of statements each."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.modules.envelopes.sending import Person, Plan, SettingsIn
from signora.modules.envelopes.views import (
    Delivery,
    EnvelopeView,
    PersonRef,
    RecipientView,
    TimelineEntry,
    ValueView,
)

TIMELINE_MAX = 200


@dataclass(frozen=True)
class Written:
    envelope_id: uuid.UUID
    expires_at: datetime
    signers: list[tuple[uuid.UUID, Person]]  # (recipient id, person), in signing order


def write_send(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    department_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    sent_by: uuid.UUID,
    plan: Plan,
    settings: SettingsIn,
) -> Written:
    envelope = session.execute(
        text(
            "INSERT INTO envelopes (workspace_id, department_id, document_id, version_id, title, "
            "require_email_code, reminder_interval_hours, max_reminders, expires_at, "
            "notify_emails, sent_by) VALUES (:w, :dep, :doc, :v, :title, :code, :every, :max, "
            "now() + make_interval(days => :days), :notify, :by) RETURNING id, expires_at"
        ),
        {
            "w": workspace_id,
            "dep": department_id,
            "doc": document_id,
            "v": version_id,
            "title": plan.title,
            "code": settings.require_email_code,
            "every": settings.reminder_interval_hours,
            "max": settings.max_reminders,
            "days": settings.expiry_days,
            "notify": plan.notify_emails,
            "by": sent_by,
        },
    ).one()
    rows = [
        {
            "party_id": str(person.party_id) if person.party_id else None,
            "kind": kind,
            "stage": stage,
            "position": position,
            "name": person.name,
            "email": person.email,
            "user_id": str(person.user_id) if person.user_id else None,
            "status": "sent" if kind == "signer" else "waiting",
        }
        for kind, stage, people in (
            ("signer", 1, plan.signers),
            ("countersigner", 2, plan.countersigners),
            ("copy", 3, plan.copies),
        )
        for position, person in enumerate(people, start=1)
    ]
    ids = {
        (row.stage, row.position): row.id
        for row in session.execute(
            text(
                "INSERT INTO envelope_recipients (workspace_id, envelope_id, version_id, party_id, "
                "kind, stage, position, name, email, user_id, status, sent_at) "
                "SELECT :w, :e, :v, r.party_id, r.kind, r.stage, r.position, r.name, r.email, "
                "r.user_id, r.status, CASE WHEN r.status = 'sent' THEN now() END "
                "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(party_id uuid, kind text, "
                "stage int, position int, name text, email text, user_id uuid, status text) "
                "RETURNING id, stage, position"
            ),
            {"w": workspace_id, "e": envelope.id, "v": version_id, "rows": json.dumps(rows)},
        )
    }
    signer_ids = {person.party_id: ids[(1, i)] for i, person in enumerate(plan.signers, start=1)}
    prefilled = [
        {"field_id": str(field_id), "value": value, "recipient_id": str(signer_ids[party_id])}
        for party_id, fills in plan.prefill.items()
        for field_id, value in fills.items()
    ]
    if prefilled:
        session.execute(
            text(
                "INSERT INTO envelope_values (envelope_id, workspace_id, version_id, field_id, "
                "value, given_by, recipient_id) SELECT :e, :w, :v, x.field_id, x.value, "
                "'prefill', x.recipient_id FROM jsonb_to_recordset(CAST(:values AS jsonb)) "
                "AS x(field_id uuid, value text, recipient_id uuid)"
            ),
            {"e": envelope.id, "w": workspace_id, "v": version_id, "values": json.dumps(prefilled)},
        )
    if plan.values:
        session.execute(
            text(
                "INSERT INTO envelope_values (envelope_id, workspace_id, version_id, field_id, "
                "value, given_by) SELECT :e, :w, :v, x.field_id, x.value, 'sender' "
                "FROM jsonb_to_recordset(CAST(:values AS jsonb)) AS x(field_id uuid, value text)"
            ),
            {
                "e": envelope.id,
                "w": workspace_id,
                "v": version_id,
                "values": json.dumps(
                    [{"field_id": str(k), "value": v} for k, v in plan.values.items()]
                ),
            },
        )
    return Written(
        envelope_id=envelope.id,
        expires_at=envelope.expires_at,
        signers=[(ids[(1, i)], person) for i, person in enumerate(plan.signers, start=1)],
    )


def record_email(session: Session, recipient_id: uuid.UUID, email_id: uuid.UUID | None) -> None:
    """The recipient's last email, whose delivery the envelope page shows."""
    if email_id is not None:
        session.execute(
            text("UPDATE envelope_recipients SET last_email_id = :m WHERE id = :r"),
            {"m": email_id, "r": recipient_id},
        )


def read_envelope(
    session: Session, workspace_id: uuid.UUID, envelope_id: uuid.UUID
) -> EnvelopeView | None:
    envelope = session.execute(
        text(
            "SELECT e.id, e.title, e.status, e.department_id, e.document_id, d.name AS "
            "document_name, e.version_id, v.version_no, e.sent_by, u.name AS sent_by_name, "
            "e.sent_at, e.expires_at, e.cancelled_at, e.require_email_code, "
            "e.reminder_interval_hours, e.max_reminders, e.notify_emails FROM envelopes e "
            "JOIN documents d ON d.id = e.document_id "
            "JOIN document_versions v ON v.id = e.version_id JOIN users u ON u.id = e.sent_by "
            "WHERE e.id = :e AND e.workspace_id = :w"
        ),
        {"e": envelope_id, "w": workspace_id},
    ).one_or_none()
    if envelope is None:
        return None
    recipients = [
        RecipientView(
            id=row.id,
            kind=row.kind,
            party_id=row.party_id,
            party_label=row.party_label,
            name=row.name,
            email=row.email,
            status=row.status,
            sent_at=row.sent_at,
            opened_at=row.opened_at,
            viewed_at=row.viewed_at,
            signed_at=row.signed_at,
            delivery=Delivery(status=row.delivery, error=row.last_error) if row.delivery else None,
        )
        for row in session.execute(
            text(
                "SELECT r.id, r.kind, r.party_id, p.label AS party_label, r.name, r.email, "
                "r.status, r.sent_at, r.opened_at, r.viewed_at, r.signed_at, m.status AS "
                "delivery, m.last_error FROM envelope_recipients r "
                "LEFT JOIN version_roles p ON p.id = r.party_id "
                "LEFT JOIN email_messages m ON m.id = r.last_email_id "
                "WHERE r.envelope_id = :e ORDER BY r.stage, r.position"
            ),
            {"e": envelope_id},
        )
    ]
    values = [
        ValueView(field_id=row.field_id, value=row.value, given_by=row.given_by)
        for row in session.execute(
            text(
                "SELECT field_id, value, given_by FROM envelope_values WHERE envelope_id = :e "
                "ORDER BY given_at, field_id"
            ),
            {"e": envelope_id},
        )
    ]
    timeline = [
        TimelineEntry(at=row.occurred_at, action=row.action, by=row.actor_label, data=row.data)
        for row in session.execute(
            text(
                "SELECT occurred_at, action, actor_label, data FROM audit_events "
                "WHERE subject_type = 'envelope' AND subject_id = :e AND workspace_id = :w "
                "ORDER BY occurred_at DESC, seq DESC LIMIT :n"
            ),
            {"e": envelope_id, "w": workspace_id, "n": TIMELINE_MAX},
        )
    ]
    return EnvelopeView(
        id=envelope.id,
        title=envelope.title,
        status=envelope.status,
        department_id=envelope.department_id,
        document_id=envelope.document_id,
        document_name=envelope.document_name,
        version_id=envelope.version_id,
        version_number=envelope.version_no,
        sent_by=PersonRef(id=envelope.sent_by, name=envelope.sent_by_name),
        sent_at=envelope.sent_at,
        expires_at=envelope.expires_at,
        cancelled_at=envelope.cancelled_at,
        require_email_code=envelope.require_email_code,
        reminder_interval_hours=envelope.reminder_interval_hours,
        max_reminders=envelope.max_reminders,
        notify_emails=list(envelope.notify_emails),
        recipients=recipients,
        values=values,
        timeline=timeline,
    )
