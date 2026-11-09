"""Tables of the detection module (Phase 5 LLD §1.5 and topic 5)."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Table,
    Text,
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
