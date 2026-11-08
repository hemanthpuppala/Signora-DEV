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
