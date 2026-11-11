"""Typesetting module: how a filled value is drawn on its page (Phase 7b LLD) — the fonts and the
rule that fits a value to its box, shared by the preview's data and the signed PDF.

Public interface — other modules import only from here.
"""

from signora.modules.typesetting.fit import fitted_size, place_size
from signora.modules.typesetting.fonts import (
    DEFAULT_FONT,
    FONTS,
    Font,
    FontUse,
    UnknownFontError,
    font,
    fonts_for,
    has_glyphs,
)
from signora.modules.typesetting.routes import router
from signora.modules.typesetting.sizes import Measured, text_sizes
from signora.modules.typesetting.views import FIT_RULE, FitRule, FontView, font_view

__all__ = [
    "DEFAULT_FONT",
    "FIT_RULE",
    "FONTS",
    "FitRule",
    "Font",
    "FontUse",
    "FontView",
    "Measured",
    "UnknownFontError",
    "fitted_size",
    "font",
    "font_view",
    "fonts_for",
    "has_glyphs",
    "place_size",
    "router",
    "text_sizes",
]
