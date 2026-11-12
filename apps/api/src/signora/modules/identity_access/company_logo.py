"""Company logos, one per domain (Company logo LLD §4-§5, revised): looked up on logo.dev by the
website's registrable domain, kept once in the system's store, shared by every company on that
domain and kept when they are gone. A company on a known domain shows its logo at once: logo.dev
is asked only for a domain not known yet, or to refresh one still in use.

Nothing here can stop a sign-up or a page from working: without a logo the header shows the
company's name, and every outcome below ends in a logo or in exactly that.

Every look-up ends by planning the next one in ``company_logos.check_due_at``; a sweep queues the
look-ups due for domains in use. The planned time is part of the job's dedupe key, so one planned
check is queued once however often it is asked for, and the next one can always be queued.
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
from signora.modules.identity_access.models import SYSTEM_WORKSPACE

log = get_logger("signora.identity")

FIND_LOGO = "identity.find_company_logo"
SWEEP = "sweep.company_logos"
SWEEP_EVERY = timedelta(minutes=15)
SWEEP_BATCH = 200
MAX_ATTEMPTS = 3  # for our own failures (database, disk); logo.dev's never fail the job
LEASE = timedelta(minutes=1)
# A look-up not finished this long after it was queued is taken as lost (its job dead, or the
# queue lost it): the domain comes due again and the sweep queues it anew.
LOST_AFTER = timedelta(minutes=30)
# Logos are brand marks, not any company's data: kept in the system's store, served to members.
STORE = uuid.UUID(SYSTEM_WORKSPACE)

# When to look again, by how the look-up ended.
AGAIN_WHEN_UNAVAILABLE = timedelta(hours=1)  # timed out, still indexing, rate-limited, down
AGAIN_WHEN_NONE = timedelta(days=7)  # no logo, or a refusal (key, credits)
AGAIN_WHEN_FOUND = timedelta(days=30)  # a refresh: downloads only when the logo changed
AGAIN_WITHOUT_KEY = timedelta(days=1)  # the key was removed after the job was queued
# logo.dev is indexing a domain new to it (202): asked again shortly, at most this many times,
# each wait longer; still indexing after them, the next look-up is the unavailable one's (an hour).
INDEXING_BACKOFF = (timedelta(seconds=10), timedelta(seconds=30), timedelta(seconds=90))


def want_logo(session: Session, domain: str, *, workspace_id: uuid.UUID, queue: bool) -> None:
    """A company now names ``domain`` as its website: make sure the domain's logo is there.

    - Unknown domain: a look-up is due now.
    - Another company is on it: its schedule stands (the logo, or a look-up already planned).
    - Known, back in use after being left: a kept logo shows at once and is refreshed a month on;
      "none found" is asked again once that answer is a week old.

    A look-up due now is queued unless ``queue`` is False (no key: the sweep queues it later).
    """
    due: datetime | None = session.execute(
        text(
            """
            INSERT INTO company_logos AS c (domain, check_due_at) VALUES (:d, now())
            ON CONFLICT (domain) DO UPDATE SET check_due_at = CASE
                WHEN EXISTS (SELECT 1 FROM workspaces w WHERE w.website = c.domain
                             AND w.id <> :w) THEN c.check_due_at
                WHEN c.logo_sha256 IS NOT NULL
                    THEN now() + make_interval(secs => :found)
                ELSE COALESCE(c.checked_at + make_interval(secs => :none), now())
            END
            RETURNING CASE WHEN c.check_due_at <= now() THEN c.check_due_at END
            """
        ),
        {
            "d": domain,
            "w": workspace_id,
            "found": AGAIN_WHEN_FOUND.total_seconds(),
            "none": AGAIN_WHEN_NONE.total_seconds(),
        },
    ).scalar_one()
    if due is not None and queue:
        _queue(session, domain)


def sweep(context: JobContext, *, settings: LogoSettings) -> None:
    """Queue the look-ups due for domains in use (none without a key: they stay due until there is
    one). A domain no company uses any more is left as it is, with no look-up planned, until a
    company names it again (``want_logo``)."""
    if not settings.configured:
        return
    with context.complete() as uow:
        uow.session.execute(
            text(
                "UPDATE company_logos c SET check_due_at = NULL WHERE check_due_at <= now() "
                "AND NOT EXISTS (SELECT 1 FROM workspaces w WHERE w.website = c.domain)"
            )
        )
        due = uow.session.execute(
            text(
                "SELECT domain FROM company_logos "
                "WHERE check_due_at <= now() ORDER BY check_due_at LIMIT :n"
            ),
            {"n": SWEEP_BATCH},
        ).scalars()
        for domain in due:
            _queue(uow.session, domain)


def find_and_keep(
    context: JobContext,
    *,
    settings: LogoSettings,
    store: BlobStore,
    client: httpx.Client | None = None,
) -> None:
    """Look the domain's logo up, keep it if it is new, and plan the next look-up.

    logo.dev timing out or being unavailable skips this look-up: every company on the domain keeps
    what it shows (the logo or its name) and the next look-up is planned sooner.
    """
    domain: str = context.payload["domain"]
    indexing_tries = int(context.payload.get("indexing", 0))  # 202s answered in a row
    with context.unit_of_work() as uow:
        row = uow.session.execute(
            text(
                "SELECT c.logo_sha256, c.etag, "
                "EXISTS (SELECT 1 FROM workspaces w WHERE w.website = c.domain) AS used "
                "FROM company_logos c WHERE c.domain = :d"
            ),
            {"d": domain},
        ).one_or_none()
    if row is None or not row.used:
        return  # no company names it any more: nothing to refresh
    if settings.secret_key is None:
        log.info("company_logo.not_configured")
        _plan_next(context, domain, AGAIN_WITHOUT_KEY, answered=False)
        return
    http = client or logo_dev.client()
    try:
        found = logo_dev.look_up(domain, secret_key=settings.secret_key, client=http)
        if found is None:
            log.info("company_logo.none", domain=domain)
            _plan_next(context, domain, AGAIN_WHEN_NONE, answered=True)
            return
        if row.logo_sha256 is not None and found.etag == row.etag:
            _plan_next(context, domain, AGAIN_WHEN_FOUND, answered=True)  # unchanged
            return
        png = logo_dev.download(found, client=http)
    except logo_dev.LogoDevIndexingError:
        if indexing_tries < len(INDEXING_BACKOFF):
            wait = INDEXING_BACKOFF[indexing_tries]
            log.info("company_logo.indexing", domain=domain, retry_in=wait.total_seconds())
            _retry_soon(context, domain, wait, tries=indexing_tries + 1)
        else:
            log.info("company_logo.still_indexing", domain=domain)
            _plan_next(context, domain, AGAIN_WHEN_UNAVAILABLE, answered=False)
        return
    except logo_dev.LogoDevUnavailableError as error:
        log.info("company_logo.skipped", domain=domain, reason=str(error))
        _plan_next(context, domain, AGAIN_WHEN_UNAVAILABLE, answered=False)
        return
    finally:
        if client is None:
            http.close()
    if png is None:
        log.warning("company_logo.unusable_file", domain=domain)
        _plan_next(context, domain, AGAIN_WHEN_NONE, answered=True)
        return
    ref = store.put(STORE, io.BytesIO(png), max_bytes=logo_dev.MAX_LOGO_BYTES)
    with context.complete() as uow:
        uow.session.execute(
            text(
                "UPDATE company_logos SET logo_sha256 = :sha, logo_bytes = :size, etag = :etag, "
                "checked_at = now(), check_due_at = now() + make_interval(secs => :again) "
                "WHERE domain = :d"
            ),
            {
                "sha": ref.sha256,
                "size": ref.size,
                "etag": found.etag,
                "again": AGAIN_WHEN_FOUND.total_seconds(),
                "d": domain,
            },
        )
    log.info("company_logo.kept", domain=domain, size=ref.size)


def logo_of(session: Session, workspace_id: uuid.UUID) -> tuple[str, BlobRef] | None:
    """The company's logo (the one kept for its website's domain) with that domain, or ``None``
    while there is none."""
    row = session.execute(
        text(
            "SELECT c.domain, c.logo_sha256, c.logo_bytes FROM workspaces w "
            "JOIN company_logos c ON c.domain = w.website WHERE w.id = :w"
        ),
        {"w": workspace_id},
    ).one_or_none()
    if row is None or row.logo_sha256 is None:
        return None
    return row.domain, BlobRef(STORE, row.logo_sha256, row.logo_bytes)


def forget_missing(session: Session, domain: str, logo: BlobRef, *, queue: bool) -> None:
    """The logo's file is gone from the store: every company on the domain shows its name, and
    the logo is fetched again."""
    due: datetime | None = session.execute(
        text(
            "UPDATE company_logos SET logo_sha256 = NULL, logo_bytes = NULL, etag = NULL, "
            "check_due_at = now() WHERE domain = :d AND logo_sha256 = :sha RETURNING check_due_at"
        ),
        {"d": domain, "sha": logo.sha256},
    ).scalar_one_or_none()
    log.warning("company_logo.file_missing", sha256=logo.sha256)
    if due is not None and queue:
        _queue(session, domain)


def _plan_next(context: JobContext, domain: str, after: timedelta, *, answered: bool) -> None:
    """The next look-up; ``answered``: logo.dev gave an answer (a logo or none) just now."""
    with context.complete() as uow:
        uow.session.execute(
            text(
                "UPDATE company_logos SET check_due_at = now() + make_interval(secs => :again), "
                "checked_at = CASE WHEN :answered THEN now() ELSE checked_at END WHERE domain = :d"
            ),
            {"again": after.total_seconds(), "answered": answered, "d": domain},
        )


def _retry_soon(context: JobContext, domain: str, wait: timedelta, *, tries: int) -> None:
    """logo.dev is indexing the domain: ask again after ``wait``, queued now to run then (the
    sweep's quarter-hour would be too late), and planned so a lost job is still picked up."""
    with context.complete() as uow:
        _queue(uow.session, domain, run_after=wait, indexing=tries)


def _queue(
    session: Session, domain: str, *, run_after: timedelta | None = None, indexing: int = 0
) -> None:
    """Queue a look-up of ``domain`` (to run after ``run_after``), claiming it: its next look-up
    moves to when this one should have finished (``LOST_AFTER`` past its start). A look-up queued
    is never queued twice; one lost (its job dead or gone) comes due again then and is queued
    anew; one that finishes plans the real next look-up. The claimed time is the job's dedupe key,
    so a new claim is a new key: never the key of a job that died."""
    wait = run_after.total_seconds() if run_after else 0.0
    claimed: datetime = session.execute(
        text(
            "UPDATE company_logos SET check_due_at = now() + make_interval(secs => :until) "
            "WHERE domain = :d RETURNING check_due_at"
        ),
        {"until": wait + LOST_AFTER.total_seconds(), "d": domain},
    ).scalar_one()
    payload: dict[str, object] = {"domain": domain}
    if indexing:
        payload["indexing"] = indexing
    enqueue(
        session,
        FIND_LOGO,
        payload,
        run_after=run_after,
        dedupe_key=f"{FIND_LOGO}:{domain}:{claimed.isoformat()}",
    )
