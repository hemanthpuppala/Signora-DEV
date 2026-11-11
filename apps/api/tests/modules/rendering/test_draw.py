"""Writing values and signatures into a PDF (Phase 8 LLD §10): the original's pages, every value
as page content where the preview draws it, the envelope's ID on every page, nothing editable or
runnable left, and fast enough for a long agreement."""

from __future__ import annotations

import time
import uuid

import pymupdf

from signora.modules.rendering import DrawnSignature, Item, Mark, Text, TypedSignature, render

ENVELOPE = uuid.UUID("0193a5f2-0000-7000-8000-000000000001")


def _pdf(pages: int = 1, *, rotate: int = 0, form: bool = False) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), "MUTUAL NON-DISCLOSURE AGREEMENT", fontsize=12)
        if rotate:
            page.set_rotation(rotate)
    if form:
        page = doc[0]
        widget = pymupdf.Widget()
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]  # not in the stubs
        widget.field_name = "name"
        widget.rect = pymupdf.Rect(72, 200, 272, 220)
        page.add_widget(widget)
        page.insert_link(
            {
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(72, 90, 200, 104),
                "uri": "https://example.com",
            }
        )
    out: bytes = doc.tobytes()
    doc.close()
    return out


def _open(data: bytes) -> pymupdf.Document:
    return pymupdf.open(stream=data, filetype="pdf")


def test_values_and_the_envelope_id_are_page_content_where_the_preview_puts_them() -> None:
    items: list[Item] = [
        Text(1, (72, 300, 272, 320), "Maya Chen", 11, "liberation-sans"),
        Mark(1, (72, 340, 84, 352)),
        TypedSignature(1, (300, 600, 500, 640), "Maya Chen", "allura", "0123456789abcdef"),
        DrawnSignature(
            1, (300, 660, 500, 700), [[(100, 200), (500, 260), (900, 180)]], "fedcba9876543210"
        ),
    ]

    signed = _open(render(_pdf(), items, envelope_id=ENVELOPE))

    page = signed[0]
    words = page.get_text()
    assert "MUTUAL NON-DISCLOSURE AGREEMENT" in words  # the original's page is kept
    assert "Maya Chen" in words
    assert f"Signora envelope ID: {str(ENVELOPE).upper()}" in words
    assert "Signed by:" in words and "0123456789ABCDEF" in words
    name = next(
        b
        for b in page.get_text("dict")["blocks"]
        for line in b.get("lines", [])
        for s in line["spans"]
        if s["text"] == "Maya Chen"
    )
    x0, _, x1, _ = name["bbox"]
    assert abs(((x0 + x1) / 2) - 172) < 2  # centred in its box, as the preview
    assert page.get_drawings()  # the tick and the drawn signature are lines on the page


def test_nothing_editable_or_runnable_is_left() -> None:
    signed = _open(render(_pdf(form=True), [], envelope_id=ENVELOPE))

    assert list(signed[0].widgets() or []) == []
    assert signed[0].get_links() == []
    assert not signed.is_form_pdf


def test_a_rotated_page_is_drawn_as_it_is_displayed() -> None:
    signed = _open(
        render(
            _pdf(rotate=90),
            [Text(1, (72, 300, 272, 320), "Founder", 11, "liberation-sans")],
            envelope_id=ENVELOPE,
        )
    )

    page = signed[0]
    hit = page.search_for("Founder")
    assert hit
    shown = hit[0] * page.rotation_matrix  # back to displayed coordinates
    assert 60 < shown.x0 < 280 and 280 < shown.y1 < 330


def test_a_hundred_page_agreement_renders_in_under_three_seconds() -> None:
    pdf = _pdf(100)
    items = [
        Text(n, (72, 300, 272, 320), f"Value {n}", 11, "liberation-sans") for n in range(1, 101)
    ]

    started = time.perf_counter()
    signed = render(pdf, items, envelope_id=ENVELOPE)
    elapsed = time.perf_counter() - started

    assert elapsed < 3.0, f"{elapsed:.2f} s"
    assert _open(signed).page_count == 100
