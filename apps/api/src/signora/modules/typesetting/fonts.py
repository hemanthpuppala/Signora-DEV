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

import pymupdf


@dataclass(frozen=True)
class Font:
    id: str
    family: str  # the name the browser gives it (FontFace) and the PDF embeds
    file: str  # in fonts/
    licence: str  # in fonts/, shipped beside the file


# Liberation Sans: SIL Open Font License 1.1, and Arial's widths, the commonest agreement font.
FONTS: tuple[Font, ...] = (
    Font(
        id="liberation-sans",
        family="Liberation Sans",
        file="LiberationSans-Regular.ttf",
        licence="LiberationSans-LICENSE.txt",
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
    """The font's glyph widths, read once per process."""
    return pymupdf.Font(fontfile=str(font_path(font_id)))
