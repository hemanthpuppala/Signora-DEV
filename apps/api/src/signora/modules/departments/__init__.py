"""Departments module: how a firm groups its documents (Phase 3 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.departments.access import (
    DepartmentAccess,
    load_access,
    revoke_removed_member,
)
from signora.modules.departments.countersigners import drop_removed_member
from signora.modules.departments.routes import router
from signora.modules.departments.service import DepartmentRow, get_department, require_active

__all__ = [
    "DepartmentAccess",
    "DepartmentRow",
    "drop_removed_member",
    "get_department",
    "load_access",
    "require_active",
    "revoke_removed_member",
    "router",
]
