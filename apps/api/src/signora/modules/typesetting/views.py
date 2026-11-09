"""What a screen needs to draw values as the signed PDF will (Phase 7b LLD): the font, by its file's
address, and the fit rule's numbers, so the browser measures with them and no rule of its own."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from signora.modules.typesetting import fit
from signora.modules.typesetting.fonts import font


class FontView(BaseModel):
    id: str
    family: str
    url: str  # the font's file, served by this API (GET /api/v1/fonts/{id})


class FitRule(BaseModel):
    min_size: float
    fallback_ratio: float
    fallback_cap: float
    baseline_ratio: float
    baseline_min: float
    align: Literal["left", "center"]


FIT_RULE = FitRule(
    min_size=fit.MIN_SIZE,
    fallback_ratio=fit.FALLBACK_RATIO,
    fallback_cap=fit.FALLBACK_CAP,
    baseline_ratio=fit.BASELINE_RATIO,
    baseline_min=fit.BASELINE_MIN,
    align=fit.ALIGN,
)


def font_view(font_id: str) -> FontView:
    chosen = font(font_id)
    return FontView(id=chosen.id, family=chosen.family, url=f"/api/v1/fonts/{chosen.id}")
