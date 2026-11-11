"""To countersign (Phase 8 LLD §7.2): a Signora user's own countersigning, across their departments.

Two lists: what waits for them, soonest expiry first (the urgent first), and what they have
countersigned, latest first. Each is one index range on the countersigner's recipients
(``(user_id, status) WHERE kind = 'countersigner'``) with a keyset cursor: O(k) for a page of k.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text

from signora.kernel.db import Database
from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.identity_access import Actor, current_actor

router = APIRouter(prefix="/api/v1/me", tags=["signing"])
Member = Annotated[Actor, Depends(current_actor)]
PAGE = 50
State = Literal["waiting", "done"]

_FROM = """
    FROM envelope_recipients r
    JOIN envelopes e ON e.id = r.envelope_id
    JOIN documents d ON d.id = e.document_id
    JOIN departments dep ON dep.id = e.department_id
    WHERE r.kind = 'countersigner' AND r.user_id = :u
"""
# Waiting: their turn (every signer signed, the envelope open, before expiry), not yet signed.
_WAITING = (
    _FROM + " AND r.status IN ('sent', 'opened', 'viewed') AND e.status = 'signed' "
    "AND e.expires_at > now()"
)
_DONE = _FROM + " AND r.status = 'signed'"
# A search across what a row shows: its title, template, department and signers' names.
_SEARCH = """
    AND (CAST(:q AS text) IS NULL OR e.title ILIKE :q OR d.name ILIKE :q OR dep.name ILIKE :q
         OR EXISTS (SELECT 1 FROM envelope_recipients s WHERE s.envelope_id = e.id
                    AND s.kind = 'signer' AND s.name ILIKE :q))
"""


def _escape(words: str) -> str:
    """A search's own % and _ are letters, not patterns."""
    return words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# (order, cursor's comparison, the row's key) for each list.
_ORDER: dict[State, tuple[str, str, str]] = {
    "waiting": ("e.expires_at ASC, r.id ASC", "(e.expires_at, r.id) > (:at, :id)", "expires_at"),
    "done": ("r.signed_at DESC, r.id DESC", "(r.signed_at, r.id) < (:at, :id)", "countersigned_at"),
}


class Waiting(BaseModel):
    recipient_id: uuid.UUID
    envelope_id: uuid.UUID
    title: str
    document_name: str
    department_id: uuid.UUID
    department_name: str
    signers: list[str]
    signed_at: datetime | None  # when the last signer signed: since when it waits for them
    expires_at: datetime
    countersigned_at: datetime | None  # theirs, in the countersigned list
    completed: bool  # the signed copy is made


class WaitingPage(BaseModel):
    items: list[Waiting]
    next_cursor: str | None
    total: int  # how many match, across every page
    waiting: int  # how many wait for them (the first tab's count), whatever the search
    done: int  # how many they countersigned (the second tab's)


class WaitingCount(BaseModel):
    count: int


def _db(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def _cursor(raw: str | None) -> tuple[datetime, uuid.UUID] | None:
    if raw is None:
        return None
    try:
        at, _, ident = base64.urlsafe_b64decode(raw.encode()).decode().partition("|")
        return datetime.fromisoformat(at), uuid.UUID(ident)
    except ValueError:
        raise ValidationFailed([FieldError("cursor", "Not a page of this list")]) from None


@router.get(
    "/countersign",
    summary="My countersigning: what waits for me (soonest expiry first), or what I countersigned",
)
def waiting(
    request: Request,
    actor: Member,
    state: State = "waiting",
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> WaitingPage:
    after = _cursor(cursor)
    order, beyond, key = _ORDER[state]
    where = (_WAITING if state == "waiting" else _DONE) + _SEARCH
    needle = f"%{_escape(q.strip())}%" if q and q.strip() else None
    with _db(request).unit_of_work() as uow:
        rows = uow.session.execute(
            text(
                f"""
                SELECT r.id AS recipient_id, e.id AS envelope_id, e.title, d.name AS document_name,
                       e.department_id, dep.name AS department_name, e.expires_at,
                       r.signed_at AS countersigned_at, e.status = 'completed' AS completed,
                       (SELECT array_agg(s.name ORDER BY s.position) FROM envelope_recipients s
                        WHERE s.envelope_id = e.id AND s.kind = 'signer') AS signers,
                       (SELECT max(s.signed_at) FROM envelope_recipients s
                        WHERE s.envelope_id = e.id AND s.kind = 'signer') AS signed_at
                {where}
                  AND (CAST(:at AS timestamptz) IS NULL OR {beyond})
                ORDER BY {order}
                LIMIT :limit
                """  # noqa: S608 - every interpolated part is a constant of this module
            ),
            {
                "u": actor.user_id,
                "q": needle,
                "at": after[0] if after else None,
                "id": after[1] if after else None,
                "limit": PAGE + 1,
            },
        ).all()
        counts = uow.session.execute(
            text(
                f"SELECT (SELECT count(*) {where}) AS total, "
                f"(SELECT count(*) {_WAITING}) AS waiting, (SELECT count(*) {_DONE}) AS done"
            ),
            {"u": actor.user_id, "q": needle},
        ).one()
    more = len(rows) > PAGE
    shown = rows[:PAGE]
    last = shown[-1] if more else None
    return WaitingPage(
        items=[
            Waiting(
                recipient_id=row.recipient_id,
                envelope_id=row.envelope_id,
                title=row.title,
                document_name=row.document_name,
                department_id=row.department_id,
                department_name=row.department_name,
                signers=list(row.signers or []),
                signed_at=row.signed_at,
                expires_at=row.expires_at,
                countersigned_at=row.countersigned_at,
                completed=row.completed,
            )
            for row in shown
        ],
        next_cursor=base64.urlsafe_b64encode(
            f"{getattr(last, key).isoformat()}|{last.recipient_id}".encode()
        ).decode()
        if last
        else None,
        total=counts.total,
        waiting=counts.waiting,
        done=counts.done,
    )


@router.get("/countersign/count", summary="How many envelopes wait for my countersignature")
def waiting_count(request: Request, actor: Member) -> WaitingCount:
    with _db(request).unit_of_work() as uow:
        count = uow.session.execute(
            text(f"SELECT count(*) {_WAITING}"),
            {"u": actor.user_id},
        ).scalar_one()
    return WaitingCount(count=count)
