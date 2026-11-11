"""Queueing and delivering email (Phase 2 LLD §1a).

``send_email`` records the message and enqueues its delivery job in the caller's transaction, so a
rolled-back action sends nothing. The job hands the message to the configured transport and records
the outcome; a final message keeps no body (it held sign-in links).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from typing import Any

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobRef, BlobStore, blob_store_from_settings
from signora.kernel.config import get_settings
from signora.kernel.db import UnitOfWork
from signora.kernel.jobs import JobContext, JobKind, JobRegistry, RecurringJob, enqueue
from signora.kernel.logging import get_logger
from signora.modules.notifications.transports import (
    Attachment,
    OutgoingEmail,
    PermanentEmailError,
    TransientEmailError,
    Transport,
    transport_from_settings,
)

log = get_logger("signora.notifications")

DELIVER = "notifications.send_email"
SWEEP = "sweep.email_messages"
MAX_ATTEMPTS = 8
RETENTION = timedelta(days=30)
DEFERRAL_MINIMUM = timedelta(minutes=1)
DEFERRAL_FALLBACK = timedelta(hours=1)  # limit reached with nothing sent today (limit set to 0)
LAST_ERROR_MAX = 2000

TransportFactory = Callable[[], Transport]
DailyLimit = Callable[[], int]


@cache
def _default_transport() -> Transport:
    """Built once per process and shared: the SendGrid HTTP client is thread-safe and keeps its
    connection pool, instead of one unclosed client per email."""
    return transport_from_settings(get_settings().email)


def _default_daily_limit() -> int:
    return get_settings().email.daily_limit


@dataclass(frozen=True)
class AttachedFile:
    """A file an email carries: a stored object of the email's workspace."""

    blob: BlobRef
    filename: str
    content_type: str = "application/pdf"


def send_email(
    uow: UnitOfWork,
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    category: str,
    workspace_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    reply_to: str | None = None,
    attachments: Sequence[AttachedFile] = (),
) -> uuid.UUID | None:
    """Queue one email. Returns its id, or ``None`` when ``dedupe_key`` was already used. Its
    files are kept as blob references in its workspace, read when it is delivered (Phase 8)."""
    row = uow.session.execute(
        sql(
            """
            INSERT INTO email_messages
                (workspace_id, category, to_address, subject, text_body, html_body, dedupe_key,
                 reply_to)
            VALUES (:workspace_id, :category, :to, :subject, :text, :html, :dedupe_key, :reply_to)
            ON CONFLICT (dedupe_key) DO NOTHING
            RETURNING id
            """
        ),
        {
            "workspace_id": workspace_id,
            "category": category,
            "to": to,
            "subject": subject,
            "text": text,
            "html": html,
            "dedupe_key": dedupe_key,
            "reply_to": reply_to,
        },
    ).one_or_none()
    if row is None:
        return None
    message_id: uuid.UUID = row.id
    if attachments:
        uow.session.execute(
            sql(
                """
                INSERT INTO email_attachments (email_id, position, blob_key, filename, content_type)
                SELECT :id, n, key, name, kind
                FROM unnest(CAST(:keys AS text[]), CAST(:names AS text[]), CAST(:kinds AS text[]))
                     WITH ORDINALITY AS t(key, name, kind, n)
                """
            ),
            {
                "id": message_id,
                "keys": [item.blob.token for item in attachments],
                "names": [item.filename for item in attachments],
                "kinds": [item.content_type for item in attachments],
            },
        )
    enqueue(uow.session, DELIVER, {"message_id": str(message_id)}, dedupe_key=f"email:{message_id}")
    log.info("email.queued", message_id=str(message_id), category=category)
    return message_id


def _mark_sent(session: Session, message_id: str, provider: str, provider_message_id: str) -> None:
    session.execute(
        sql(
            """
            UPDATE email_messages
            SET status = 'sent', sent_at = now(), text_body = NULL, html_body = NULL,
                attempts = attempts + 1, provider = :provider,
                provider_message_id = :provider_message_id
            WHERE id = :id AND status = 'queued'
            """
        ),
        {"id": message_id, "provider": provider, "provider_message_id": provider_message_id},
    )


def _mark_failed(session: Session, message_id: str, error: str) -> None:
    session.execute(
        sql(
            """
            UPDATE email_messages
            SET status = 'failed', failed_at = now(), text_body = NULL, html_body = NULL,
                attempts = attempts + 1, last_error = :error
            WHERE id = :id AND status = 'queued'
            """
        ),
        {"id": message_id, "error": error[:LAST_ERROR_MAX]},
    )


def _defer_until_capacity(session: Session, message_id: str, job_id: uuid.UUID) -> int:
    """Queue this message's delivery again for when the oldest send of the last 24 hours ages out
    (at least a minute away). Returns the wait in seconds."""
    wait: float | None = session.execute(
        sql(
            "SELECT extract(epoch FROM min(sent_at) + interval '24 hours' - now()) "
            "FROM email_messages WHERE status = 'sent' AND sent_at > now() - interval '24 hours'"
        )
    ).scalar_one()
    seconds = max(
        int(wait or DEFERRAL_FALLBACK.total_seconds()), int(DEFERRAL_MINIMUM.total_seconds())
    )
    session.execute(
        sql("UPDATE email_messages SET last_error = :note WHERE id = :id AND status = 'queued'"),
        {"id": message_id, "note": "waiting for daily email capacity"},
    )
    enqueue(
        session,
        DELIVER,
        {"message_id": message_id},
        run_after=timedelta(seconds=seconds),
        dedupe_key=f"email:{message_id}:deferred:{job_id}",
    )
    return seconds


def _record_attempt(session: Session, message_id: str, error: str) -> None:
    session.execute(
        sql(
            "UPDATE email_messages SET attempts = attempts + 1, last_error = :error "
            "WHERE id = :id AND status = 'queued'"
        ),
        {"id": message_id, "error": error[:LAST_ERROR_MAX]},
    )


def _default_store() -> BlobStore:
    return blob_store_from_settings(get_settings().blob_store)


def _attached(
    store: BlobStore, workspace_id: uuid.UUID | None, files: Sequence[Any]
) -> tuple[Attachment, ...]:
    """An email's files, read from the store as it is sent (never kept in the email itself)."""
    if not files or workspace_id is None:
        return ()
    out = []
    for item in files:
        with store.open(BlobRef.from_token(workspace_id, item.blob_key)) as source:
            out.append(Attachment(item.filename, item.content_type, source.read()))
    return tuple(out)


def make_deliver(
    transport_factory: TransportFactory = _default_transport,
    daily_limit: DailyLimit = _default_daily_limit,
    blob_store: Callable[[], BlobStore] = _default_store,
) -> Callable[[JobContext], None]:
    """The delivery handler; tests pass a fake transport."""

    def deliver(context: JobContext) -> None:
        message_id = context.payload["message_id"]
        bind = {"message_id": message_id, "attempt": context.attempt}
        with context.unit_of_work() as uow:
            message = uow.session.execute(
                sql(
                    "SELECT to_address, subject, text_body, html_body, category, status, reply_to, "
                    "workspace_id FROM email_messages WHERE id = :id"
                ),
                {"id": message_id},
            ).one_or_none()
            files = uow.session.execute(
                sql(
                    "SELECT blob_key, filename, content_type FROM email_attachments "
                    "WHERE email_id = :id ORDER BY position"
                ),
                {"id": message_id},
            ).all()
            sent_today = uow.session.execute(
                sql(
                    "SELECT count(*) FROM email_messages "
                    "WHERE status = 'sent' AND sent_at > now() - interval '24 hours'"
                )
            ).scalar_one()
        if message is None or message.status != "queued":
            with context.complete():
                return

        if sent_today >= daily_limit():
            # Not a failure: wait for capacity without using up attempts (the provider's daily cap
            # is never exceeded and the message is never dropped).
            with context.complete() as uow:
                wait = _defer_until_capacity(uow.session, message_id, context.job_id)
            log.warning("email.deferred_daily_limit", sent_today=sent_today, wait_s=wait, **bind)
            return

        try:
            transport = transport_factory()
            provider_id = transport.send(
                OutgoingEmail(
                    to=message.to_address,
                    subject=message.subject,
                    text=message.text_body,
                    html=message.html_body,
                    message_id=message_id,
                    reply_to=message.reply_to,
                    attachments=_attached(blob_store(), message.workspace_id, files),
                )
            )
        except PermanentEmailError as error:
            log.error("email.failed", category=message.category, error=str(error), **bind)
            with context.complete() as uow:
                _mark_failed(uow.session, message_id, str(error))
            return
        except TransientEmailError as error:
            if context.attempt >= MAX_ATTEMPTS:
                log.error("email.failed", category=message.category, error=str(error), **bind)
                with context.complete() as uow:
                    _mark_failed(uow.session, message_id, str(error))
                return
            log.warning("email.retrying", category=message.category, error=str(error), **bind)
            with context.unit_of_work() as uow:
                _record_attempt(uow.session, message_id, str(error))
            raise

        with context.complete() as uow:
            _mark_sent(uow.session, message_id, transport.name, provider_id)
        log.info("email.sent", category=message.category, provider=transport.name, **bind)

    return deliver


def purge_old_messages(context: JobContext) -> None:
    """Delete final messages after the retention period (bodies are already gone)."""
    with context.complete() as uow:
        uow.session.execute(
            sql(
                "DELETE FROM email_messages WHERE status <> 'queued' "
                "AND created_at < now() - make_interval(secs => :retention)"
            ),
            {"retention": RETENTION.total_seconds()},
        )


# Built once, so registering the default handler again (every API app factory call) is a no-op.
_default_deliver = make_deliver()


def register(
    jobs_registry: JobRegistry,
    *,
    transport_factory: TransportFactory | None = None,
    daily_limit: DailyLimit | None = None,
) -> RecurringJob:
    """Register delivery and the retention sweep. Tests pass a fake transport or daily limit."""
    custom = transport_factory is not None or daily_limit is not None
    handler = (
        make_deliver(transport_factory or _default_transport, daily_limit or _default_daily_limit)
        if custom
        else _default_deliver
    )
    jobs_registry.register(
        JobKind(
            DELIVER,
            handler,
            max_attempts=MAX_ATTEMPTS,
            lease=timedelta(minutes=2),
        )
    )
    jobs_registry.register(
        JobKind(SWEEP, purge_old_messages, max_attempts=3, lease=timedelta(minutes=2))
    )
    return RecurringJob(SWEEP, every=timedelta(hours=1))
