"""The fonts a filled value is drawn in (Phase 7b LLD): one list, one default. Pure.

A font's id names one file forever: a changed file is a new font with a new id, so an envelope that
recorded a font keeps drawing with the same letters, and the file can be cached as immutable.
Every font is open-licence and kept here with its licence; nothing is fetched at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Literal

import pymupdf

from signora.modules.typesetting.mupdf import MUPDF_LOCK

FontUse = Literal["text", "signature", "certificate"]


@dataclass(frozen=True)
class Font:
    id: str
    family: str  # the name the browser gives it (FontFace) and the PDF embeds
    file: str  # in fonts/
    licence: str  # in fonts/, shipped beside the file
    use: FontUse = "text"  # a filled value's, a typed signature's (§5.2), or the certificate's


# Liberation Sans: SIL Open Font License 1.1, and Arial's widths, the commonest agreement font.
# Each file's licence ships beside it.
FONTS: tuple[Font, ...] = (
    Font(
        id="liberation-sans",
        family="Liberation Sans",
        file="LiberationSans-Regular.ttf",
        licence="LiberationSans-LICENSE.txt",
    ),
    # The certificate of completion's headings and fingerprints (Phase 8 §11): the same family,
    # under the same licence as Liberation Sans.
    Font(
        id="liberation-sans-bold",
        family="Liberation Sans Bold",
        file="LiberationSans-Bold.ttf",
        licence="LiberationSans-LICENSE.txt",
        use="certificate",
    ),
    Font(
        id="liberation-mono",
        family="Liberation Mono",
        file="LiberationMono-Regular.ttf",
        licence="LiberationSans-LICENSE.txt",
        use="certificate",
    ),
    # Typed signatures' handwriting styles (Phase 8 §5.2), SIL Open Font License 1.1 each.
    Font(
        id="great-vibes",
        family="Great Vibes",
        file="GreatVibes-Regular.ttf",
        licence="GreatVibes-LICENSE.txt",
        use="signature",
    ),
    Font(
        id="allura",
        family="Allura",
        file="Allura-Regular.ttf",
        licence="Allura-LICENSE.txt",
        use="signature",
    ),
    Font(
        id="sacramento",
        family="Sacramento",
        file="Sacramento-Regular.ttf",
        licence="Sacramento-LICENSE.txt",
        use="signature",
    ),
)
DEFAULT_FONT = "liberation-sans"

_BY_ID = {font.id: font for font in FONTS}


class UnknownFontError(LookupError):
    pass


def font(font_id: str) -> Font:
    try:
        return _BY_ID[font_id]
    except KeyError:
        raise UnknownFontError(font_id) from None


def font_path(font_id: str) -> Path:
    """The font's file on disk (inside the installed package)."""
    return Path(str(files(__package__).joinpath("fonts", font(font_id).file)))


@cache
def metrics(font_id: str) -> pymupdf.Font:
    """The font's glyph widths, read once per process. Not for use across threads: measure with
    ``text_width``."""
    return pymupdf.Font(fontfile=str(font_path(font_id)))


def text_width(text: str, font_id: str, size: float = 1.0) -> float:
    """The width of ``text`` in the font at ``size`` points: the sum of its glyphs' advances, no
    kerning (as the PDF draws it). O(len(text)); safe from any thread."""
    with MUPDF_LOCK:
        return float(metrics(font_id).text_length(text, fontsize=size))


def fonts_for(use: FontUse) -> list[Font]:
    """The fonts offered for a use, in the list's order. Adding one is its file, its licence and
    one entry in ``FONTS``."""
    return [entry for entry in FONTS if entry.use == use]


def has_glyphs(font_id: str, text: str) -> bool:
    """Whether the font draws every letter of ``text`` (spaces aside): a typed signature is never
    offered in a font that would draw a box for a letter of the name. O(len(text))."""
    with MUPDF_LOCK:
        face = metrics(font_id)
        return all(face.has_glyph(ord(char)) for char in text if not char.isspace())
