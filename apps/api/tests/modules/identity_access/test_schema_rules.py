"""Integrity rules the identity tables enforce themselves (Phase 2 LLD §8.3)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signora.kernel.db import Database

SYSTEM_WORKSPACE = uuid.UUID(int=0)


def new_id(session: Session) -> uuid.UUID:
    value: uuid.UUID = session.execute(text("SELECT uuidv7()")).scalar_one()
    return value


def make_workspace(session: Session, email: str | None = None) -> dict[str, Any]:
    """Workspace, its two roles and its creator, inserted in one transaction."""
    workspace_id, user_id = new_id(session), new_id(session)
    session.execute(
        text("INSERT INTO workspaces (id, name, created_by) VALUES (:w, 'Acme', :u)"),
        {"w": workspace_id, "u": user_id},
    )
    roles = {}
    for key in ("read_write", "read"):
        roles[key] = session.execute(
            text(
                "INSERT INTO roles (workspace_id, key, name, is_system) "
                "VALUES (:w, :k, :k, true) RETURNING id"
            ),
            {"w": workspace_id, "k": key},
        ).scalar_one()
    session.execute(
        text(
            "INSERT INTO users (id, workspace_id, role_id, email, name, password_hash) "
            "VALUES (:u, :w, :r, :e, 'Rosa', 'x')"
        ),
        {
            "u": user_id,
            "w": workspace_id,
            "r": roles["read_write"],
            "e": email or f"rosa-{uuid.uuid4().hex[:8]}@example.com",
        },
    )
    # Check the deferred creator key now, then defer again: the setting lasts for the whole
    # transaction, which the test fixture shares between units of work.
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    return {"workspace_id": workspace_id, "user_id": user_id, "roles": roles}


def test_the_system_workspace_exists_without_a_creator(db: Database) -> None:
    with db.unit_of_work() as uow:
        row = uow.session.execute(
            text("SELECT name, created_by FROM workspaces WHERE id = :id"),
            {"id": SYSTEM_WORKSPACE},
        ).one()
    assert row.name == "Signora (system)"
    assert row.created_by is None


def test_a_workspace_and_its_creator_are_inserted_together(db: Database) -> None:
    with db.unit_of_work() as uow:
        made = make_workspace(uow.session)
        creator = uow.session.execute(
            text("SELECT created_by FROM workspaces WHERE id = :w"), {"w": made["workspace_id"]}
        ).scalar_one()
    assert creator == made["user_id"]


def test_a_workspace_needs_a_creator(db: Database) -> None:
    with pytest.raises(IntegrityError, match="creator_required"), db.unit_of_work() as uow:
        uow.session.execute(text("INSERT INTO workspaces (name) VALUES ('Orphan')"))


def test_the_creator_must_be_a_real_user(db: Database) -> None:
    with (
        pytest.raises(IntegrityError, match="fk_workspaces_created_by_users"),
        db.unit_of_work() as uow,
    ):
        uow.session.execute(
            text("INSERT INTO workspaces (name, created_by) VALUES ('Ghost', uuidv7())")
        )
        uow.session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_a_user_cannot_hold_another_workspaces_role(db: Database) -> None:
    with db.unit_of_work() as uow:
        acme = make_workspace(uow.session)
        other = make_workspace(uow.session)
    with (
        pytest.raises(IntegrityError, match="fk_users_role_id_workspace_id_roles"),
        db.unit_of_work() as uow,
    ):
        uow.session.execute(
            text("UPDATE users SET role_id = :r WHERE id = :u"),
            {"r": other["roles"]["read"], "u": acme["user_id"]},
        )


def test_emails_are_unique_and_stored_normalised(db: Database) -> None:
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    with db.unit_of_work() as uow:
        make_workspace(uow.session, email=email)
    with pytest.raises(IntegrityError, match="uq_users_email"), db.unit_of_work() as uow:
        make_workspace(uow.session, email=email)
    with pytest.raises(IntegrityError, match="email_normalised"), db.unit_of_work() as uow:
        make_workspace(uow.session, email="Upper@Example.com")


def invite(session: Session, made: dict[str, Any], email: str) -> None:
    session.execute(
        text(
            "INSERT INTO invites (workspace_id, email, role_id, token_hash, invited_by, "
            "expires_at) VALUES (:w, :e, :r, :t, :by, now() + interval '7 days')"
        ),
        {
            "w": made["workspace_id"],
            "e": email,
            "r": made["roles"]["read"],
            "t": uuid.uuid4().bytes * 2,
            "by": made["user_id"],
        },
    )


def test_one_pending_invite_per_email_per_workspace(db: Database) -> None:
    with db.unit_of_work() as uow:
        made = make_workspace(uow.session)
        invite(uow.session, made, "sam@example.com")
    with pytest.raises(IntegrityError, match="uq_invites_pending_email"), db.unit_of_work() as uow:
        invite(uow.session, made, "sam@example.com")


def test_an_accepted_invite_does_not_block_a_new_one(db: Database) -> None:
    with db.unit_of_work() as uow:
        made = make_workspace(uow.session)
        invite(uow.session, made, "sam@example.com")
        uow.session.execute(
            text("UPDATE invites SET accepted_at = now() WHERE workspace_id = :w"),
            {"w": made["workspace_id"]},
        )
        invite(uow.session, made, "sam@example.com")  # allowed: the first is no longer pending


@pytest.mark.parametrize(
    ("purpose", "with_user", "allowed"),
    [("signup", False, True), ("signup", True, False), ("password_reset", False, False)],
)
def test_reset_tokens_belong_to_a_user_and_signup_tokens_do_not(
    db: Database, purpose: str, with_user: bool, allowed: bool
) -> None:
    with db.unit_of_work() as uow:
        made = make_workspace(uow.session)

    def insert() -> None:
        with db.unit_of_work() as uow:
            uow.session.execute(
                text(
                    "INSERT INTO email_tokens (purpose, email, user_id, token_hash, expires_at) "
                    "VALUES (:p, 'a@example.com', :u, :t, now() + interval '1 hour')"
                ),
                {"p": purpose, "u": made["user_id"] if with_user else None, "t": bytes(32)},
            )

    if allowed:
        insert()
    else:
        with pytest.raises(IntegrityError, match="reset_tokens_have_a_user"):
            insert()
