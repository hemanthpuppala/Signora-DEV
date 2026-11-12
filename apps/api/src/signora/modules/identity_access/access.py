"""Who is calling and what they may do (Phase 2 LLD §4.2, §8.1)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from signora.kernel.errors import PermissionDenied
from signora.kernel.logging import get_logger
from signora.modules.identity_access.domain.permissions import (
    ALL_PERMISSIONS,
    Permission,
    parse_permissions,
)

log = get_logger("signora.identity")
_reported_unknown: set[str] = set()


@dataclass(frozen=True)
class Actor:
    """The signed-in user of this request. ``workspace_id`` always comes from here."""

    user_id: uuid.UUID
    email: str
    name: str
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_logo: str | None  # the logo's sha256 while the company has one
    role_id: uuid.UUID
    role_key: str
    role_name: str
    role_description: str
    permissions: frozenset[Permission]
    is_creator: bool
    session_digest: bytes

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


def effective_permissions(stored: Iterable[str], *, is_creator: bool) -> frozenset[Permission]:
    """The role's permissions; the creator holds every permission (a code rule, not data)."""
    if is_creator:
        return ALL_PERMISSIONS
    known, unknown = parse_permissions(stored)
    for value in unknown - _reported_unknown:
        _reported_unknown.add(value)
        log.warning("roles.unknown_permission_ignored", permission=value)
    return known


def authorize(actor: Actor, permission: Permission) -> None:
    if not actor.can(permission):
        raise PermissionDenied
