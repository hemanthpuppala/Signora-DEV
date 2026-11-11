"""Signing and completion (Phase 8 LLD §15).

The signer's browser sessions and the people opened in them, email codes, consent to electronic
records, drafts, adopted signatures (and a Signora user's saved one, for countersigning); a
recipient's decline; an envelope's completed files; and files attached to an email.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def _recipient(table: str) -> sa.ForeignKeyConstraint:
    """A row of one recipient, in the recipient's company (composite key). Named by hand: the
    convention's name would pass Postgres's 63 characters."""
    return sa.ForeignKeyConstraint(
        ["recipient_id", "workspace_id"],
        ["envelope_recipients.id", "envelope_recipients.workspace_id"],
        name=op.f(f"fk_{table}_recipient_envelope_recipients"),
    )


def _signature_checks(table: str) -> list[sa.CheckConstraint]:
    """A typed signature is its text in a font; a drawn one is its strokes (§5.5)."""
    return [
        sa.CheckConstraint(
            "kind IN ('signature', 'initials')", name=op.f(f"ck_{table}_kind_known")
        ),
        sa.CheckConstraint(
            "method = 'typed' AND text IS NOT NULL AND font IS NOT NULL AND strokes IS NULL "
            "OR method = 'drawn' AND strokes IS NOT NULL AND text IS NULL AND font IS NULL",
            name=op.f(f"ck_{table}_method_shape"),
        ),
        sa.CheckConstraint(
            "text IS NULL OR char_length(text) BETWEEN 1 AND 100",
            name=op.f(f"ck_{table}_text_length"),
        ),
        sa.CheckConstraint("octet_length(sha256) = 32", name=op.f(f"ck_{table}_sha256_length")),
    ]


def _signature_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("font", sa.Text(), nullable=True),
        sa.Column("strokes", pg.JSONB(), nullable=True),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
    ]


def upgrade() -> None:
    # Signing rows name a recipient with its company (and drafts with its version too).
    op.create_unique_constraint(
        op.f("uq_envelope_recipients_id_workspace_id"),
        "envelope_recipients",
        ["id", "workspace_id"],
    )
    op.create_unique_constraint(
        op.f("uq_envelope_recipients_id_workspace_id_version_id"),
        "envelope_recipients",
        ["id", "workspace_id", "version_id"],
    )

    # A decline (§8.3): who, when, why; final.
    op.add_column("envelope_recipients", sa.Column("declined_at", TS, nullable=True))
    op.add_column("envelope_recipients", sa.Column("decline_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_envelope_recipients_declined_is_recorded"),
        "envelope_recipients",
        "(status = 'declined') = (declined_at IS NOT NULL AND decline_reason IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_envelope_recipients_decline_reason_length"),
        "envelope_recipients",
        "decline_reason IS NULL OR char_length(btrim(decline_reason)) BETWEEN 1 AND 500",
    )
    # A countersigner's inbox (§7.2): their waiting envelopes, one index range.
    op.create_index(
        "ix_envelope_recipients_user_id_status",
        "envelope_recipients",
        ["user_id", "status"],
        postgresql_where=sa.text("kind = 'countersigner'"),
    )

    # The completed document and its certificate (§12): set together, once, at completion.
    op.add_column("envelopes", sa.Column("signed_blob", sa.Text(), nullable=True))
    op.add_column("envelopes", sa.Column("signed_sha256", sa.LargeBinary(), nullable=True))
    op.add_column("envelopes", sa.Column("certificate_blob", sa.Text(), nullable=True))
    op.add_column("envelopes", sa.Column("certificate_sha256", sa.LargeBinary(), nullable=True))
    op.create_check_constraint(
        op.f("ck_envelopes_completed_has_files"),
        "envelopes",
        "(status = 'completed') = (signed_blob IS NOT NULL AND signed_sha256 IS NOT NULL "
        "AND certificate_blob IS NOT NULL AND certificate_sha256 IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_envelopes_file_hashes_length"),
        "envelopes",
        "(signed_sha256 IS NULL OR octet_length(signed_sha256) = 32) AND "
        "(certificate_sha256 IS NULL OR octet_length(certificate_sha256) = 32)",
    )
    op.execute(
        """
        CREATE FUNCTION envelopes_keep_completed_files() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.signed_blob IS NOT NULL AND
               (NEW.signed_blob, NEW.signed_sha256, NEW.certificate_blob, NEW.certificate_sha256)
               IS DISTINCT FROM
               (OLD.signed_blob, OLD.signed_sha256, OLD.certificate_blob, OLD.certificate_sha256)
            THEN
                RAISE EXCEPTION 'a completed envelope''s files cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER envelopes_keep_completed_files BEFORE UPDATE ON envelopes "
        "FOR EACH ROW EXECUTE FUNCTION envelopes_keep_completed_files()"
    )

    # A browser's signing session (§1.3): only the cookie's hash is kept.
    op.create_table(
        "signing_sessions",
        sa.Column("id_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.CheckConstraint(
            "octet_length(id_hash) = 32", name=op.f("ck_signing_sessions_id_hash_sha256")
        ),
        sa.PrimaryKeyConstraint("id_hash", name=op.f("pk_signing_sessions")),
    )
    op.create_index("ix_signing_sessions_expires_at", "signing_sessions", ["expires_at"])

    # Each person opened in a browser session (§1.4).
    op.create_table(
        "signing_grants",
        sa.Column("session_hash", sa.LargeBinary(), nullable=False),
        sa.Column("recipient_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("link_version", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", TS, nullable=True),
        sa.PrimaryKeyConstraint("session_hash", "recipient_id", name=op.f("pk_signing_grants")),
        sa.ForeignKeyConstraint(
            ["session_hash"],
            ["signing_sessions.id_hash"],
            name=op.f("fk_signing_grants_session_hash_signing_sessions"),
            ondelete="CASCADE",
        ),
        _recipient("signing_grants"),
    )

    # At most one live email code per person (§2.2); only its keyed hash.
    op.create_table(
        "signing_codes",
        sa.Column("recipient_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("link_version", sa.Integer(), nullable=False),
        sa.Column("code_mac", sa.LargeBinary(), nullable=False),
        sa.Column("sent_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("wrong_tries", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("used_at", TS, nullable=True),
        sa.Column("window_start", TS, nullable=False),
        sa.Column("sent_in_window", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "octet_length(code_mac) = 32", name=op.f("ck_signing_codes_code_mac_length")
        ),
        sa.CheckConstraint(
            "wrong_tries BETWEEN 0 AND 20", name=op.f("ck_signing_codes_wrong_tries_range")
        ),
        sa.CheckConstraint(
            "sent_in_window BETWEEN 1 AND 5", name=op.f("ck_signing_codes_sent_in_window_range")
        ),
        sa.PrimaryKeyConstraint("recipient_id", name=op.f("pk_signing_codes")),
        _recipient("signing_codes"),
    )

    # Consent to electronic records (§3.2): a fact once given (insert only).
    op.create_table(
        "signing_consents",
        sa.Column("recipient_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("disclosure_version", sa.Text(), nullable=False),
        sa.Column("consented_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("ip", pg.INET(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "char_length(disclosure_version) BETWEEN 1 AND 40",
            name=op.f("ck_signing_consents_disclosure_version_length"),
        ),
        sa.CheckConstraint(
            "char_length(user_agent) <= 512", name=op.f("ck_signing_consents_user_agent_length")
        ),
        sa.PrimaryKeyConstraint("recipient_id", name=op.f("pk_signing_consents")),
        _recipient("signing_consents"),
    )
    op.execute(
        """
        CREATE FUNCTION signing_consents_insert_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'a consent cannot change' USING ERRCODE = 'check_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER signing_consents_insert_only BEFORE UPDATE OR DELETE ON signing_consents "
        "FOR EACH ROW EXECUTE FUNCTION signing_consents_insert_only()"
    )

    # A person's values before they submit (§4.7); nobody else reads them.
    op.create_table(
        "signing_drafts",
        sa.Column("recipient_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "char_length(value) <= 2000", name=op.f("ck_signing_drafts_value_length")
        ),
        sa.PrimaryKeyConstraint("recipient_id", "field_id", name=op.f("pk_signing_drafts")),
        sa.ForeignKeyConstraint(
            ["recipient_id", "workspace_id", "version_id"],
            [
                "envelope_recipients.id",
                "envelope_recipients.workspace_id",
                "envelope_recipients.version_id",
            ],
            name=op.f("fk_signing_drafts_recipient_envelope_recipients"),
        ),
        sa.ForeignKeyConstraint(
            ["field_id", "version_id"],
            ["version_fields.id", "version_fields.version_id"],
            name=op.f("fk_signing_drafts_field_id_version_id_version_fields"),
        ),
    )

    # What a person adopted for one envelope (§5.5): evidence, frozen once they have signed.
    op.create_table(
        "signing_signatures",
        sa.Column("recipient_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        *_signature_columns(),
        sa.Column("adopted_at", TS, server_default=sa.func.now(), nullable=False),
        *_signature_checks("signing_signatures"),
        sa.PrimaryKeyConstraint("recipient_id", "kind", name=op.f("pk_signing_signatures")),
        _recipient("signing_signatures"),
    )
    op.execute(
        """
        CREATE FUNCTION signing_signatures_frozen_once_signed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM envelope_recipients
                       WHERE id = OLD.recipient_id AND status = 'signed') THEN
                RAISE EXCEPTION 'a signature that was signed with cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER signing_signatures_frozen_once_signed BEFORE UPDATE OR DELETE ON "
        "signing_signatures FOR EACH ROW EXECUTE FUNCTION signing_signatures_frozen_once_signed()"
    )

    # A Signora user's signature, saved on their first countersign (§5.4).
    op.create_table(
        "saved_signatures",
        sa.Column("user_id", UUID, nullable=False),
        *_signature_columns(),
        sa.Column("saved_at", TS, server_default=sa.func.now(), nullable=False),
        *_signature_checks("saved_signatures"),
        sa.PrimaryKeyConstraint("user_id", "kind", name=op.f("pk_saved_signatures")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_signatures_user_id_users"),
            ondelete="CASCADE",
        ),
    )

    # Files an email carries (§15): kept as blob keys, read by the transport when it sends.
    op.create_table(
        "email_attachments",
        sa.Column("email_id", UUID, nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("blob_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.CheckConstraint("position >= 1", name=op.f("ck_email_attachments_position_positive")),
        sa.CheckConstraint(
            "char_length(filename) BETWEEN 1 AND 200",
            name=op.f("ck_email_attachments_filename_length"),
        ),
        sa.PrimaryKeyConstraint("email_id", "position", name=op.f("pk_email_attachments")),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["email_messages.id"],
            name=op.f("fk_email_attachments_email_id_email_messages"),
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("email_attachments")
    op.drop_table("saved_signatures")
    op.execute("DROP TRIGGER signing_signatures_frozen_once_signed ON signing_signatures")
    op.execute("DROP FUNCTION signing_signatures_frozen_once_signed()")
    op.drop_table("signing_signatures")
    op.drop_table("signing_drafts")
    op.execute("DROP TRIGGER signing_consents_insert_only ON signing_consents")
    op.execute("DROP FUNCTION signing_consents_insert_only()")
    op.drop_table("signing_consents")
    op.drop_table("signing_codes")
    op.drop_table("signing_grants")
    op.drop_index("ix_signing_sessions_expires_at", table_name="signing_sessions")
    op.drop_table("signing_sessions")
    op.execute("DROP TRIGGER envelopes_keep_completed_files ON envelopes")
    op.execute("DROP FUNCTION envelopes_keep_completed_files()")
    op.drop_constraint(op.f("ck_envelopes_file_hashes_length"), "envelopes", type_="check")
    op.drop_constraint(op.f("ck_envelopes_completed_has_files"), "envelopes", type_="check")
    for column in ("certificate_sha256", "certificate_blob", "signed_sha256", "signed_blob"):
        op.drop_column("envelopes", column)
    op.drop_index("ix_envelope_recipients_user_id_status", table_name="envelope_recipients")
    op.drop_constraint(
        op.f("ck_envelope_recipients_decline_reason_length"), "envelope_recipients", type_="check"
    )
    op.drop_constraint(
        op.f("ck_envelope_recipients_declined_is_recorded"), "envelope_recipients", type_="check"
    )
    op.drop_column("envelope_recipients", "decline_reason")
    op.drop_column("envelope_recipients", "declined_at")
    op.drop_constraint(
        op.f("uq_envelope_recipients_id_workspace_id_version_id"),
        "envelope_recipients",
        type_="unique",
    )
    op.drop_constraint(
        op.f("uq_envelope_recipients_id_workspace_id"), "envelope_recipients", type_="unique"
    )
