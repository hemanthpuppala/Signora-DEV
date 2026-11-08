"""Identity and access module: accounts, sessions, workspaces, invites, permissions (Phase 2 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.identity_access.access import Actor, authorize
from signora.modules.identity_access.dependencies import current_actor, require
from signora.modules.identity_access.domain.emails import InvalidEmailError, normalize_email
from signora.modules.identity_access.domain.passwords import PasswordPolicy
from signora.modules.identity_access.domain.permissions import DEPARTMENT_GRANT, Permission
from signora.modules.identity_access.hooks import MemberRemovedHook, on_member_removed
from signora.modules.identity_access.routes import router

__all__ = [
    "DEPARTMENT_GRANT",
    "Actor",
    "InvalidEmailError",
    "MemberRemovedHook",
    "PasswordPolicy",
    "Permission",
    "authorize",
    "current_actor",
    "normalize_email",
    "on_member_removed",
    "require",
    "router",
]
