"""Signing links (Phase 7 LLD §11.2, ADR-E1)."""

from __future__ import annotations

import uuid

from signora.modules.envelopes.links import (
    LinkClaim,
    link_key,
    make_token,
    read_token,
    signing_url,
)

KEY = link_key("x" * 32)


def test_a_link_names_its_recipient_and_can_be_made_again() -> None:
    recipient = uuid.uuid4()
    token = make_token(KEY, recipient, 1)

    assert len(token) == 70 and token.isascii() and "=" not in token
    assert make_token(KEY, recipient, 1) == token  # shown again: the same link
    assert read_token(KEY, token) == LinkClaim(recipient, 1)
    assert signing_url("https://signora.example/", token) == f"https://signora.example/s/{token}"


def test_a_new_version_makes_a_different_link() -> None:
    recipient = uuid.uuid4()
    first, second = make_token(KEY, recipient, 1), make_token(KEY, recipient, 2)

    assert first != second
    assert read_token(KEY, first) == LinkClaim(recipient, 1)  # the caller refuses the old version


def test_anything_but_a_genuine_link_is_refused() -> None:
    token = make_token(KEY, uuid.uuid4(), 1)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    other_recipient = make_token(KEY, uuid.uuid4(), 1)

    assert read_token(KEY, tampered) is None
    assert read_token(link_key("y" * 32), token) is None  # another key: a rotated secret
    assert read_token(KEY, token[:-4]) is None
    assert read_token(KEY, "not a token at all!") is None
    assert read_token(KEY, "A" * 500) is None
    assert read_token(KEY, other_recipient[:30] + token[30:]) is None  # spliced
