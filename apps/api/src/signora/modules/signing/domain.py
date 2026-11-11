"""Signing's pure rules (Phase 8 LLD): what a person sees of their email, and their next step."""

from __future__ import annotations

from typing import Literal

Step = Literal["verify", "consent", "sign", "done"]


def mask_email(email: str) -> str:
    """``m•••@example.com``: the first character of the local part, then dots (§2.1.8)."""
    local, _, domain = email.partition("@")
    shown = local[0] if len(local) > 1 else ""
    return f"{shown}•••@{domain}"


def next_step(*, signed: bool, needs_code: bool, verified: bool, consented: bool) -> Step:
    """The first step the person still has (§1.5): their done screen once signed; else the email
    code when the envelope asks for it, then consent, then the document."""
    if signed:
        return "done"
    if needs_code and not verified:
        return "verify"
    if not consented:
        return "consent"
    return "sign"
