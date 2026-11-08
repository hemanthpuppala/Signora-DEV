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
