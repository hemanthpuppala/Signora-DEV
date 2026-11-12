"""A member's actor as a request would see it, for tests that call a module's functions directly."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.domain.permissions import parse_permissions


class Member(Protocol):
    @property
    def email(self) -> str: ...
    @property
    def user_id(self) -> uuid.UUID: ...
    @property
    def workspace_id(self) -> uuid.UUID: ...


def actor_for(db: Database, account: Member) -> Actor:
    """The member's actor (role permissions from the database)."""
    with db.unit_of_work() as uow:
        row = uow.session.execute(
            text(
                "SELECT r.key, r.name, r.permissions FROM users u JOIN roles r ON r.id = u.role_id "
                "WHERE u.id = :u"
            ),
            {"u": account.user_id},
        ).one()
    return Actor(
        user_id=account.user_id,
        email=account.email,
        name="x",
        workspace_id=account.workspace_id,
        workspace_name="x",
        workspace_logo=None,
        role_id=uuid.uuid4(),
        role_key=row.key,
        role_name=row.name,
        role_description="",
        permissions=parse_permissions(row.permissions)[0],
        is_creator=False,
        session_digest=b"",
    )
