"""Departments module: how a firm groups its files (Phase 3 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.departments.access import DepartmentAccess, load_access
from signora.modules.departments.routes import router
from signora.modules.departments.service import DepartmentRow, get_department, require_active

__all__ = [
    "DepartmentAccess",
    "DepartmentRow",
    "get_department",
    "load_access",
    "require_active",
    "router",
]
