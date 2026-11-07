"""Idempotency keys for create actions (backbone LLD topic 3).

The key row is written inside the action's own transaction, before the work. A committed row
with the same fingerprint replays the stored response; an in-flight duplicate waits at most 2
seconds and then gets ``409`` with ``Retry-After``; a different fingerprint gets ``422``. The
2-second lock limit applies only to the key insert (LLD §3.4).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from signora.kernel.errors import IdempotencyKeyInvalid, IdempotencyKeyReused, RequestInProgress

KEY_LOCK_TIMEOUT = "2s"
RETRY_AFTER_SECONDS = 1
_KEY_PATTERN = re.compile(r"^[\x20-\x7e]{1,255}$")  # printable ASCII
_LOCK_NOT_AVAILABLE = "55P03"


def canonical_json(value: Any) -> bytes:
    """Stable bytes for hashing: sorted keys, no insignificant whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(value: Any) -> bytes:
    return hashlib.sha256(canonical_json(value)).digest()


def validate_key(key: str) -> str:
    if not _KEY_PATTERN.match(key):
        raise IdempotencyKeyInvalid
    return key


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: Any


def _is_lock_timeout(error: OperationalError) -> bool:
    return getattr(error.orig, "sqlstate", None) == _LOCK_NOT_AVAILABLE


def begin(session: Session, scope: str, key: str, request_hash: bytes) -> StoredResponse | None:
    """Reserve ``(scope, key)`` in the current transaction.

    Returns None when this request should run, or the stored response to replay.
    """
    session.execute(text(f"SET LOCAL lock_timeout = '{KEY_LOCK_TIMEOUT}'"))
    try:
        inserted = session.execute(
            text(
                """
                INSERT INTO idempotency_keys (scope, key, request_hash)
                VALUES (:scope, :key, :hash)
                ON CONFLICT (scope, key) DO NOTHING
                RETURNING 1
                """
            ),
            {"scope": scope, "key": key, "hash": request_hash},
        ).scalar_one_or_none()
    except OperationalError as error:
        if _is_lock_timeout(error):
            raise RequestInProgress(retry_after_seconds=RETRY_AFTER_SECONDS) from None
        raise
    # The 2 s cap must not apply to any later lock wait in this transaction.
    session.execute(text("SET LOCAL lock_timeout = DEFAULT"))
    if inserted is not None:
        return None

    stored = session.execute(
        text(
            """
            SELECT request_hash, response_status, response_body
            FROM idempotency_keys WHERE scope = :scope AND key = :key
            """
        ),
        {"scope": scope, "key": key},
    ).one()
    if bytes(stored.request_hash) != request_hash:
        raise IdempotencyKeyReused
    return StoredResponse(status=int(stored.response_status), body=stored.response_body)


def finish(session: Session, scope: str, key: str, status: int, body: Any) -> None:
    """Store the response with the key, in the same transaction as the work."""
    session.execute(
        text(
            """
            UPDATE idempotency_keys
            SET response_status = :status, response_body = CAST(:body AS jsonb)
            WHERE scope = :scope AND key = :key
            """
        ),
        {"status": status, "body": json.dumps(body), "scope": scope, "key": key},
    )
