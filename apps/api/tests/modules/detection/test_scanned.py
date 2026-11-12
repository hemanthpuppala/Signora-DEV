"""Scanned pages (Phase 5c): lines read from a page's pixels at exact positions, the AI shown the
pictures with each field's id drawn on them, extra fields placed from their box."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pymupdf
import pytest

from signora.modules.detection.ai import AiCall, Usage
from signora.modules.detection.derive import check, derive
from signora.modules.detection.read import read_document
from signora.modules.detection.run import ask
from signora.modules.detection.scan_images import marked_pages
from signora.modules.detection.scan_lines import scan_blanks

PARAGRAPH = "The parties have executed this Agreement as of the dates written below, in two copies."
Draw = Callable[[pymupdf.Page], object]


def _text(x: float, y: float, text: str) -> Draw:
    return lambda page: page.insert_text((x, y), text, fontsize=11)


def _line(x0: float, x1: float, y: float) -> Draw:
    return lambda page: page.draw_line((x0, y), (x1, y), width=0.75)


def _end(text: str, x: float = 72) -> float:
    return x + float(pymupdf.get_text_length(text, fontsize=11))


def _scan(*pages: list[Draw], keep_text: tuple[int, ...] = ()) -> bytes:
    """A document whose pages are drawn, then turned into pictures (a scanner's output), except
    the pages in ``keep_text`` (1-based), which keep their text layer."""
    drawn = pymupdf.open()
    for steps in pages:
        page = drawn.new_page()
        page.insert_text((72, 100), PARAGRAPH, fontsize=11)
        for step in steps:
            step(page)
    scanned = pymupdf.open()
    for number in range(1, drawn.page_count + 1):
        page = drawn.load_page(number - 1)
        if number in keep_text:
            scanned.insert_pdf(drawn, from_page=number - 1, to_page=number - 1)
            continue
        picture: pymupdf.Pixmap = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        out = scanned.new_page(width=page.rect.width, height=page.rect.height)
        out.insert_image(out.rect, pixmap=picture)
    data: bytes = scanned.tobytes()
    return data


def _boxes(data: bytes) -> list[tuple[float, float, float, float]]:
    document = pymupdf.open(stream=data, filetype="pdf")
    return [b.box for n in range(document.page_count) for b in scan_blanks(document.load_page(n))]


def test_a_line_after_a_label_is_found_at_its_exact_place() -> None:
    data = _scan([_text(72, 300, "Name:"), _line(_end("Name:") + 4, 300, 302)])
    ((x0, _, x1, y1),) = _boxes(data)
    assert abs(x0 - (_end("Name:") + 4)) <= 2 and abs(x1 - 300) <= 2 and abs(y1 - 302) <= 2


def test_typed_underscores_on_a_scan_are_one_line() -> None:
    data = _scan([_text(72, 300, "Date: " + "_" * 20)])
    ((x0, _, x1, _),) = _boxes(data)
    assert abs(x0 - _end("Date: ")) <= 3 and abs(x1 - _end("Date: " + "_" * 20)) <= 3


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [_text(72, 300, "Disclosing"), _line(72, _end("Disclosing"), 302)], id="underlined-word"
        ),
        pytest.param([_line(72, _end(PARAGRAPH), 260)], id="rule-across-the-text"),
        pytest.param(
            [_line(72, 300, y) for y in (240, 262, 284)]
            + [
                lambda page, x=x: page.draw_line((x, 240), (x, 284), width=0.75)
                for x in (72, 186, 300)
            ],
            id="ruled-table",
        ),
        pytest.param(
            [lambda page: page.draw_rect(pymupdf.Rect(300, 300, 302, 302), fill=(0, 0, 0))],
            id="a-speck",
        ),
    ],
)
def test_marks_that_are_not_blanks_give_nothing(steps: list[Draw]) -> None:
    assert _boxes(_scan(steps)) == []


def test_a_scanned_document_is_read_from_its_pictures() -> None:
    data = _scan(
        [_text(72, 300, "Name:"), _line(110, 300, 302)],
        [_text(72, 400, "Signature:"), _line(140, 360, 402)],
    )
    reading = read_document(data)
    assert reading.scanned_pages == [1, 2] and reading.fields_from == "blanks"
    assert [(f.placements[0].page, f.drawn) for f in reading.asked] == [(1, True), (2, True)]
    assert all(f.placements[0].headroom is not None for f in reading.asked)
    assert "--- page 1 (a scanned picture" in reading.layout and "⟦f1⟧" in reading.layout


def test_a_mixed_document_reads_text_pages_as_before_and_pictures_from_pixels() -> None:
    data = _scan(
        [_text(72, 300, "Name: " + "_" * 20)],
        [_text(72, 300, "Title:"), _line(110, 300, 302)],
        keep_text=(1,),
    )
    reading = read_document(data)
    assert reading.scanned_pages == [2]
    page_one, page_two = reading.asked
    assert (page_one.label, page_one.drawn) == ("Name:", False)  # from the text, as before
    assert (page_two.placements[0].page, page_two.drawn) == (2, True)
    with pymupdf.open(stream=data, filetype="pdf") as document:
        parts = marked_pages(document, reading)
    assert [part["type"] for part in parts] == ["text", "image_url"]  # the scanned page only
    assert parts[0]["text"].startswith("Page 2")


def test_the_ai_receives_the_pictures_with_the_text() -> None:
    data = _scan([_text(72, 300, "Name:"), _line(110, 300, 302)])
    reading = read_document(data)
    seen: list[list[dict[str, Any]]] = []

    class Capture:
        def assign(self, messages: list[dict[str, Any]], answer: Any) -> AiCall:
            seen.append(messages)
            return AiCall(
                answer={
                    "roles": [{"slug": "client", "kind": "signer"}],
                    "fields": [
                        {
                            "id": "f1",
                            "holds": "full_name",
                            "format": None,
                            "filled_by": "client",
                            "label": "Name",
                            "must_fill": True,
                            "depends_on": None,
                            "same_as": None,
                        }
                    ],
                    "checkbox_groups": [],
                    "extra_fields": [],
                    "document": {"name": "Agreement", "description": "An agreement."},
                },
                content="{}",
                request_id="r",
                model="m",
                latency_s=0.0,
                usage=Usage(input=0, cached=0, output=0, reasoning=0),
            )

    with pymupdf.open(stream=data, filetype="pdf") as document:
        calls, _, _ = ask(reading, document, Capture(), current_name="Agreement", instructions="")
    content = seen[0][1]["content"]
    assert len(calls) == 1 and isinstance(content, list)
    assert [part["type"] for part in content] == ["text", "text", "image_url"]
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def _answer(reading: Any, extra: list[dict[str, Any]], holds: str = "full_name") -> dict[str, Any]:
    return {
        "roles": [{"slug": "client", "kind": "signer"}],
        "fields": [
            {
                "id": f.id,
                "holds": holds,
                "format": None,
                "filled_by": "client",
                "label": f"Field {f.id}",
                "must_fill": True,
                "depends_on": None,
                "same_as": None,
            }
            for f in reading.asked
        ],
        "checkbox_groups": [],
        "extra_fields": extra,
        "document": None,
    }


def _extra(box: list[int] | None, holds: str = "title") -> dict[str, Any]:
    return {
        "page": 1,
        "anchor_text": "Title:",
        "box": box,
        "holds": holds,
        "format": None,
        "filled_by": "client",
        "label": "Title",
        "must_fill": False,
    }


def test_an_extra_field_on_a_scanned_page_is_placed_from_its_box_and_flagged() -> None:
    data = _scan([_text(72, 300, "Name:"), _line(110, 300, 302), _text(72, 340, "Title:")])
    reading = read_document(data)
    answer = _answer(reading, [_extra([180, 418, 490, 432])])
    with pymupdf.open(stream=data, filetype="pdf") as document:
        problems = check(answer, reading, document)
        result = derive(reading, answer, document, problems=problems, repaired=False)
    title = next(field for field in result.fields if field.label == "Title")
    page = reading.pages[0]  # the box is in thousandths of the page's own width and height
    expected = (180 * page.width / 1000, 418 * page.height / 1000, 490 * page.width / 1000)
    x0, y0, x1, _ = title.placements[0].rect
    assert problems == [] and (x0, y0, x1) == pytest.approx(expected, abs=0.1)
    assert title.needs_review == "placed from the scanned picture: check its position"


@pytest.mark.parametrize("box", [None, [500, 418, 180, 432], [0, 0, 1200, 10]])
def test_an_extra_field_on_a_scanned_page_without_a_valid_box_is_a_problem(
    box: list[int] | None,
) -> None:
    data = _scan([_text(72, 300, "Name:"), _line(110, 300, 302)])
    reading = read_document(data)
    answer = _answer(reading, [_extra(box)])
    with pymupdf.open(stream=data, filetype="pdf") as document:
        problems = check(answer, reading, document)
        result = derive(reading, answer, document, problems=problems, repaired=True)
    assert any("page 1 is a scanned picture: give the blank's box" in p for p in problems)
    assert all(field.label != "Title" for field in result.fields)


def test_a_signature_on_a_scanned_line_takes_the_room_measured_above_it() -> None:
    """F2 on a scan: no words to stop the box, so the free height read from the picture does."""
    roomy = _scan([_text(72, 300, "Signature"), _line(72, 300, 360)])
    tight = _scan(
        [_text(72, 350, "In witness whereof the parties have signed."), _line(72, 300, 364)]
    )
    for data, grows in ((roomy, True), (tight, False)):
        reading = read_document(data)
        (found,) = reading.asked
        before = found.placements[0].rect
        with pymupdf.open(stream=data, filetype="pdf") as document:
            (field,) = derive(
                reading, _answer(reading, [], "signature"), document, problems=[], repaired=False
            ).fields
        after = field.placements[0].rect
        assert after[3] == before[3]  # the line stays its bottom edge
        assert (after[1] < before[1] - 10) is grows  # grows into free space, never over text


def _scanner(data: bytes, *, angle: float = 0.0, blur: bool = False, dpi: int = 150) -> bytes:
    """A scanner's output of a drawn document: its pages turned by ``angle`` degrees about their
    centre (the page's size kept), blurred, at ``dpi``; with numpy only (nearest pixel)."""
    import numpy as np

    source = pymupdf.open(stream=data, filetype="pdf")
    out = pymupdf.open()
    for number in range(source.page_count):
        page = source.load_page(number)
        pix: pymupdf.Pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[
            :, : pix.width
        ]
        h, w = grey.shape
        ys, xs = np.mgrid[0:h, 0:w]
        t = np.radians(angle)
        sx = np.rint(w / 2 + (xs - w / 2) * np.cos(t) - (ys - h / 2) * np.sin(t)).astype(int)
        sy = np.rint(h / 2 + (xs - w / 2) * np.sin(t) + (ys - h / 2) * np.cos(t)).astype(int)
        inside = (sx >= 0) & (sx < w) & (sy >= 0) & (sy < h)
        turned = np.full_like(grey, 255)
        turned[inside] = grey[sy[inside], sx[inside]]
        if blur:
            padded = np.pad(turned.astype(np.float32), 1, mode="edge")
            shifted = [padded[dy : dy + h, dx : dx + w] for dy in range(3) for dx in range(3)]
            turned = (np.sum(shifted, axis=0) / 9).astype(np.uint8)
        image = pymupdf.Pixmap(
            pymupdf.csGRAY, w, h, np.ascontiguousarray(turned, dtype=np.uint8).tobytes(), False
        )
        target = out.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, pixmap=image)
    result: bytes = out.tobytes()
    return result


LINES = [
    _text(72, 300, "Name:"),
    _line(110, 300, 302),
    _text(72, 360, "Date:"),
    _line(110, 250, 362),
]


@pytest.mark.parametrize(
    ("angle", "blur", "dpi"),
    [
        pytest.param(1.0, False, 150, id="turned-1-degree"),
        pytest.param(-2.0, False, 150, id="turned-minus-2-degrees"),
        pytest.param(0.0, True, 100, id="blurred-100-dpi"),
        pytest.param(1.0, True, 100, id="turned-blurred-100-dpi"),
    ],
)
def test_a_real_scanners_page_still_gives_each_line_once(
    angle: float, blur: bool, dpi: int
) -> None:
    """The page is straightened before its lines are read (a turned line spans many pixel rows)
    and ink is judged against the page's own paper (a blurred line is grey)."""
    data = _scanner(_scan(LINES, keep_text=(1,)), angle=angle, blur=blur, dpi=dpi)
    boxes = sorted(_boxes(data), key=lambda b: b[3])
    assert len(boxes) == 2
    for (x0, _, x1, _), (lx0, lx1) in zip(boxes, ((110, 300), (110, 250)), strict=True):
        assert abs(x0 - lx0) <= 6 and abs(x1 - lx1) <= 6


def test_the_top_edge_of_bold_blurred_text_is_not_a_line() -> None:
    """Blurred, a bold heading's letters merge along their top into a long stroke with paper above
    it; letters lie under it, so it is no line."""

    def heading(page: pymupdf.Page) -> None:
        page.insert_text((72, 300), "NON-DISCLOSURE AGREEMENT", fontsize=18, fontname="hebo")

    data = _scanner(_scan([heading], keep_text=(1,)), blur=True, dpi=100)
    assert _boxes(data) == []


def test_two_blanks_of_a_row_at_slightly_different_feet_stay_two() -> None:
    """A turned page puts two blanks of one row a point apart in height; they are two blanks, not
    one box running backwards from the right one's start to the left one's end."""
    from signora.modules.detection.scan_lines import ScanBlank, _merge

    left = ScanBlank(box=(208.0, 108.0, 234.0, 121.4), headroom=12.0)
    right = ScanBlank(box=(326.0, 107.0, 470.0, 120.4), headroom=12.0)
    merged = sorted(b.box for b in _merge([right, left]))
    assert merged == [left.box, right.box]


def test_a_scan_with_a_fax_header_in_its_text_layer_is_read_from_its_picture() -> None:
    """Review #2: processing called such a page a scan (an image over it, under 20 characters of
    text) while detection called it text, so it reached review with no fields. One rule now."""
    data = _scan([_text(72, 300, "Name:"), _line(110, 300, 302)])
    document = pymupdf.open(stream=data, filetype="pdf")
    document[0].insert_text((20, 20), "FAX 11/12 p1", fontsize=7)  # a fax machine's header line
    faxed = document.tobytes()
    reading = read_document(faxed)
    assert reading.scanned_pages == [1] and len(reading.asked) == 1


def test_a_huge_page_is_read_within_the_pixel_budget() -> None:
    """Review #1: a scanned page was turned into pixels at 150 dpi whatever its size, so a 23 KB
    PDF with one 8000 pt page held 2 GB. A page's picture now holds at most MAX_PIXELS."""
    from signora.modules.detection.scan_lines import MAX_PIXELS, SCAN_DPI, render_dpi

    document = pymupdf.open()
    document.new_page(width=8000, height=8000)
    document.new_page(width=612, height=792)
    huge, letter = document.load_page(0), document.load_page(1)
    dpi = render_dpi(huge, SCAN_DPI)
    assert (8000 * dpi / 72) ** 2 <= MAX_PIXELS
    assert render_dpi(letter, SCAN_DPI) == SCAN_DPI  # an ordinary page keeps its resolution
    assert scan_blanks(huge) == []  # read, quickly, within the budget


def _upright_turned_scan(rotation: int) -> bytes:
    """A scan stored turned, its /Rotate showing it upright, as scanners write them: the line of
    "Name:" lies at (110..300, 302) as the page is shown."""
    drawn = pymupdf.open()
    page = drawn.new_page(width=612, height=792)
    page.insert_text((72, 100), PARAGRAPH, fontsize=11)
    page.insert_text((72, 300), "Name:", fontsize=11)
    page.draw_line((110, 302), (300, 302), width=0.75)
    picture: pymupdf.Pixmap = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    for stored in (0, 90, 180, 270):
        scan = pymupdf.open()
        width, height = (612, 792) if rotation in (0, 180) else (792, 612)
        sheet = scan.new_page(width=width, height=height)
        sheet.insert_image(sheet.rect, pixmap=picture, rotate=stored)
        sheet.set_rotation(rotation)
        data: bytes = scan.tobytes()
        found = read_document(data).asked
        if len(found) == 1 and abs(found[0].placements[0].rect[3] - 303) < 4:
            return data
    raise AssertionError(f"no upright layout for /Rotate {rotation}")


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_turned_pages_tag_sits_at_the_start_of_its_line(rotation: int) -> None:
    """Review #4: tags were drawn in the page's own unrotated space, so on /Rotate 180 and 270
    they landed at the line's end, upside down. They are drawn on the picture as shown now."""
    import base64

    data = _upright_turned_scan(rotation)
    reading = read_document(data)
    with pymupdf.open(stream=data, filetype="pdf") as document:
        part = marked_pages(document, reading)[1]
        width = document[0].rect.width
    picture = pymupdf.Pixmap(base64.b64decode(part["image_url"]["url"].split(",")[1]))
    scale = picture.width / width

    def red_near(x: float) -> int:
        return sum(
            1
            for dx in range(0, 30, 2)
            for dy in range(-14, 2, 2)
            if (lambda px: px[0] > 150 and px[1] < 90)(
                picture.pixel(int((x + dx) * scale), int((303 + dy) * scale))
            )
        )

    assert red_near(110) > 5 and red_near(270) == 0  # at the start, not at the end


def test_scanned_pages_go_to_the_ai_as_jpeg_within_a_hard_pixel_budget() -> None:
    """Review #3: every scanned page went as a full PNG in one request, unbounded. Pictures are
    JPEG now, within a page budget and a hard document budget (lower resolution, never more)."""
    from signora.modules.detection.scan_images import (
        DOCUMENT_PIXELS,
        IMAGE_DPI,
        PAGE_PIXELS,
        picture_dpis,
    )

    letters = pymupdf.open()
    for _ in range(200):  # the longest upload allowed
        letters.new_page(width=612, height=792)
    dpis = picture_dpis(letters, list(range(1, 201)))
    assert sum((dpi / 72) ** 2 * 612 * 792 for dpi in dpis.values()) <= DOCUMENT_PIXELS
    assert min(dpis.values()) >= 72  # still readable
    short = pymupdf.open()
    short.new_page(width=612, height=792)
    assert picture_dpis(short, [1]) == {1: IMAGE_DPI}  # an ordinary scan is not lowered
    assert (612 * IMAGE_DPI / 72) * (792 * IMAGE_DPI / 72) <= PAGE_PIXELS
    data = _scan([_text(72, 300, "Name:"), _line(110, 300, 302)])
    with pymupdf.open(stream=data, filetype="pdf") as document:
        part = marked_pages(document, read_document(data))[1]
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
