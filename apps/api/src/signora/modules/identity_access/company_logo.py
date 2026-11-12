"""A company's logo: found after sign-up by a background job, kept as a blob of the workspace,
served to its members (Company logo LLD §4-§5).

Nothing here can stop a sign-up or a page from working: without a logo the header shows the
company's name, and every failure below ends in exactly that.
"""

from __future__ import annotations

import io
import uuid
from datetime import timedelta

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
# logo.dev asks for 30 s while it indexes a new brand; backoff (30 s doubling) covers ~30 min.
MAX_ATTEMPTS = 7
LEASE = timedelta(minutes=1)


def request_logo(session: Session, *, workspace_id: uuid.UUID, domain: str) -> None:
    """Queue the look-up in the caller's transaction (it runs once the workspace exists)."""
    enqueue(
        session,
        FIND_LOGO,
        {"workspace_id": str(workspace_id), "domain": domain},
        dedupe_key=f"{FIND_LOGO}:{workspace_id}:{domain}",
    )


def find_and_keep(
    context: JobContext,
    *,
    settings: LogoSettings,
    store: BlobStore,
    client: httpx.Client | None = None,
) -> None:
    """Look the domain's logo up and keep it on the workspace, if its website is still that domain.

    ``logo_dev.LogoDevUnavailableError`` propagates, so the job is tried again with backoff.
    """
    if settings.secret_key is None:
        log.info("company_logo.not_configured")
        return
    workspace_id = uuid.UUID(context.payload["workspace_id"])
    domain: str = context.payload["domain"]
    http = client or logo_dev.client()
    try:
        logo = logo_dev.find_logo(domain, secret_key=settings.secret_key, client=http)
    finally:
        if client is None:
            http.close()
    if logo is None:
        log.info("company_logo.none", domain=domain)
        return
    ref = store.put(workspace_id, io.BytesIO(logo.png), max_bytes=logo_dev.MAX_LOGO_BYTES)
    with context.complete() as uow:
        uow.session.execute(
            text(
                "UPDATE workspaces SET logo_sha256 = :sha, logo_bytes = :size, logo_etag = :etag "
                "WHERE id = :w AND website = :domain"
            ),
            {
                "sha": ref.sha256,
                "size": ref.size,
                "etag": logo.etag,
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
