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
    # Departments (Phase 3): company-level
    DEPARTMENTS_CREATE = "departments.create"
    DEPARTMENTS_MANAGE = "departments.manage"
    # Inside a department (Phase 3 topic 2): from the role in every department, or a grant in one
    FILES_VIEW_SENDS = "files.view_sends"  # see sends and their client details
    FILES_SEND = "files.send"  # upload, review, approve and send files


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
    key: str  # stable identifier; the name and description are what people read
    name: str
    description: str
    permissions: frozenset[Permission]


READ = RoleTemplate(
    "read",
    "Viewer",
    "Can see projects, documents and signed agreements, but can't change anything.",
    frozenset(),
)
READ_WRITE = RoleTemplate(
    "read_write",
    "Editor",
    "Can create and send agreements, and rename the company.",
    frozenset(
        {
            Permission.MEMBERS_DIRECTORY,
            Permission.WORKSPACE_RENAME,
            Permission.DEPARTMENTS_CREATE,
            Permission.DEPARTMENTS_MANAGE,
            Permission.FILES_VIEW_SENDS,
            Permission.FILES_SEND,
        }
    ),
)
# What a department grant gives in its one department (Phase 3 topic 2).
DEPARTMENT_GRANT = frozenset({Permission.FILES_VIEW_SENDS, Permission.FILES_SEND})
# Shown for the workspace creator, who holds the Editor role plus every permission in code.
OWNER_LABEL = "Owner"
OWNER_DESCRIPTION = (
    "Created this company's account. Can invite and remove people, change what they can do, "
    "and everything editors can do."
)
# Created with every workspace. The creator gets Editor and, in code, every permission.
DEFAULT_ROLES = (READ_WRITE, READ)
CREATOR_ROLE = READ_WRITE
