"""Tables of the identity module (Phase 2 LLD §4.4, §6.4, §8.1, §8.3). Must match migration 0003.

Integrity rules the database enforces:
- every workspace except the reserved system one has a creator (deferred foreign key, so the
  workspace and its first user are inserted in one transaction);
- a user's and an invite's role belong to the same workspace (composite foreign keys);
- one pending invite per email per workspace; emails are unique across Signora.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, UUID

from signora.kernel.db import metadata

SYSTEM_WORKSPACE = "00000000-0000-0000-0000-000000000000"

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("name", Text, nullable=False),
    Column("created_by", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # The company's website as its registrable domain: its logo is ``company_logos``' row for it.
    Column("website", Text),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
    CheckConstraint("char_length(website) BETWEEN 4 AND 253", name="website_length"),
    CheckConstraint(
        f"created_by IS NOT NULL OR id = '{SYSTEM_WORKSPACE}'", name="creator_required"
    ),
    ForeignKeyConstraint(
        ["created_by"],
        ["users.id"],
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        name="fk_workspaces_created_by_users",
    ),
)

# The companies on a domain: whether its logo is still in use, and each company's logo.
Index(
    "ix_workspaces_website", workspaces.c.website, postgresql_where=workspaces.c.website.isnot(None)
)

# One logo per domain, shared by every company on it and kept when they are gone (migration
# 0031): a company on a known domain shows its logo without asking logo.dev. A row without a logo
# after a look-up means none was found then. The file is in the system workspace's store.
company_logos = Table(
    "company_logos",
    metadata,
    Column("domain", Text, primary_key=True),
    Column("logo_sha256", Text),
    Column("logo_bytes", Integer),
    Column("etag", Text),  # logo.dev's version of it: a refresh downloads only a changed one
    Column("checked_at", DateTime(timezone=True)),  # the last look-up that answered
    Column("check_due_at", DateTime(timezone=True)),  # the next look-up; null: none planned
    CheckConstraint("char_length(domain) BETWEEN 4 AND 253", name="domain_length"),
    CheckConstraint("(logo_sha256 IS NULL) = (logo_bytes IS NULL)", name="logo_complete"),
)

# The look-ups that are due (the sweep's scan): only rows with one planned.
Index(
    "ix_company_logos_check_due_at",
    company_logos.c.check_due_at,
    postgresql_where=company_logos.c.check_due_at.isnot(None),
)

roles = Table(
    "roles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False),
    Column("key", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("permissions", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("is_system", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("workspace_id", "key"),
    UniqueConstraint("id", "workspace_id"),
)

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False),
    Column("role_id", UUID(as_uuid=True), nullable=False),
    Column("email", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column(
        "password_changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_login_at", DateTime(timezone=True)),
    Column("deactivated_at", DateTime(timezone=True)),
    CheckConstraint("email = lower(email)", name="email_normalised"),
    CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
    ForeignKeyConstraint(["role_id", "workspace_id"], ["roles.id", "roles.workspace_id"]),
    # Lets other tables check a referenced user belongs to the same company (Phase 3).
    UniqueConstraint("id", "workspace_id"),
    Index("ix_users_workspace_id", "workspace_id"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id_hash", LargeBinary, primary_key=True),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "last_seen_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    ),
    Column("ip", INET),
    Column("user_agent", Text),
    CheckConstraint("octet_length(id_hash) = 32", name="id_hash_sha256"),
)

email_tokens = Table(
    "email_tokens",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("purpose", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("token_hash", LargeBinary, nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    CheckConstraint("purpose IN ('signup', 'password_reset')", name="purpose_valid"),
    CheckConstraint("octet_length(token_hash) = 32", name="token_hash_sha256"),
    CheckConstraint("(purpose = 'signup') = (user_id IS NULL)", name="reset_tokens_have_a_user"),
    Index("ix_email_tokens_unused", "purpose", "email", postgresql_where=text("used_at IS NULL")),
    Index("ix_email_tokens_expires_at", "expires_at"),
)

invites = Table(
    "invites",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")),
    Column("workspace_id", UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False),
    Column("email", Text, nullable=False),
    Column("role_id", UUID(as_uuid=True), nullable=False),
    Column("token_hash", LargeBinary, nullable=False, unique=True),
    Column("invited_by", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("accepted_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    CheckConstraint("email = lower(email)", name="email_normalised"),
    CheckConstraint("octet_length(token_hash) = 32", name="token_hash_sha256"),
    CheckConstraint(
        "accepted_at IS NULL OR revoked_at IS NULL", name="not_both_accepted_and_revoked"
    ),
    ForeignKeyConstraint(["role_id", "workspace_id"], ["roles.id", "roles.workspace_id"]),
    Index(
        "uq_invites_pending_email",
        "workspace_id",
        "email",
        unique=True,
        postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
    ),
)
