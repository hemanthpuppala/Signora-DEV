"""The certificate's facts, read from what is already kept (Phase 8 LLD §11.2): recipients,
consents, adopted signatures and the envelope's audit events. Nothing is written for it. Every
time is given in the envelope's zone. O(R + E) for R recipients and the envelope's E events.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Row, text

from signora.kernel.db import UnitOfWork
from signora.modules.envelopes import moment_in_words
from signora.modules.rendering import Certificate, Copy, Signature, Signed
from signora.modules.signing import consent
from signora.modules.typesetting import font

VERIFIED = {
    "email_code": "Email code",
    "email_link": "Email link",
    "signora_sign_in": "Signora sign-in",
}


def _when(moment: datetime | None, zone: ZoneInfo) -> str | None:
    return moment_in_words(moment.astimezone(zone)) if moment else None


def _signature(row: Row[Any] | None) -> Signature | None:
    if row is None:
        return None
    method = row.method
    adopted = "Drawn" if method == "drawn" else f"Typed, {font(row.font).family}"
    return Signature(
        method=method,
        text=row.text,
        font=row.font,
        strokes=row.strokes,
        signature_id=bytes(row.sha256).hex()[:16],
        adopted=adopted,
    )


def facts(
    uow: UnitOfWork,
    envelope_id: uuid.UUID,
    *,
    original_sha256: str,
    completed_sha256: str,
    completed_at: datetime,
) -> Certificate:
    session = uow.session
    envelope = session.execute(
        text(
            """
            SELECT e.id, e.title, e.time_zone, e.sent_at, e.version_id, d.name AS template,
                   jsonb_array_length(v.pages) AS pages, u.name AS sender, u.email AS sender_email,
                   w.name AS company
            FROM envelopes e
            JOIN documents d ON d.id = e.document_id
            JOIN document_versions v ON v.id = e.version_id
            JOIN users u ON u.id = e.sent_by
            JOIN workspaces w ON w.id = e.workspace_id
            WHERE e.id = :e
            """
        ),
        {"e": envelope_id},
    ).one()
    zone = ZoneInfo(envelope.time_zone)
    people = session.execute(
        text(
            """
            SELECT r.id, r.kind, r.name, r.email, r.sent_at, r.viewed_at, r.signed_at,
                   p.label AS party, c.consented_at, c.disclosure_version,
                   signed.ip, signed.verified_by
            FROM envelope_recipients r
            LEFT JOIN version_roles p ON p.id = r.party_id
            LEFT JOIN signing_consents c ON c.recipient_id = r.id
            -- The person's signing event, read once: the first on the envelope's chain (there is
            -- one, written with the guarded update that records them signed).
            LEFT JOIN LATERAL (
                SELECT a.ip, a.data ->> 'verified_by' AS verified_by FROM audit_events a
                WHERE a.subject_id = r.envelope_id AND a.action = 'signing.signed'
                  AND a.actor_id = r.id
                ORDER BY a.seq LIMIT 1
            ) signed ON true
            WHERE r.envelope_id = :e
            ORDER BY r.stage, r.position
            """
        ),
        {"e": envelope_id},
    ).all()
    marks = {
        (row.recipient_id, row.kind): row
        for row in session.execute(
            text(
                "SELECT s.recipient_id, s.kind, s.method, s.text, s.font, s.strokes, s.sha256 "
                "FROM signing_signatures s JOIN envelope_recipients r ON r.id = s.recipient_id "
                "WHERE r.envelope_id = :e"
            ),
            {"e": envelope_id},
        )
    }
    counts = session.execute(
        text(
            "SELECT count(*) FILTER (WHERE holds = 'signature') AS signatures, "
            "count(*) FILTER (WHERE holds = 'initials') AS initials "
            "FROM version_fields WHERE version_id = :v"
        ),
        {"v": envelope.version_id},
    ).one()

    signing = [p for p in people if p.kind in ("signer", "countersigner")]
    viewed = [p.viewed_at for p in signing if p.viewed_at]
    signers_done = [p.signed_at for p in signing if p.kind == "signer" and p.signed_at]
    accepted = {p.disclosure_version for p in signing if p.disclosure_version}
    return Certificate(
        envelope_id=envelope.id,
        title=envelope.title,
        template=envelope.template,
        pages=envelope.pages or 0,
        signatures=counts.signatures,
        initials=counts.initials,
        sent_by=f"{envelope.sender} ({envelope.sender_email})",
        time_zone=envelope.time_zone,
        people=[
            Signed(
                role=f"{'Signer' if p.kind == 'signer' else 'Countersigner'}"
                + (f" · {p.party}" if p.party else ""),
                name=p.name,
                email=p.email,
                verified_by=VERIFIED.get(p.verified_by or "", "Email link"),
                signature=_signature(marks.get((p.id, "signature"))),
                initials=_signature(marks.get((p.id, "initials"))),
                ip=str(p.ip) if p.ip else None,
                sent=_when(p.sent_at, zone),
                viewed=_when(p.viewed_at, zone),
                signed=_when(p.signed_at, zone),
                consented=_when(p.consented_at, zone),
                disclosure_version=p.disclosure_version,
            )
            for p in signing
        ],
        copies=[
            Copy(p.name, p.email, _when(completed_at, zone)) for p in people if p.kind == "copy"
        ],
        summary=[
            (event, when)
            for event, when in (
                ("Sent", _when(envelope.sent_at, zone)),
                ("First viewed", _when(min(viewed), zone) if viewed else None),
                ("Every signer signed", _when(max(signers_done), zone) if signers_done else None),
                ("Completed", _when(completed_at, zone)),
            )
            if when
        ],
        original_sha256=original_sha256,
        completed_sha256=completed_sha256,
        disclosures={
            version: [
                (paragraph.title, paragraph.text)
                for paragraph in consent.disclosure(envelope.company, envelope.sender_email)
            ]
            for version in sorted(accepted)
            if version == consent.VERSION
        },
    )
