"""Identity and access module: accounts, sessions, workspaces, invites, permissions (Phase 2 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.identity_access.access import Actor, authorize
from signora.modules.identity_access.dependencies import current_actor, require
from signora.modules.identity_access.domain.emails import InvalidEmailError, normalize_email
from signora.modules.identity_access.domain.passwords import PasswordPolicy
from signora.modules.identity_access.domain.permissions import Permission
from signora.modules.identity_access.routes import router

__all__ = [
    "Actor",
    "InvalidEmailError",
    "PasswordPolicy",
    "Permission",
    "authorize",
    "current_actor",
    "normalize_email",
    "require",
    "router",
]
