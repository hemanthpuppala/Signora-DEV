"""Typesetting's API: a font's file, for the browser's preview and the signer's screen (7b LLD)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from signora.kernel.errors import NotFound
from signora.modules.typesetting.fonts import UnknownFontError, font_path

router = APIRouter(prefix="/api/v1", tags=["typesetting"])


@router.get(
    "/fonts/{font_id}",
    summary="A font's file (TrueType); public, and the same bytes for an id forever",
    response_class=FileResponse,
    responses={200: {"content": {"font/ttf": {}}}},
)
def font_file(font_id: str) -> FileResponse:
    try:
        path = font_path(font_id)
    except UnknownFontError:
        raise NotFound from None
    # Public: a signer opens a link without a session. An id names one file forever.
    return FileResponse(
        path,
        media_type="font/ttf",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
