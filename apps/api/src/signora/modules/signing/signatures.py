"""Signatures and initials (Phase 8 LLD §5): adopted once per envelope, placed by a tap or by Apply
to all, kept as evidence with a fingerprint.

A typed signature is its text in a handwriting font; a drawn one is its strokes, integer points in
a 1000 x 400 box, smoothed on the page before they are sent and never on the server, so what was
seen is what is kept.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from signora.kernel.db import UnitOfWork
from signora.kernel.errors import FieldError, ValidationFailed
from signora.modules.typesetting import FontView, UnknownFontError, font, font_view, fonts_for
from signora.modules.typesetting import has_glyphs as _has_glyphs

Kind = Literal["signature", "initials"]
Method = Literal["typed", "drawn"]

WIDTH, HEIGHT = 1000, 400
MAX_STROKES = 50
MAX_POINTS = 5000
MIN_INK = 30.0  # units of line, so a dot or a blank pad is not a signature


class SignatureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Method
    text: str | None = Field(default=None, max_length=100)
    font: str | None = Field(default=None, max_length=60)
    strokes: list[list[tuple[int, int]]] | None = Field(default=None, max_length=MAX_STROKES)


class Adopted(BaseModel):
    """An adopted signature as the page draws it and the certificate names it."""

    kind: Kind
    method: Method
    text: str | None
    font: FontView | None
    strokes: list[list[tuple[int, int]]] | None
    signature_id: str  # the first 16 hexadecimal characters of its sha256 (§10.1.4)


def _ink(strokes: list[list[tuple[int, int]]]) -> float:
    return sum(
        math.dist(stroke[i - 1], stroke[i]) for stroke in strokes for i in range(1, len(stroke))
    )


def checked(body: SignatureIn) -> tuple[str | None, str | None, list[list[tuple[int, int]]] | None]:
    """The signature as it is kept, or ``ValidationFailed`` saying why. O(points)."""
    if body.method == "typed":
        words = (body.text or "").strip()
        if not words:
            raise ValidationFailed([FieldError("text", "Type your name")])
        try:
            chosen = font(body.font or "")
        except UnknownFontError:
            raise ValidationFailed([FieldError("font", "Choose a style")]) from None
        if chosen.use != "signature":
            raise ValidationFailed([FieldError("font", "Choose a style")])
        if not _has_glyphs(chosen.id, words):
            raise ValidationFailed([FieldError("text", "Draw your signature instead")])
        return words, chosen.id, None
    strokes = [stroke for stroke in (body.strokes or []) if stroke]
    points = sum(len(stroke) for stroke in strokes)
    if points > MAX_POINTS:
        raise ValidationFailed(
            [FieldError("strokes", "Too long a drawing. Clear it and draw again")]
        )
    if any(not (0 <= x <= WIDTH and 0 <= y <= HEIGHT) for stroke in strokes for x, y in stroke):
        raise ValidationFailed([FieldError("strokes", "Draw inside the box")])
    if _ink(strokes) < MIN_INK:
        raise ValidationFailed([FieldError("strokes", "Draw your signature")])
    return None, None, strokes


def fingerprint(
    kind: str, method: str, words: str | None, font_id: str | None, strokes: Any
) -> bytes:
    """SHA-256 of the canonical JSON of what was adopted (§5.5)."""
    canonical = json.dumps(
        {"kind": kind, "method": method, "text": words, "font": font_id, "strokes": strokes},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).digest()


def adopt(
    uow: UnitOfWork, recipient_id: uuid.UUID, workspace_id: uuid.UUID, kind: Kind, body: SignatureIn
) -> Adopted:
    """Adopt (or change) the person's signature or initials for this envelope. Every place they
    already signed takes the new one: a place's value names the kind, not a version of it."""
    words, font_id, strokes = checked(body)
    digest = fingerprint(kind, body.method, words, font_id, strokes)
    uow.session.execute(
        text(
            """
            INSERT INTO signing_signatures (recipient_id, workspace_id, kind, method, text, font,
                                            strokes, sha256)
            VALUES (:r, :w, :k, :m, :t, :f, CAST(:s AS jsonb), :h)
            ON CONFLICT (recipient_id, kind) DO UPDATE
            SET method = EXCLUDED.method, text = EXCLUDED.text, font = EXCLUDED.font,
                strokes = EXCLUDED.strokes, sha256 = EXCLUDED.sha256, adopted_at = now()
            """
        ),
        {
            "r": recipient_id,
            "w": workspace_id,
            "k": kind,
            "m": body.method,
            "t": words,
            "f": font_id,
            "s": json.dumps(strokes) if strokes is not None else None,
            "h": digest,
        },
    )
    return _view(kind, body.method, words, font_id, strokes, digest)


def _view(
    kind: str, method: str, words: str | None, font_id: str | None, strokes: Any, digest: bytes
) -> Adopted:
    return Adopted(
        kind=kind,  # type: ignore[arg-type]
        method=method,  # type: ignore[arg-type]
        text=words,
        font=font_view(font_id) if font_id else None,
        strokes=strokes,
        signature_id=digest.hex()[:16],
    )


def adopted(uow: UnitOfWork, recipient_id: uuid.UUID) -> dict[str, Adopted]:
    """The person's adopted signature and initials, by kind."""
    rows = uow.session.execute(
        text(
            "SELECT kind, method, text, font, strokes, sha256 FROM signing_signatures "
            "WHERE recipient_id = :r"
        ),
        {"r": recipient_id},
    )
    return {
        row.kind: _view(row.kind, row.method, row.text, row.font, row.strokes, bytes(row.sha256))
        for row in rows
    }


def signature_fonts() -> list[FontView]:
    return [font_view(entry.id) for entry in fonts_for("signature")]
