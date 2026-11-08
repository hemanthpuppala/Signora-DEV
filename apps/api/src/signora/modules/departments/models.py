"""Tables of the departments module (Phase 3 LLD). Must match the migrations."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from signora.kernel.db import metadata

departments = Table(
    "departments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("created_by", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("archived_at", DateTime(timezone=True)),
    Column("archived_by", UUID(as_uuid=True), ForeignKey("users.id")),
    CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
    CheckConstraint("char_length(description) <= 500", name="description_length"),
    CheckConstraint("(archived_at IS NULL) = (archived_by IS NULL)", name="archived_together"),
    # Child tables reference (department_id, workspace_id): never another company's department.
    UniqueConstraint("id", "workspace_id"),
    Index(
        "uq_departments_active_name",
        "workspace_id",
        text("lower(name)"),
        unique=True,
        postgresql_where=text("archived_at IS NULL"),
    ),
    Index("ix_departments_workspace_created", "workspace_id", text("created_at DESC")),
)
