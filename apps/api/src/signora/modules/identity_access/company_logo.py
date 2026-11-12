"""A company's logo: looked up by its website's domain, kept as a blob of the workspace, served to
its members, and looked up again from time to time (Company logo LLD §4-§5).

Nothing here can stop a sign-up or a page from working: without a logo the header shows the
company's name, and every outcome below ends in a logo or in exactly that.

Every look-up ends by planning the next one in ``workspaces.logo_check_due_at``; a sweep queues
the look-ups that are due. The planned time is part of the job's dedupe key, so one planned check
is queued once however often it is asked for, and the next one can always be queued.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.blobstore import BlobRef, BlobStore
from signora.kernel.config import LogoSettings
from signora.kernel.jobs import JobContext, enqueue
from signora.kernel.logging import get_logger
from signora.modules.identity_access import logo_dev

log = get_logger("signora.identity")

FIND_LOGO = "identity.find_company_logo"
SWEEP = "sweep.company_logos"
SWEEP_EVERY = timedelta(minutes=15)
SWEEP_BATCH = 200
MAX_ATTEMPTS = 3  # for our own failures (database, disk); logo.dev's never fail the job
LEASE = timedelta(minutes=1)

# When to look again, by how the look-up ended.
AGAIN_WHEN_UNAVAILABLE = timedelta(hours=1)  # timed out, still indexing, rate-limited, down
AGAIN_WHEN_NONE = timedelta(days=7)  # no logo, or a refusal (key, credits)
AGAIN_WHEN_FOUND = timedelta(days=30)  # a refresh: downloads only when the logo changed
AGAIN_WITHOUT_KEY = timedelta(days=1)  # the key was removed after the job was queued


def plan_check(session: Session, workspace_id: uuid.UUID, *, queue: bool) -> None:
    """Make a look-up due now, and queue it unless ``queue`` is False (no key is configured:
    the sweep queues it once there is one). For a workspace with a website."""
    due = session.execute(
        text(
            "UPDATE workspaces SET logo_check_due_at = now() "
            "WHERE id = :w AND website IS NOT NULL RETURNING logo_check_due_at"
        ),
        {"w": workspace_id},
    ).scalar_one_or_none()
    if due is not None and queue:
        _queue(session, workspace_id, due)


def sweep(context: JobContext, *, settings: LogoSettings) -> None:
    """Queue the look-ups that are due (none without a key: they stay due until there is one)."""
    if not settings.configured:
        return
    with context.complete() as uow:
        due = uow.session.execute(
            text(
                "SELECT id, logo_check_due_at FROM workspaces "
                "WHERE logo_check_due_at <= now() ORDER BY logo_check_due_at LIMIT :n"
            ),
            {"n": SWEEP_BATCH},
        ).all()
        for row in due:
            _queue(uow.session, row.id, row.logo_check_due_at)


def find_and_keep(
    context: JobContext,
    *,
    settings: LogoSettings,
    store: BlobStore,
    client: httpx.Client | None = None,
) -> None:
    """Look the workspace's logo up, keep it if it is new, and plan the next look-up.

    logo.dev timing out or being unavailable skips this look-up: the company keeps what it shows
    (its logo or its name) and the next look-up is planned sooner.
    """
    workspace_id = uuid.UUID(context.payload["workspace_id"])
    with context.unit_of_work() as uow:
        row = uow.session.execute(
            text("SELECT website, logo_sha256, logo_etag FROM workspaces WHERE id = :w"),
            {"w": workspace_id},
        ).one_or_none()
    if row is None or row.website is None:
        return  # the website was removed since: nothing to look up
    domain: str = row.website
    if settings.secret_key is None:
        log.info("company_logo.not_configured")
        _plan_next(context, workspace_id, domain, AGAIN_WITHOUT_KEY)
        return
    http = client or logo_dev.client()
    try:
        found = logo_dev.look_up(domain, secret_key=settings.secret_key, client=http)
        if found is None:
            log.info("company_logo.none", domain=domain)
            _plan_next(context, workspace_id, domain, AGAIN_WHEN_NONE)
            return
        if row.logo_sha256 is not None and found.etag == row.logo_etag:
            _plan_next(context, workspace_id, domain, AGAIN_WHEN_FOUND)  # unchanged
            return
        png = logo_dev.download(found, client=http)
    except logo_dev.LogoDevUnavailableError as error:
        log.info("company_logo.skipped", domain=domain, reason=str(error))
        _plan_next(context, workspace_id, domain, AGAIN_WHEN_UNAVAILABLE)
        return
    finally:
        if client is None:
            http.close()
    if png is None:
        log.warning("company_logo.unusable_file", domain=domain)
        _plan_next(context, workspace_id, domain, AGAIN_WHEN_NONE)
        return
    ref = store.put(workspace_id, io.BytesIO(png), max_bytes=logo_dev.MAX_LOGO_BYTES)
    with context.complete() as uow:
        uow.session.execute(
            text(
                "UPDATE workspaces SET logo_sha256 = :sha, logo_bytes = :size, logo_etag = :etag, "
                "logo_check_due_at = now() + make_interval(secs => :again) "
                "WHERE id = :w AND website = :domain"
            ),
            {
                "sha": ref.sha256,
                "size": ref.size,
                "etag": found.etag,
                "again": AGAIN_WHEN_FOUND.total_seconds(),
                "w": workspace_id,
                "domain": domain,
            },
        )
    log.info("company_logo.kept", domain=domain, size=ref.size)


def logo_of(session: Session, workspace_id: uuid.UUID) -> BlobRef | None:
    """The workspace's logo, or ``None`` while it has none."""
    row = session.execute(
        text("SELECT logo_sha256, logo_bytes FROM workspaces WHERE id = :w"), {"w": workspace_id}
    ).one()
    if row.logo_sha256 is None:
        return None
    return BlobRef(workspace_id, row.logo_sha256, row.logo_bytes)


def forget_missing(session: Session, logo: BlobRef, *, queue: bool) -> None:
    """The logo's file is gone from the store: show the name and fetch the logo again."""
    session.execute(
        text(
            "UPDATE workspaces SET logo_sha256 = NULL, logo_bytes = NULL, logo_etag = NULL "
            "WHERE id = :w AND logo_sha256 = :sha"
        ),
        {"w": logo.workspace_id, "sha": logo.sha256},
    )
    log.warning("company_logo.file_missing", sha256=logo.sha256)
    plan_check(session, logo.workspace_id, queue=queue)


def _plan_next(context: JobContext, workspace_id: uuid.UUID, domain: str, after: timedelta) -> None:
    with context.complete() as uow:
        uow.session.execute(
            text(
                "UPDATE workspaces SET logo_check_due_at = now() + make_interval(secs => :again) "
                "WHERE id = :w AND website = :domain"
            ),
            {"again": after.total_seconds(), "w": workspace_id, "domain": domain},
        )


def _queue(session: Session, workspace_id: uuid.UUID, due: datetime) -> None:
    enqueue(
        session,
        FIND_LOGO,
        {"workspace_id": str(workspace_id)},
        dedupe_key=f"{FIND_LOGO}:{workspace_id}:{due.isoformat()}",
    )
