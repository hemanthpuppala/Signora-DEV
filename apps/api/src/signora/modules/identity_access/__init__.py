"""Identity and access module: accounts, sessions, workspaces, invites, permissions (Phase 2 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.identity_access.access import Actor, authorize
from signora.modules.identity_access.dependencies import current_actor, require
from signora.modules.identity_access.domain.emails import InvalidEmailError, normalize_email
from signora.modules.identity_access.domain.passwords import PasswordPolicy
from signora.modules.identity_access.domain.permissions import DEPARTMENT_GRANT, Permission
from signora.modules.identity_access.domain.tokens import IssuedToken, hash_token, issue_token
from signora.modules.identity_access.hooks import MemberRemovedHook, on_member_removed
from signora.modules.identity_access.routes import router
from signora.modules.identity_access.sessions import actor_of

__all__ = [
    "DEPARTMENT_GRANT",
    "Actor",
    "InvalidEmailError",
    "IssuedToken",
    "MemberRemovedHook",
    "PasswordPolicy",
    "Permission",
    "actor_of",
    "authorize",
    "current_actor",
    "hash_token",
    "issue_token",
    "normalize_email",
    "on_member_removed",
    "require",
    "router",
]
