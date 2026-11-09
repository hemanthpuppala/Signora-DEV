"""Departments module: how a firm groups its documents (Phase 3 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.departments.access import (
    DepartmentAccess,
    load_access,
    revoke_removed_member,
)
from signora.modules.departments.countersigners import (
    Countersigner,
    drop_removed_member,
    list_countersigners,
)
from signora.modules.departments.domain import normalize_name
from signora.modules.departments.routes import router
from signora.modules.departments.service import DepartmentRow, get_department, require_active

__all__ = [
    "Countersigner",
    "DepartmentAccess",
    "DepartmentRow",
    "drop_removed_member",
    "get_department",
    "list_countersigners",
    "load_access",
    "normalize_name",
    "require_active",
    "revoke_removed_member",
    "router",
]
