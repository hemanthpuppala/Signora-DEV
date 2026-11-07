"""Identity and access: workspaces, roles, users, sessions, email_tokens, invites (Phase 2 LLD).

Also inserts the reserved system workspace that the system audit chain uses (backbone LLD §4.2).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_WORKSPACE = "00000000-0000-0000-0000-000000000000"
UUID = pg.UUID(as_uuid=True)
NOW = sa.func.now()


def _id() -> sa.Column[Any]:
    return sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False)


def _ts(name: str, *, nullable: bool = False, default: bool = True) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=NOW if default else None, nullable=nullable
    )


def upgrade() -> None:
    op.create_table(
        "workspaces",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_by", UUID, nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
        sa.CheckConstraint(
            f"created_by IS NOT NULL OR id = '{SYSTEM_WORKSPACE}'", name="creator_required"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_table(
        "roles",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "permissions",
            pg.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_roles_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("workspace_id", "key", name=op.f("uq_roles_workspace_id_key")),
        sa.UniqueConstraint("id", "workspace_id", name=op.f("uq_roles_id_workspace_id")),
    )
    op.create_table(
        "users",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("role_id", UUID, nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        _ts("password_changed_at"),
        _ts("created_at"),
        _ts("last_login_at", nullable=True, default=False),
        _ts("deactivated_at", nullable=True, default=False),
        sa.CheckConstraint("email = lower(email)", name="email_normalised"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_users_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(
            ["role_id", "workspace_id"],
            ["roles.id", "roles.workspace_id"],
            name=op.f("fk_users_role_id_workspace_id_roles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])
    op.create_foreign_key(
        "fk_workspaces_created_by_users",
        "workspaces",
        "users",
        ["created_by"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "sessions",
        sa.Column("id_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        _ts("created_at"),
        _ts("last_seen_at"),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.CheckConstraint("octet_length(id_hash) = 32", name="id_hash_sha256"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=op.f("fk_sessions_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id_hash", name=op.f("pk_sessions")),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_last_seen_at", "sessions", ["last_seen_at"])

    op.create_table(
        "email_tokens",
        _id(),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        _ts("created_at"),
        _ts("expires_at", default=False),
        _ts("used_at", nullable=True, default=False),
        sa.CheckConstraint("purpose IN ('signup', 'password_reset')", name="purpose_valid"),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="token_hash_sha256"),
        sa.CheckConstraint(
            "(purpose = 'signup') = (user_id IS NULL)", name="reset_tokens_have_a_user"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_email_tokens_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_tokens_token_hash")),
    )
    op.create_index(
        "ix_email_tokens_unused",
        "email_tokens",
        ["purpose", "email"],
        postgresql_where=sa.text("used_at IS NULL"),
    )
    op.create_index("ix_email_tokens_expires_at", "email_tokens", ["expires_at"])

    op.create_table(
        "invites",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role_id", UUID, nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("invited_by", UUID, nullable=False),
        _ts("created_at"),
        _ts("expires_at", default=False),
        _ts("accepted_at", nullable=True, default=False),
        _ts("revoked_at", nullable=True, default=False),
        sa.CheckConstraint("email = lower(email)", name="email_normalised"),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="token_hash_sha256"),
        sa.CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL", name="not_both_accepted_and_revoked"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_invites_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(
            ["role_id", "workspace_id"],
            ["roles.id", "roles.workspace_id"],
            name=op.f("fk_invites_role_id_workspace_id_roles"),
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["users.id"], name=op.f("fk_invites_invited_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )
    op.create_index(
        "uq_invites_pending_email",
        "invites",
        ["workspace_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )

    op.execute(
        sa.text("INSERT INTO workspaces (id, name) VALUES (CAST(:id AS uuid), :name)").bindparams(
            id=SYSTEM_WORKSPACE, name="Signora (system)"
        )
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.drop_table("email_tokens")
    op.drop_table("sessions")
    op.drop_constraint("fk_workspaces_created_by_users", "workspaces", type_="foreignkey")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("workspaces")
