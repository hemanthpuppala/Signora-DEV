"""Tables of the review module (Phase 6 LLD §9, ADR-R1): a version's parties, fields and places.

Moved from detection (Phase 5 §5.2), which now hands its proposal over through ``replace_fields``.
"""

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

# The parties of a version (§4.5): a signer or a countersigner, in signing order.
version_roles = Table(
    "version_roles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("version_id", UUID(as_uuid=True), nullable=False),
    Column("slug", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("kind", Text, nullable=False),  # how it signs
    Column("kind_label", Text),  # the typed text of an Other kind: "Witness" (Phase 6 §3)
    Column("position", Integer, nullable=False),
    CheckConstraint("kind IN ('signer', 'countersigner')", name="kind_known"),
    CheckConstraint(
        "kind_label IS NULL OR char_length(kind_label) BETWEEN 1 AND 40", name="kind_label_length"
    ),
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
    Column("holds", Text, nullable=False),  # the manual layer of review.values (Phase 6 §4.1)
    Column("holds_label", Text),  # the typed text of an Other type
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
        "(holds = 'other') = (holds_label IS NOT NULL) "
        "AND (holds_label IS NULL OR char_length(holds_label) BETWEEN 1 AND 60)",
        name="holds_label_when_other",
    ),
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

# A version's review: its revision (one per Save, Phase 6 §1.6) and, at approval, the warnings
# accepted.
version_reviews = Table(
    "version_reviews",
    metadata,
    Column("version_id", UUID(as_uuid=True), primary_key=True),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("revision", Integer, nullable=False, server_default=text("0")),
    # The document's flags as detection found them (already signed, XFA, addressed to an AI…).
    Column("flags", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("accepted", JSONB),
    Column("updated_by", UUID(as_uuid=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("revision >= 0", name="revision_positive"),
    ForeignKeyConstraint(
        ["version_id", "workspace_id"],
        ["document_versions.id", "document_versions.workspace_id"],
    ),
    ForeignKeyConstraint(["updated_by", "workspace_id"], ["users.id", "users.workspace_id"]),
)

# How close the AI came, measured when a version is approved (Phase 6 §1.5).
review_metrics = Table(
    "review_metrics",
    metadata,
    Column("version_id", UUID(as_uuid=True), primary_key=True),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("baseline_version_id", UUID(as_uuid=True), nullable=False),  # whose AI proposal
    Column("true_positives", Integer, nullable=False),
    Column("false_positives", Integer, nullable=False),
    Column("false_negatives", Integer, nullable=False),
    Column("precision", Float),
    Column("recall", Float),
    Column("f1", Float),
    Column("relabelled", Integer, nullable=False),
    Column("retyped", Integer, nullable=False),
    Column("reassigned", Integer, nullable=False),
    Column("flags_accepted", Integer, nullable=False),
    Column("mean_iou", Float),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["version_id", "workspace_id"],
        ["document_versions.id", "document_versions.workspace_id"],
    ),
    ForeignKeyConstraint(
        ["baseline_version_id", "workspace_id"],
        ["document_versions.id", "document_versions.workspace_id"],
    ),
)
