"""Permission catalogue and default roles (Phase 2 LLD topic 8, ADR-A1).

The catalogue is code: each permission marks a place where the code checks access. Which role holds
which permission is data (``roles.permissions``), so a company's rules change without a release.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    MEMBERS_MANAGE = "members.manage"  # the People screen: members, roles, invites
    MEMBERS_DIRECTORY = "members.directory"  # list colleagues in pickers
    ROLES_MANAGE = "roles.manage"  # the future role editor
    WORKSPACE_RENAME = "workspace.rename"


ALL_PERMISSIONS = frozenset(Permission)


def parse_permissions(values: Iterable[str]) -> tuple[frozenset[Permission], frozenset[str]]:
    """Known permissions, plus the unknown strings (ignored, so a newer release's role rows do
    not break an older one)."""
    known: set[Permission] = set()
    unknown: set[str] = set()
    for value in values:
        try:
            known.add(Permission(value))
        except ValueError:
            unknown.add(value)
    return frozenset(known), frozenset(unknown)


@dataclass(frozen=True)
class RoleTemplate:
    key: str
    name: str
    permissions: frozenset[Permission]


READ = RoleTemplate("read", "Read", frozenset())
READ_WRITE = RoleTemplate(
    "read_write",
    "Read/write",
    frozenset({Permission.MEMBERS_DIRECTORY, Permission.WORKSPACE_RENAME}),
)
# Created with every workspace. The creator gets Read/write and, in code, every permission.
DEFAULT_ROLES = (READ_WRITE, READ)
CREATOR_ROLE = READ_WRITE
