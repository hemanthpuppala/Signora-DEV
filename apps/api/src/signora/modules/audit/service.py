"""Recording and verifying audit entries (backbone LLD §4.3-4.5)."""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.context import current_origin
from signora.kernel.db import UnitOfWork
from signora.kernel.logging import current_context
from signora.modules.audit.domain import (
    GENESIS_HASH,
    Actor,
    AuditChain,
    AuditEntry,
    ChainKind,
    Subject,
    VerificationResult,
    canonical_ip,
    check_data,
    compute_hash,
)

_VERIFY_BATCH = 1000


def record(
    uow: UnitOfWork,
    *,
    chain: AuditChain,
    actor: Actor,
    action: str,
    subject: Subject | None = None,
    data: Mapping[str, Any] | None = None,
) -> AuditEntry:
    """Append an entry to ``chain`` inside the caller's transaction.

    The entry commits or rolls back together with the action. The request origin (request id, IP,
    user agent) is taken from the current request context when there is one.
    """
    payload = dict(data or {})
    check_data(payload)
    origin = current_origin()
    request_id = origin.request_id if origin else current_context().get("request_id")
    session = uow.session

    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": chain.lock_key})
    last = session.execute(
        text("SELECT seq, hash FROM audit_events WHERE chain_id = :c ORDER BY seq DESC LIMIT 1"),
        {"c": chain.chain_id},
    ).one_or_none()
    previous_seq, previous_hash = (last.seq, bytes(last.hash)) if last else (0, GENESIS_HASH)

    draft = AuditEntry(
        chain=chain,
        seq=previous_seq + 1,
        occurred_at=datetime.now(UTC),
        actor=actor,
        action=action,
        subject=subject,
        request_id=request_id,
        ip=canonical_ip(origin.ip) if origin else None,
        user_agent=origin.user_agent if origin else None,
        data=payload,
    )
    entry = dataclasses.replace(draft, hash=compute_hash(previous_hash, draft))
    session.execute(
        text(
            """
            INSERT INTO audit_events (chain_kind, chain_id, seq, workspace_id, occurred_at,
                actor_type, actor_id, actor_label, action, subject_type, subject_id,
                request_id, ip, user_agent, data, hash)
            VALUES (:chain_kind, :chain_id, :seq, :workspace_id, :occurred_at,
                :actor_type, :actor_id, :actor_label, :action, :subject_type, :subject_id,
                :request_id, CAST(:ip AS inet), :user_agent, CAST(:data AS jsonb), :hash)
            """
        ),
        {
            "chain_kind": chain.kind.value,
            "chain_id": chain.chain_id,
            "seq": entry.seq,
            "workspace_id": chain.workspace_id,
            "occurred_at": entry.occurred_at,
            "actor_type": actor.type,
            "actor_id": actor.id,
            "actor_label": actor.label,
            "action": action,
            "subject_type": subject.type if subject else None,
            "subject_id": subject.id if subject else None,
            "request_id": request_id,
            "ip": entry.ip,
            "user_agent": entry.user_agent,
            "data": json.dumps(payload),
            "hash": entry.hash,
        },
    )
    return entry


def _entry_from_row(row: Any) -> AuditEntry:
    chain = AuditChain(ChainKind(row.chain_kind), row.chain_id, row.workspace_id)
    return AuditEntry(
        chain=chain,
        seq=row.seq,
        occurred_at=row.occurred_at,
        actor=Actor(row.actor_type, row.actor_id, row.actor_label),
        action=row.action,
        subject=Subject(row.subject_type, row.subject_id) if row.subject_type else None,
        request_id=row.request_id,
        ip=str(row.ip) if row.ip is not None else None,
        user_agent=row.user_agent,
        data=row.data,
        hash=bytes(row.hash),
    )


def verify(
    session: Session,
    chain_id: uuid.UUID,
    *,
    expected_head: tuple[int, bytes] | None = None,
) -> VerificationResult:
    """Recompute every hash of the chain in order (O(n)).

    Detects changed entries and deleted entries in the middle (gaps). Deleting the newest entries
    leaves no gap; pass ``expected_head`` (a ``(seq, hash)`` anchored elsewhere, e.g. printed on a
    certificate) to detect that too.
    """
    previous_hash, expected_seq, checked = GENESIS_HASH, 1, 0
    last_seq = 0
    while True:
        rows = session.execute(
            text(
                "SELECT * FROM audit_events WHERE chain_id = :c AND seq > :after"
                " ORDER BY seq LIMIT :limit"
            ),
            {"c": chain_id, "after": last_seq, "limit": _VERIFY_BATCH},
        ).all()
        if not rows:
            break
        for row in rows:
            entry = _entry_from_row(row)
            if entry.seq != expected_seq:
                return VerificationResult(
                    False,
                    checked,
                    last_seq,
                    previous_hash,
                    expected_seq,
                    f"entry {expected_seq} is missing",
                )
            if compute_hash(previous_hash, entry) != entry.hash:
                return VerificationResult(
                    False,
                    checked,
                    last_seq,
                    previous_hash,
                    entry.seq,
                    f"entry {entry.seq} does not match its hash",
                )
            previous_hash, last_seq, checked = entry.hash, entry.seq, checked + 1
            expected_seq += 1

    if expected_head is not None:
        anchored_seq, anchored_hash = expected_head
        if last_seq < anchored_seq:
            return VerificationResult(
                False,
                checked,
                last_seq,
                previous_hash,
                last_seq + 1,
                f"chain ends at {last_seq} but entry {anchored_seq} was anchored (truncated)",
            )
        anchored = session.execute(
            text("SELECT hash FROM audit_events WHERE chain_id = :c AND seq = :s"),
            {"c": chain_id, "s": anchored_seq},
        ).scalar_one()
        if bytes(anchored) != anchored_hash:
            return VerificationResult(
                False,
                checked,
                last_seq,
                previous_hash,
                anchored_seq,
                f"entry {anchored_seq} differs from the anchored hash",
            )
    return VerificationResult(True, checked, last_seq, previous_hash)
