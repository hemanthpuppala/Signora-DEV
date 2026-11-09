"""Generated test files: PDFs and Word documents built in code, never checked in."""

from __future__ import annotations

import io
import zipfile

import docx
import pymupdf


def pdf_bytes(
    pages: int = 1, *, text: str = "Engagement letter between the firm and the client."
) -> bytes:
    document = pymupdf.open()
    for number in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"{text} Page {number + 1}.")
    data = document.tobytes()
    document.close()
    return bytes(data)


def docx_bytes(text: str = "Engagement letter between the firm and the client.") -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def zip_bytes(names: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in names.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def docm_bytes() -> bytes:
    """A macro-enabled Word file saved with a .docx name."""
    buffer = io.BytesIO(docx_bytes())
    with zipfile.ZipFile(buffer, "a") as archive:
        archive.writestr("word/vbaProject.bin", b"macros")
    return buffer.getvalue()


def encrypted_word_bytes() -> bytes:
    """The shape of a password-protected .docx: an OLE compound file with an EncryptedPackage
    stream (the detector looks only at the signature and the stream name)."""
    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
    return header + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 1024


def _image_pixmap() -> pymupdf.Pixmap:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 80), False)
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    return pixmap


def pdf_with_scan(
    scanned_pages: list[int], pages: int = 3, *, blank: list[int] | None = None
) -> bytes:
    """Text pages, except ``scanned_pages`` (a full-page image) and ``blank`` (nothing at all),
    numbered from 1."""
    document = pymupdf.open()
    for number in range(1, pages + 1):
        page = document.new_page()
        if number in scanned_pages:
            page.insert_image(page.rect, pixmap=_image_pixmap())
            page.insert_text((72, 800), str(number))  # a typed page number on a scan
        elif number not in (blank or []):
            page.insert_text((72, 72), f"Clause {number}: the client agrees to the terms of work.")
    data = document.tobytes()
    document.close()
    return bytes(data)


def pdf_with_signature_block() -> bytes:
    """A last page with little text and a line: not a scan."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 700), "Signed:")
    page.draw_line((130, 702), (400, 702))
    data = document.tobytes()
    document.close()
    return bytes(data)


def encrypted_pdf(user_password: str, owner_password: str = "owner-secret") -> bytes:  # noqa: S107 - test value
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Confidential engagement letter for the client.")
    data = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,  # type: ignore[attr-defined]  # missing from stubs
        user_pw=user_password,
        owner_pw=owner_password,
        permissions=int(pymupdf.PDF_PERM_PRINT),  # type: ignore[attr-defined]
    )
    document.close()
    return bytes(data)


def form_with_scripts() -> bytes:
    """Form fields carrying their own scripts, as Acrobat forms do: a calculation and a keystroke
    script on a field, a script on a parent field its kids inherit, a JavaScript click action on a
    button, and a link annotation that runs JavaScript."""
    document = pymupdf.open()
    page = document.new_page()
    for name, rect in (
        ("fee", (72, 100, 200, 120)),
        ("total", (72, 140, 200, 160)),
        ("print", (72, 180, 200, 200)),
    ):
        widget = pymupdf.Widget()
        widget.field_type = (
            pymupdf.PDF_WIDGET_TYPE_BUTTON if name == "print" else pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
        )
        widget.field_name = name
        widget.rect = pymupdf.Rect(rect)
        page.add_widget(widget)
    xrefs = {w.field_name: w.xref for w in page.widgets()}
    document.xref_set_key(
        xrefs["total"],
        "AA",
        '<</C<</S/JavaScript/JS(AFSimple_Calculate\\("SUM", new Array\\("fee"\\)\\);)>>'
        "/K<</S/JavaScript/JS(app.alert\\(1\\))>>>>",
    )
    document.xref_set_key(xrefs["print"], "A", "<</S/JavaScript/JS(this.print\\(\\))>>")
    parent = document.get_new_xref()  # a parent field whose action its kid inherits
    document.update_object(
        parent, "<</T(group)/Kids[]/AA<</F<</S/JavaScript/JS(app.alert\\(2\\))>>>>>>"
    )
    document.xref_set_key(xrefs["fee"], "Parent", f"{parent} 0 R")
    document.xref_set_key(parent, "Kids", f"[{xrefs['fee']} 0 R]")
    page.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(72, 220, 200, 240),
            "uri": "https://example.com",
        }
    )
    link_annot = pymupdf.PDF_ANNOT_LINK  # type: ignore[attr-defined]
    link_xref = next(xref for xref, kind, *_ in page.annot_xrefs() if kind == link_annot)
    document.xref_set_key(link_xref, "A", "<</S/JavaScript/JS(app.launchURL\\(1\\))>>")
    page.insert_link(  # an ordinary link, which stays
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(72, 260, 200, 280),
            "uri": "https://example.org",
        }
    )
    data = document.tobytes()
    document.close()
    return bytes(data)


def risky_pdf() -> bytes:
    """JavaScript on open, an embedded file, a launch link and a form field."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Engagement letter between the firm and the client.")
    script = document.get_new_xref()
    document.update_object(script, "<</S/JavaScript/JS(app.alert(1))>>")
    document.xref_set_key(document.pdf_catalog(), "OpenAction", f"{script} 0 R")
    document.embfile_add("payload.txt", b"hidden")
    page.insert_link(
        {"kind": pymupdf.LINK_LAUNCH, "from": pymupdf.Rect(72, 100, 200, 120), "file": "calc.exe"}
    )
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
    widget.field_name = "client_name"
    widget.rect = pymupdf.Rect(72, 200, 300, 220)
    page.add_widget(widget)
    data = document.tobytes()
    document.close()
    return bytes(data)


def links_reaching_outside() -> bytes:
    """Links whose actions reach outside the document in ways a top-level check misses: a link
    that opens another file (/GoToR), a safe link with a launch chained after it (/Next), and a
    link whose action is its own object (an indirect /A). An ordinary link stays alongside."""
    document = pymupdf.open()
    page = document.new_page()
    link_annot = pymupdf.PDF_ANNOT_LINK  # type: ignore[attr-defined]
    actions = (
        "<</S/GoToR/F(\\\\\\\\host\\\\share\\\\x.pdf)/D[0/Fit]>>",
        "<</S/URI/URI(https://example.com)/Next<</S/Launch/F(cmd.exe)>>>>",
        None,  # an indirect action object, below
        "<</S/URI/URI(https://example.org)>>",
    )
    indirect = document.get_new_xref()
    document.update_object(indirect, "<</S/Launch/F(calc.exe)>>")
    for index, action in enumerate(actions):
        top = 100 + index * 40
        page.insert_link(
            {"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, top, 200, top + 20), "uri": "x"}
        )
        xref = [x for x, kind, *_ in page.annot_xrefs() if kind == link_annot][-1]
        document.xref_set_key(xref, "A", action or f"{indirect} 0 R")
    return bytes(document.tobytes())
