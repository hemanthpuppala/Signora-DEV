"""Tables of the detection module (Phase 5 LLD §1.5 and topic 5)."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from signora.kernel.db import metadata

# One run per version, saved stage by stage so a retry resumes where it stopped (§1.2).
detection_runs = Table(
    "detection_runs",
    metadata,
    Column("version_id", UUID(as_uuid=True), primary_key=True),
    Column("run_id", UUID(as_uuid=True), nullable=False),  # a new run gets a new id (§1.7)
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("stage", Text, nullable=False, server_default=text("'read'")),  # the next stage to run
    Column("fields_from", Text),
    Column("parsed", JSONB),  # read: the fields with their kinds, places, options, labels, flags
    Column("layout", Text),  # read: the document as the AI reads it, with field markers
    Column("calls", JSONB),  # ai: per call: request id, latency, tokens, problems found
    Column("answer", JSONB),  # ai: the final answer, parsed against the schema
    Column("result", JSONB),  # derive: the checked result with keys, values and flags
    Column("model", Text),
    Column("failure_code", Text),
    Column("requested_by", UUID(as_uuid=True)),  # who ran it by hand (§1.3)
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint("stage IN ('read', 'ai', 'derive', 'store', 'done')", name="stage_known"),
    CheckConstraint("fields_from IN ('form_fields', 'blanks', 'none')", name="fields_from_known"),
    CheckConstraint("(stage = 'done') = (finished_at IS NOT NULL)", name="done_when_finished"),
    ForeignKeyConstraint(
        ["version_id", "workspace_id"],
        ["document_versions.id", "document_versions.workspace_id"],
    ),
    ForeignKeyConstraint(["requested_by", "workspace_id"], ["users.id", "users.workspace_id"]),
)

# The parties of a version (§4.5): a signer or a countersigner, in signing order.
version_roles = Table(
    "version_roles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("slug", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("position", Integer, nullable=False),
    CheckConstraint("kind IN ('signer', 'countersigner')", name="kind_known"),
    UniqueConstraint("version_id", "slug"),
    UniqueConstraint("id", "version_id"),
    ForeignKeyConstraint(
        ["version_id", "workspace_id"],
        ["document_versions.id", "document_versions.workspace_id"],
    ),
)

# A version's fields: one per key, with all its places (§5.2).
version_fields = Table(
    "version_fields",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("key", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("holds", Text, nullable=False),
    Column("filled_by", Text, nullable=False),
    Column("role_id", UUID(as_uuid=True)),
    Column("required", Boolean, nullable=False),
    Column("sensitive", Boolean, nullable=False),
    Column("depends_on_field_id", UUID(as_uuid=True)),
    Column("depends_on_option", Text),
    Column("needs_review", Text),
    Column("origin", Text, nullable=False),
    CheckConstraint("filled_by IN ('role', 'sender', 'none')", name="filled_by_known"),
    CheckConstraint("origin IN ('detected', 'added')", name="origin_known"),
    CheckConstraint(
        "(filled_by = 'role') = (role_id IS NOT NULL)", name="role_when_filled_by_role"
    ),
    CheckConstraint(
        "(depends_on_field_id IS NULL) = (depends_on_option IS NULL)", name="dependency_complete"
    ),
    UniqueConstraint("version_id", "key"),
    UniqueConstraint("id", "version_id"),
    ForeignKeyConstraint(
        ["version_id", "workspace_id"],
        ["document_versions.id", "document_versions.workspace_id"],
    ),
    ForeignKeyConstraint(
        ["role_id", "version_id"], ["version_roles.id", "version_roles.version_id"]
    ),
    ForeignKeyConstraint(
        ["depends_on_field_id", "version_id"],
        ["version_fields.id", "version_fields.version_id"],
        ondelete="CASCADE",
    ),
    Index("ix_version_fields_version_id", "version_id"),
)

# Every place a field fills, keeping the PDF's field name for signing (§5.2).
field_placements = Table(
    "field_placements",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("field_id", UUID(as_uuid=True), nullable=False),
    Column("page", Integer, nullable=False),
    Column("x0", Float, nullable=False),  # PDF points, as displayed
    Column("y0", Float, nullable=False),
    Column("x1", Float, nullable=False),
    Column("y1", Float, nullable=False),
    Column("kind", Text, nullable=False),
    Column("pdf_field", Text),  # the form field signing fills; null for a blank
    Column("option_value", Text),  # a choice: the value this place stands for
    Column("option_text", Text),  # and its own words
    CheckConstraint("page >= 1", name="page_positive"),
    CheckConstraint(
        "kind IN ('text', 'signature', 'checkbox', 'radio', 'combobox', 'listbox', 'blank')",
        name="kind_known",
    ),
    ForeignKeyConstraint(
        ["field_id", "version_id"],
        ["version_fields.id", "version_fields.version_id"],
        ondelete="CASCADE",
    ),
    Index("ix_field_placements_version_id", "version_id"),
    Index("ix_field_placements_field_id", "field_id"),
)
