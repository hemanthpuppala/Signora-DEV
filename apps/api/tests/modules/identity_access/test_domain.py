"""Pure identity rules (Phase 2 LLD topics 3, 4, 8)."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from signora.modules.identity_access.domain import passwords
from signora.modules.identity_access.domain.emails import (
    InvalidEmailError,
    email_domain,
    normalize_email,
)
from signora.modules.identity_access.domain.passwords import (
    PasswordPolicy,
    hash_password,
    spend_verification_time,
    verify_password,
)
from signora.modules.identity_access.domain.permissions import (
    DEFAULT_ROLES,
    Permission,
    parse_permissions,
)
from signora.modules.identity_access.domain.tokens import (
    csrf_matches,
    csrf_token,
    hash_token,
    issue_token,
)

POLICY = PasswordPolicy(min_length=12)


def full_width(ascii_letters: str) -> str:
    """The same letters as typed on a full-width (e.g. Japanese) keyboard: U+FF41 onwards."""
    return "".join(chr(ord(letter) + 0xFEE0) for letter in ascii_letters)


# --- emails ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Rosa.Hale@Example.COM ", "rosa.hale@example.com"),
        ("rosa+signora@gmail.com", "rosa+signora@gmail.com"),  # +tags kept as typed
        ("r.o.s.a@gmail.com", "r.o.s.a@gmail.com"),  # dots kept as typed
    ],
)
def test_emails_are_trimmed_and_lowercased_only(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not-an-email", "a@b@c.com", "rosa@", "@example.com", "a" * 250 + "@x.com"],
)
def test_invalid_emails_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalize_email(raw)


def test_email_domain() -> None:
    assert email_domain("rosa@example.com") == "example.com"


# --- password rules ----------------------------------------------------------------------------


def test_length_is_counted_after_normalisation() -> None:
    assert POLICY.problem("a" * 11) == "Use 12 or more characters."
    assert POLICY.problem("correct horse battery") is None  # spaces allowed, no composition rules
    # Full-width letters normalise (NFKC) to ASCII letters: the length is unchanged.
    assert POLICY.problem(full_width("qwertyuiopasd")) is None
    assert POLICY.problem("x" * 129) == "Use 128 or fewer characters."
    assert POLICY.problem("😀" * 12) is None  # any characters


@pytest.mark.parametrize("common", ["password1234", "PASSWORD1234", "qwertyuiop123"])
def test_common_passwords_are_rejected_case_insensitively(common: str) -> None:
    assert POLICY.problem(common) == "This password is too common. Choose another."


def test_the_common_list_is_bundled_and_complete() -> None:
    common = passwords._common_passwords()
    assert len(common) > 95_000
    assert "123456" in common


def test_minimum_length_is_configurable() -> None:
    assert PasswordPolicy(min_length=15).problem("a much longer pw") is None
    assert PasswordPolicy(min_length=15).problem("short but fine") == "Use 15 or more characters."


# --- hashing -----------------------------------------------------------------------------------


def test_hash_is_argon2id_and_verifies_the_normalised_password() -> None:
    stored = hash_password(full_width("correct") + " horse 42")

    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "correct horse 42").ok  # same password typed on another device
    assert not verify_password(stored, "correct horse 43").ok
    assert not verify_password("not-a-hash", "anything").ok


def test_outdated_hash_parameters_are_flagged_for_upgrade() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash("pass phrase 1")

    result = verify_password(weak, "pass phrase 1")

    assert result.ok and result.needs_rehash
    assert not verify_password(hash_password("pass phrase 1"), "pass phrase 1").needs_rehash


def test_dummy_verification_never_succeeds() -> None:
    spend_verification_time("anything at all")  # must not raise


# --- tokens ------------------------------------------------------------------------------------


def test_tokens_are_256_bit_and_stored_only_as_their_hash() -> None:
    token = issue_token()

    assert len(token.value) >= 43  # 32 bytes, URL-safe base64
    assert token.digest == hash_token(token.value)
    assert len(token.digest) == 32
    assert issue_token().value != token.value


def test_csrf_token_is_bound_to_the_session_and_the_secret() -> None:
    session = hash_token("session-a")
    token = csrf_token("k" * 48, session)

    assert csrf_matches("k" * 48, session, token)
    assert not csrf_matches("k" * 48, hash_token("session-b"), token)
    assert not csrf_matches("x" * 48, session, token)
    assert not csrf_matches("k" * 48, session, None)
    assert not csrf_matches("k" * 48, session, "")


# --- permissions -------------------------------------------------------------------------------


def test_unknown_permissions_are_ignored_not_fatal() -> None:
    known, unknown = parse_permissions(["members.manage", "projects.archive", "workspace.rename"])

    assert known == {Permission.MEMBERS_MANAGE, Permission.WORKSPACE_RENAME}
    assert unknown == {"projects.archive"}


def test_default_roles_match_the_agreed_rules() -> None:
    roles = {role.key: role for role in DEFAULT_ROLES}

    assert roles["read"].permissions == frozenset()
    assert roles["read_write"].permissions == {
        Permission.MEMBERS_DIRECTORY,
        Permission.WORKSPACE_RENAME,
        Permission.DEPARTMENTS_CREATE,
        Permission.DEPARTMENTS_MANAGE,
        Permission.DOCUMENTS_VIEW_SENDS,
        Permission.DOCUMENTS_SEND,
    }
    # Managing people and editing roles belong to the creator by default (owner decision).
    for role in DEFAULT_ROLES:
        assert Permission.MEMBERS_MANAGE not in role.permissions
        assert Permission.ROLES_MANAGE not in role.permissions
