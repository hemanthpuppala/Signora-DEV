"""Password rules and hashing (Phase 2 LLD topic 3, NIST SP 800-63B).

Rules: length counted after Unicode NFKC normalisation, any characters, no composition rules, not
on the bundled list of common passwords. Hashing: Argon2id with the library's RFC 9106 low-memory
defaults; ``verify`` reports when a stored hash should be upgraded.
"""

from __future__ import annotations

import gzip
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher()
# Verified when the email is unknown, so log-in takes as long as for a real account.
DUMMY_HASH = _hasher.hash("signora-timing-equaliser")


@cache
def _common_passwords() -> frozenset[str]:
    data = files("signora.modules.identity_access.domain").joinpath("data/common-passwords.txt.gz")
    with data.open("rb") as raw, gzip.open(raw, "rt", encoding="utf-8") as lines:
        return frozenset(line.strip().casefold() for line in lines if line.strip())


def normalize_password(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int
    max_length: int = MAX_PASSWORD_LENGTH

    @property
    def rule(self) -> str:
        """The rule as people read it: the form hint and the too-short message (one wording)."""
        return f"Use {self.min_length} or more characters."

    def problem(self, password: str) -> str | None:
        """A user-facing reason the password is not allowed, or ``None`` when it is fine."""
        normalized = normalize_password(password)
        if len(normalized) < self.min_length:
            return self.rule
        if len(normalized) > self.max_length:
            return f"Use {self.max_length} or fewer characters."
        if normalized.casefold() in _common_passwords():
            return "This password is too common. Choose another."
        return None


def hash_password(password: str) -> str:
    return _hasher.hash(normalize_password(password))


@dataclass(frozen=True)
class Verification:
    ok: bool
    needs_rehash: bool = False


def verify_password(stored_hash: str, password: str) -> Verification:
    """Constant-time check; ``needs_rehash`` is set when the hash uses outdated parameters."""
    try:
        _hasher.verify(stored_hash, normalize_password(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return Verification(ok=False)
    return Verification(ok=True, needs_rehash=_hasher.check_needs_rehash(stored_hash))


def spend_verification_time(password: str) -> None:
    """Verify against a dummy hash: same cost as a real check, always fails."""
    verify_password(DUMMY_HASH, password)
