"""Invites (Phase 2 LLD topic 6).

Creating an invite answers the same way whether the address is new, already invited, a removed
member, or someone in another workspace (only "already a member here" differs, which the manager
can see anyway). Acceptance takes the address lock before the invite's row lock, the same order as
sign-up, so concurrent acceptances and sign-ups for one address cannot deadlock.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.config import AuthSettings
from signora.kernel.db import UnitOfWork
from signora.kernel.errors import Conflict, FieldError, NotFound, RateLimited, ValidationFailed
from signora.kernel.ratelimit import RateLimiter
from signora.modules.audit import AuditChain, Subject, record
from signora.modules.identity_access import accounts, emails
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.domain.passwords import PasswordPolicy, hash_password
from signora.modules.identity_access.domain.tokens import hash_token, issue_token
from signora.modules.identity_access.errors import (
    AlreadyMember,
    EmailInOtherWorkspace,
    LinkExpired,
)
from signora.modules.identity_access.signup import check_password, valid_email
from signora.modules.notifications import send_email

RESEND_COOLDOWN = timedelta(minutes=1)


@dataclass(frozen=True)
class InviteRow:
    id: uuid.UUID
    email: str
    role_id: uuid.UUID
    role_name: str
    invited_by_name: str
    created_at: datetime
    expires_at: datetime
    expired: bool


_LIST_SQL = """
    SELECT i.id, i.email, i.role_id, r.name AS role_name, u.name AS invited_by_name,
           i.created_at, i.expires_at, i.expires_at <= now() AS expired
    FROM invites i
    JOIN roles r ON r.id = i.role_id
    JOIN users u ON u.id = i.invited_by
    WHERE i.workspace_id = :w AND i.accepted_at IS NULL AND i.revoked_at IS NULL
"""


def list_pending(session: Session, workspace_id: uuid.UUID) -> list[InviteRow]:
    rows = session.execute(text(_LIST_SQL + " ORDER BY i.created_at DESC"), {"w": workspace_id})
    return [InviteRow(**row._mapping) for row in rows]


def _pending(session: Session, workspace_id: uuid.UUID, invite_id: uuid.UUID) -> InviteRow:
    row = session.execute(
        text(_LIST_SQL + " AND i.id = :id"), {"w": workspace_id, "id": invite_id}
    ).one_or_none()
    if row is None:
        raise NotFound
    return InviteRow(**row._mapping)


def _role_name(session: Session, workspace_id: uuid.UUID, role_id: uuid.UUID) -> str:
    name = session.execute(
        text("SELECT name FROM roles WHERE id = :r AND workspace_id = :w"),
        {"r": role_id, "w": workspace_id},
    ).scalar_one_or_none()
    if name is None:
        raise ValidationFailed([FieldError("role_id", "Choose one of this workspace's roles")])
    return str(name)


def _send_invitation(
    uow: UnitOfWork,
    *,
    actor: Actor,
    email: str,
    token: str,
    role_name: str,
    settings: AuthSettings,
    base_url: str,
) -> None:
    owner = accounts.find_user_by_email(uow.session, email)
    if owner is not None and owner.workspace_id != actor.workspace_id:
        message = emails.invitation_blocked(workspace=actor.workspace_name, inviter=actor.name)
    else:
        message = emails.invitation(
            base_url,
            token,
            workspace=actor.workspace_name,
            inviter=actor.name,
            role=role_name,
            days=settings.invite_days,
        )
    send_email(
        uow,
        to=email,
        subject=message.subject,
        text=message.body.text,
        html=message.body.html,
        category=message.category,
        workspace_id=actor.workspace_id,
    )


def _audit(uow: UnitOfWork, actor: Actor, action: str, invite_id: uuid.UUID, **data: Any) -> None:
    record(
        uow,
        chain=AuditChain.workspace(actor.workspace_id),
        actor=accounts.audit_actor(actor.user_id, actor.email),
        action=action,
        subject=Subject("invite", invite_id),
        data=data,
    )


def create_invite(
    uow: UnitOfWork,
    *,
    actor: Actor,
    limiter: RateLimiter,
    settings: AuthSettings,
    email: str,
    role_id: uuid.UUID,
    base_url: str,
) -> InviteRow:
    address = valid_email(email)
    role_name = _role_name(uow.session, actor.workspace_id, role_id)
    retry = limiter.hit(
        f"invite:ws:{actor.workspace_id}",
        limit=settings.invites_per_hour,
        window=timedelta(hours=1),
    )
    if retry is not None:
        raise RateLimited(retry)
    owner = accounts.find_user_by_email(uow.session, address)
    if owner is not None and owner.workspace_id == actor.workspace_id and owner.active:
        raise AlreadyMember

    token = issue_token()
    ttl = {"ttl": timedelta(days=settings.invite_days).total_seconds()}
    existing = uow.session.execute(
        text(
            "SELECT id FROM invites WHERE workspace_id = :w AND email = :e "
            "AND accepted_at IS NULL AND revoked_at IS NULL FOR UPDATE"
        ),
        {"w": actor.workspace_id, "e": address},
    ).scalar_one_or_none()
    if existing is not None:  # inviting again = resend: new link, old one dead, new expiry
        uow.session.execute(
            text(
                "UPDATE invites SET token_hash = :h, role_id = :r, invited_by = :by, "
                "expires_at = now() + make_interval(secs => :ttl) WHERE id = :id"
            ),
            {"h": token.digest, "r": role_id, "by": actor.user_id, "id": existing, **ttl},
        )
        invite_id: uuid.UUID = existing
        _audit(uow, actor, "invite.resent", invite_id, email=address)
    else:
        invite_id = uow.session.execute(
            text(
                "INSERT INTO invites (workspace_id, email, role_id, token_hash, invited_by, "
                "expires_at) VALUES (:w, :e, :r, :h, :by, now() + make_interval(secs => :ttl)) "
                "RETURNING id"
            ),
            {
                "w": actor.workspace_id,
                "e": address,
                "r": role_id,
                "h": token.digest,
                "by": actor.user_id,
                **ttl,
            },
        ).scalar_one()
        _audit(uow, actor, "invite.created", invite_id, email=address, role=role_name)
    _send_invitation(
        uow,
        actor=actor,
        email=address,
        token=token.value,
        role_name=role_name,
        settings=settings,
        base_url=base_url,
    )
    return _pending(uow.session, actor.workspace_id, invite_id)


def resend_invite(
    uow: UnitOfWork,
    *,
    actor: Actor,
    limiter: RateLimiter,
    settings: AuthSettings,
    invite_id: uuid.UUID,
    base_url: str,
) -> InviteRow:
    invite = _pending(uow.session, actor.workspace_id, invite_id)
    retry = limiter.hit(f"invite:resend:{invite_id}", limit=1, window=RESEND_COOLDOWN)
    if retry is not None:
        raise RateLimited(retry)
    token = issue_token()
    uow.session.execute(
        text(
            "UPDATE invites SET token_hash = :h, expires_at = now() + make_interval(secs => :ttl) "
            "WHERE id = :id"
        ),
        {
            "h": token.digest,
            "id": invite_id,
            "ttl": timedelta(days=settings.invite_days).total_seconds(),
        },
    )
    _audit(uow, actor, "invite.resent", invite_id, email=invite.email)
    _send_invitation(
        uow,
        actor=actor,
        email=invite.email,
        token=token.value,
        role_name=invite.role_name,
        settings=settings,
        base_url=base_url,
    )
    return _pending(uow.session, actor.workspace_id, invite_id)


def revoke_invite(uow: UnitOfWork, *, actor: Actor, invite_id: uuid.UUID) -> None:
    """Idempotent: revoking a revoked invite succeeds; an accepted one cannot be revoked."""
    row = uow.session.execute(
        text(
            "SELECT email, accepted_at, revoked_at FROM invites "
            "WHERE id = :id AND workspace_id = :w FOR UPDATE"
        ),
        {"id": invite_id, "w": actor.workspace_id},
    ).one_or_none()
    if row is None:
        raise NotFound
    if row.revoked_at is not None:
        return
    if row.accepted_at is not None:
        raise Conflict("This invitation was already accepted")
    uow.session.execute(
        text("UPDATE invites SET revoked_at = now() WHERE id = :id"), {"id": invite_id}
    )
    _audit(uow, actor, "invite.revoked", invite_id, email=row.email)


@dataclass(frozen=True)
class InviteDetails:
    email: str
    workspace_name: str
    role_name: str
    inviter_name: str


_LIVE_SQL = """
    SELECT i.id, i.workspace_id, i.email, i.role_id, w.name AS workspace_name,
           r.name AS role_name, u.name AS inviter_name
    FROM invites i
    JOIN workspaces w ON w.id = i.workspace_id
    JOIN roles r ON r.id = i.role_id
    JOIN users u ON u.id = i.invited_by
    WHERE i.token_hash = :h AND i.accepted_at IS NULL AND i.revoked_at IS NULL
      AND i.expires_at > now()
"""


def _live(session: Session, token: str, *, lock: bool = False) -> Any:
    row = session.execute(
        text(_LIVE_SQL + (" FOR UPDATE OF i" if lock else "")), {"h": hash_token(token)}
    ).one_or_none()
    if row is None:
        raise LinkExpired
    return row


def verify_invite(uow: UnitOfWork, token: str) -> InviteDetails:
    row = _live(uow.session, token)
    return InviteDetails(row.email, row.workspace_name, row.role_name, row.inviter_name)


def accept_invite(
    uow: UnitOfWork, *, policy: PasswordPolicy, token: str, name: str, password: str
) -> str:
    """Create the member, or restore a removed member of this workspace; returns the email."""
    accounts.lock_email(uow.session, _live(uow.session, token).email)  # lock order: address first
    invite = _live(uow.session, token, lock=True)
    owner = accounts.find_user_by_email(uow.session, invite.email)
    if owner is not None and owner.workspace_id != invite.workspace_id:
        raise EmailInOtherWorkspace
    if owner is not None and owner.active:
        raise AlreadyMember
    check_password(policy, password)
    password_hash = hash_password(password)
    if owner is not None:
        uow.session.execute(
            text(
                "UPDATE users SET name = :n, role_id = :r, password_hash = :h, "
                "password_changed_at = now(), deactivated_at = NULL WHERE id = :u"
            ),
            {"n": name, "r": invite.role_id, "h": password_hash, "u": owner.id},
        )
        user_id, action = owner.id, "member.restored"
    else:
        user_id = uow.session.execute(
            text(
                "INSERT INTO users (workspace_id, role_id, email, name, password_hash) "
                "VALUES (:w, :r, :e, :n, :h) RETURNING id"
            ),
            {
                "w": invite.workspace_id,
                "r": invite.role_id,
                "e": invite.email,
                "n": name,
                "h": password_hash,
            },
        ).scalar_one()
        action = "member.joined"
    uow.session.execute(
        text("UPDATE invites SET accepted_at = now() WHERE id = :id"), {"id": invite.id}
    )
    record(
        uow,
        chain=AuditChain.workspace(invite.workspace_id),
        actor=accounts.audit_actor(user_id, invite.email),
        action=action,
        subject=Subject("user", user_id),
        data={"role": invite.role_name, "invite_id": str(invite.id)},
    )
    return str(invite.email)
