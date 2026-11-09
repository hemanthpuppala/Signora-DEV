"""Envelopes and sending (Phase 7 LLD §9).

An envelope sends one approved version of a document to its parties: its recipients (signers,
countersigners, people who receive a copy) and the values given before signing. Its version,
settings and the sender's values never change once sent (a trigger). Emails gain a Reply-To.
"Require email code" moves from the document to the envelope (owner decision, 2026-11-09).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
ENVELOPE_STATUSES = (
    "('sent', 'opened', 'viewed', 'signed', 'completed', 'declined', 'expired', 'cancelled')"
)
RECIPIENT_STATUSES = "('waiting', 'sent', 'opened', 'viewed', 'signed', 'declined')"


def upgrade() -> None:
    op.create_table(
        "envelopes",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("department_id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'sent'"), nullable=False),
        sa.Column("require_email_code", sa.Boolean(), nullable=False),
        sa.Column("reminder_interval_hours", sa.Integer(), nullable=False),
        sa.Column("max_reminders", sa.Integer(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("notify_emails", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("sent_by", UUID, nullable=False),
        sa.Column("sent_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.CheckConstraint(
            f"status IN {ENVELOPE_STATUSES}", name=op.f("ck_envelopes_status_known")
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120", name=op.f("ck_envelopes_title_length")
        ),
        sa.CheckConstraint(
            "reminder_interval_hours BETWEEN 1 AND 720",
            name=op.f("ck_envelopes_reminder_interval_hours_range"),
        ),
        sa.CheckConstraint(
            "max_reminders BETWEEN 0 AND 20", name=op.f("ck_envelopes_max_reminders_range")
        ),
        sa.CheckConstraint(
            "cardinality(notify_emails) <= 5", name=op.f("ck_envelopes_notify_emails_count")
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)",
            name=op.f("ck_envelopes_cancelled_is_recorded"),
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name=op.f("ck_envelopes_completed_is_recorded"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_envelopes")),
        sa.UniqueConstraint("id", "workspace_id", name=op.f("uq_envelopes_id_workspace_id")),
        sa.UniqueConstraint("id", "version_id", name=op.f("uq_envelopes_id_version_id")),
        sa.ForeignKeyConstraint(
            ["department_id", "workspace_id"],
            ["departments.id", "departments.workspace_id"],
            name=op.f("fk_envelopes_department_id_workspace_id_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            name=op.f("fk_envelopes_document_id_workspace_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "document_id"],
            ["document_versions.id", "document_versions.document_id"],
            name=op.f("fk_envelopes_version_id_document_id_document_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["sent_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_envelopes_sent_by_workspace_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_envelopes_cancelled_by_workspace_id_users"),
        ),
    )
    op.create_index(
        "ix_envelopes_workspace_id_department_id_status_sent_at",
        "envelopes",
        ["workspace_id", "department_id", "status", "sent_at"],
    )
    op.create_index("ix_envelopes_document_id", "envelopes", ["document_id"])

    op.add_column("email_messages", sa.Column("reply_to", sa.Text(), nullable=True))

    op.create_table(
        "envelope_recipients",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("envelope_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("party_id", UUID, nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("link_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("reminders_sent", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_reminder_at", TS, nullable=True),
        sa.Column("last_email_id", UUID, nullable=True),
        sa.Column("sent_at", TS, nullable=True),
        sa.Column("opened_at", TS, nullable=True),
        sa.Column("viewed_at", TS, nullable=True),
        sa.Column("signed_at", TS, nullable=True),
        sa.CheckConstraint(
            "kind IN ('signer', 'countersigner', 'copy')",
            name=op.f("ck_envelope_recipients_kind_known"),
        ),
        sa.CheckConstraint(
            "kind = 'signer' AND stage = 1 OR kind = 'countersigner' AND stage = 2 "
            "OR kind = 'copy' AND stage = 3",
            name=op.f("ck_envelope_recipients_stage_of_kind"),
        ),
        sa.CheckConstraint(
            "(kind = 'copy') = (party_id IS NULL)",
            name=op.f("ck_envelope_recipients_party_unless_copy"),
        ),
        sa.CheckConstraint(
            "(kind = 'countersigner') = (user_id IS NOT NULL)",
            name=op.f("ck_envelope_recipients_user_for_countersigner"),
        ),
        sa.CheckConstraint(
            f"status IN {RECIPIENT_STATUSES}", name=op.f("ck_envelope_recipients_status_known")
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120", name=op.f("ck_envelope_recipients_name_length")
        ),
        sa.CheckConstraint("link_version >= 1", name=op.f("ck_envelope_recipients_link_positive")),
        sa.CheckConstraint("position >= 1", name=op.f("ck_envelope_recipients_position_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_envelope_recipients")),
        sa.UniqueConstraint(
            "envelope_id", "party_id", name=op.f("uq_envelope_recipients_envelope_id_party_id")
        ),
        sa.UniqueConstraint(
            "envelope_id",
            "stage",
            "position",
            name=op.f("uq_envelope_recipients_envelope_id_stage_position"),
        ),
        sa.ForeignKeyConstraint(
            ["envelope_id", "workspace_id"],
            ["envelopes.id", "envelopes.workspace_id"],
            name=op.f("fk_envelope_recipients_envelope_id_workspace_id_envelopes"),
        ),
        sa.ForeignKeyConstraint(
            ["envelope_id", "version_id"],
            ["envelopes.id", "envelopes.version_id"],
            name=op.f("fk_envelope_recipients_envelope_id_version_id_envelopes"),
        ),
        sa.ForeignKeyConstraint(
            ["party_id", "version_id"],
            ["version_roles.id", "version_roles.version_id"],
            name=op.f("fk_envelope_recipients_party_id_version_id_version_roles"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "workspace_id"],
            ["users.id", "users.workspace_id"],
            name=op.f("fk_envelope_recipients_user_id_workspace_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["last_email_id"],
            ["email_messages.id"],
            name=op.f("fk_envelope_recipients_last_email_id_email_messages"),
        ),
    )
    op.create_index("ix_envelope_recipients_envelope_id", "envelope_recipients", ["envelope_id"])

    op.create_table(
        "envelope_values",
        sa.Column("envelope_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("given_by", sa.Text(), nullable=False),
        sa.Column("recipient_id", UUID, nullable=True),
        sa.Column("given_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "given_by IN ('sender', 'recipient')", name=op.f("ck_envelope_values_given_by_known")
        ),
        sa.CheckConstraint(
            "(given_by = 'recipient') = (recipient_id IS NOT NULL)",
            name=op.f("ck_envelope_values_recipient_when_theirs"),
        ),
        sa.CheckConstraint(
            "char_length(value) <= 2000", name=op.f("ck_envelope_values_value_length")
        ),
        sa.PrimaryKeyConstraint("envelope_id", "field_id", name=op.f("pk_envelope_values")),
        sa.ForeignKeyConstraint(
            ["envelope_id", "workspace_id"],
            ["envelopes.id", "envelopes.workspace_id"],
            name=op.f("fk_envelope_values_envelope_id_workspace_id_envelopes"),
        ),
        sa.ForeignKeyConstraint(
            ["envelope_id", "version_id"],
            ["envelopes.id", "envelopes.version_id"],
            name=op.f("fk_envelope_values_envelope_id_version_id_envelopes"),
        ),
        sa.ForeignKeyConstraint(
            ["field_id", "version_id"],
            ["version_fields.id", "version_fields.version_id"],
            name=op.f("fk_envelope_values_field_id_version_id_version_fields"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["envelope_recipients.id"],
            name=op.f("fk_envelope_values_recipient_id_envelope_recipients"),
        ),
    )

    # What was sent never changes (NFR-E5): an envelope's document, version and settings, and the
    # values the sender gave. Its title may still be renamed; its state moves on.
    op.execute(
        """
        CREATE FUNCTION envelopes_keep_what_was_sent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.workspace_id, NEW.department_id, NEW.document_id, NEW.version_id,
                NEW.require_email_code, NEW.reminder_interval_hours, NEW.max_reminders,
                NEW.notify_emails, NEW.sent_by, NEW.sent_at)
               IS DISTINCT FROM
               (OLD.workspace_id, OLD.department_id, OLD.document_id, OLD.version_id,
                OLD.require_email_code, OLD.reminder_interval_hours, OLD.max_reminders,
                OLD.notify_emails, OLD.sent_by, OLD.sent_at) THEN
                RAISE EXCEPTION 'what an envelope sent cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER envelopes_keep_what_was_sent BEFORE UPDATE ON envelopes "
        "FOR EACH ROW EXECUTE FUNCTION envelopes_keep_what_was_sent()"
    )
    op.execute(
        """
        CREATE FUNCTION envelope_values_keep_the_senders() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.given_by = 'sender' THEN
                RAISE EXCEPTION 'a value given when sending cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER envelope_values_keep_the_senders BEFORE UPDATE OR DELETE ON "
        "envelope_values FOR EACH ROW EXECUTE FUNCTION envelope_values_keep_the_senders()"
    )

    # An envelope's timeline reads its audit entries (§6): one subject's history, by time.
    op.create_index(
        "ix_audit_events_subject_type_subject_id_occurred_at",
        "audit_events",
        ["subject_type", "subject_id", "occurred_at"],
    )

    # A send's setting now (owner decision, 2026-11-09); nothing has been sent yet.
    op.drop_column("documents", "require_email_code")


def downgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "require_email_code", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.drop_index("ix_audit_events_subject_type_subject_id_occurred_at", table_name="audit_events")
    op.execute("DROP TRIGGER envelope_values_keep_the_senders ON envelope_values")
    op.execute("DROP FUNCTION envelope_values_keep_the_senders()")
    op.execute("DROP TRIGGER envelopes_keep_what_was_sent ON envelopes")
    op.execute("DROP FUNCTION envelopes_keep_what_was_sent()")
    op.drop_table("envelope_values")
    op.drop_index("ix_envelope_recipients_envelope_id", table_name="envelope_recipients")
    op.drop_table("envelope_recipients")
    op.drop_column("email_messages", "reply_to")
    op.drop_index("ix_envelopes_document_id", table_name="envelopes")
    op.drop_index("ix_envelopes_workspace_id_department_id_status_sent_at", table_name="envelopes")
    op.drop_table("envelopes")
