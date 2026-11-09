"""PDF facts and the safe working copy (Phase 4 LLD §3.1-3.2), with PyMuPDF.

Pure functions over bytes: no database, no blob store. MuPDF errors on a file it cannot read are
reported as ``DamagedPdfError``: a PDF the renderer cannot process cannot be shown or signed either.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pymupdf

# A page "lacks text" when an image covers at least this share of it and it has fewer than
# MIN_TEXT_CHARACTERS of extractable text: what a scanned page looks like. Pages that are blank,
# or carry only a little text and lines (a signature block), are not scans.
MIN_TEXT_CHARACTERS = 20
SCAN_IMAGE_SHARE = 1 / 3
# Saving with this removes encryption and restrictions (the constant is missing from the stubs).
_ENCRYPT_NONE = int(pymupdf.PDF_ENCRYPT_NONE)  # type: ignore[attr-defined]


class DamagedPdfError(Exception):
    pass


class PasswordRequiredError(Exception):
    pass


class TooManyPagesError(Exception):
    def __init__(self, pages: int) -> None:
        super().__init__(f"{pages} pages")
        self.pages = pages


@dataclass(frozen=True)
class PageFacts:
    """As displayed (rotation applied), in PDF points; Phase 6 places fields in these units."""

    width: float
    height: float
    rotation: int


@dataclass(frozen=True)
class Prepared:
    pdf: bytes  # the working copy
    pages: list[PageFacts]
    pages_without_text: list[int]  # 1-based


def _pages(document: pymupdf.Document) -> Iterator[pymupdf.Page]:
    for index in range(document.page_count):
        yield document.load_page(index)


@contextmanager
def _opened(data: bytes) -> Iterator[pymupdf.Document]:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError) as error:
        raise DamagedPdfError(str(error)) from error
    try:
        if document.page_count == 0:
            raise DamagedPdfError("no pages")
        yield document
    except (RuntimeError, ValueError) as error:
        if isinstance(error, (DamagedPdfError, TooManyPagesError, PasswordRequiredError)):
            raise
        raise DamagedPdfError(str(error)) from error
    finally:
        document.close()


def needs_password(data: bytes) -> bool:
    with _opened(data) as document:
        return bool(document.needs_pass)


def unlock(data: bytes, password: str) -> bytes | None:
    """The PDF without its encryption when ``password`` opens it, else None. Never logged."""
    with _opened(data) as document:
        if not document.needs_pass:
            return bytes(document.tobytes(encryption=_ENCRYPT_NONE))
        if not document.authenticate(password):
            return None
        return bytes(document.tobytes(encryption=_ENCRYPT_NONE))


def _lacks_text(page: pymupdf.Page) -> bool:
    if len("".join(page.get_text("text").split())) >= MIN_TEXT_CHARACTERS:
        return False
    page_area = abs(page.rect.width * page.rect.height) or 1.0
    for image in page.get_image_info():
        x0, y0, x1, y1 = image["bbox"]
        if abs((x1 - x0) * (y1 - y0)) / page_area >= SCAN_IMAGE_SHARE:
            return True
    return False


# Actions that run a script or reach outside the document (another file, an embedded one, a
# program, a form submission). Plain links (/URI, /GoTo within the document) are kept.
_UNSAFE_ACTIONS = frozenset(
    {
        "/JavaScript",
        "/Launch",
        "/SubmitForm",
        "/ImportData",
        "/Rendition",
        "/Movie",
        "/Sound",
        "/GoToE",
        "/GoToR",
    }
)


def _make_safe(document: pymupdf.Document) -> None:
    """Remove what could run or open something; keep the form fields themselves (Phase 5 reads
    them from the original, never from this copy)."""
    document.scrub(
        attached_files=True,
        embedded_files=True,
        javascript=True,
        clean_pages=False,
        hidden_text=False,
        metadata=False,
        redactions=False,
        remove_links=False,
        reset_fields=False,
        reset_responses=False,
        thumbnails=False,
        xml_metadata=False,
    )
    document.xref_set_key(document.pdf_catalog(), "OpenAction", "null")
    # One pass over every object: additional actions (/AA) on the catalog, pages, form fields and
    # annotations run on events (open, keystroke, calculate, focus), and an action (/A) of an
    # unsafe kind runs on a click. A field's /AA was left by scrub(javascript=True) (Phase 5 §2.1).
    # An action can also be its own object (referenced from /A), and any action can chain more
    # after it (/Next): a chain is dropped whole, and an unsafe action object is emptied wherever
    # it is referenced from (review fix).
    for xref in range(1, document.xref_length()):
        if document.xref_get_key(xref, "AA")[0] != "null":
            document.xref_set_key(xref, "AA", "null")
        if document.xref_get_key(xref, "A/S")[1] in _UNSAFE_ACTIONS:
            document.xref_set_key(xref, "A", "null")
        elif document.xref_get_key(xref, "A/Next")[0] != "null":
            document.xref_set_key(xref, "A/Next", "null")
        if document.xref_get_key(xref, "S")[1] in _UNSAFE_ACTIONS:
            document.update_object(xref, "<<>>")  # an action object: nothing left to run
        elif document.xref_get_key(xref, "Next")[0] != "null":
            document.xref_set_key(xref, "Next", "null")


def prepare(data: bytes, *, max_pages: int) -> Prepared:
    """Check and measure the PDF and make its working copy.

    Raises ``PasswordRequiredError``, ``TooManyPagesError`` or ``DamagedPdfError``. A PDF with
    only an owner password (edit restrictions) opens without one and is saved without them.
    """
    with _opened(data) as document:
        if document.needs_pass:
            raise PasswordRequiredError
        if document.page_count > max_pages:
            raise TooManyPagesError(document.page_count)
        pages = [
            PageFacts(
                width=round(page.rect.width, 2),
                height=round(page.rect.height, 2),
                rotation=page.rotation,
            )
            for page in _pages(document)
        ]
        without = [
            number for number, page in enumerate(_pages(document), start=1) if _lacks_text(page)
        ]
        _make_safe(document)
        pdf = bytes(document.tobytes(garbage=3, deflate=True, encryption=_ENCRYPT_NONE))
    return Prepared(pdf=pdf, pages=pages, pages_without_text=without)
