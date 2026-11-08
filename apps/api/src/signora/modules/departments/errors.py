"""Errors of the departments module (Phase 3 LLD topic 1)."""

from __future__ import annotations

from signora.kernel.errors import Conflict


class DepartmentNameTaken(Conflict):
    code = "department-name-taken"
    title = "Another active department already has this name"


class DepartmentArchived(Conflict):
    code = "department-archived"
    title = "This department is archived. Restore it to make changes"
