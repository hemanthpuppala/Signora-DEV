"""Pure document rules (Phase 4 LLD topics 1-2). No web framework or database imports.

The file type comes from the contents, never the name or the browser's type (§2.1).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from signora.modules.documents.errors import ProtectedWordFile, UnsupportedFile

Kind = Literal["pdf", "docx"]

NAME_MAX = 120
DESCRIPTION_MAX = 500
AI_INSTRUCTIONS_MAX = 1000
FILENAME_MAX = 255

_PDF_MAGIC = b"%PDF-"
_PDF_MAGIC_WITHIN = 1024  # readers accept leading junk before the header; so do we, this far
_ZIP_MAGIC = b"PK\x03\x04"
_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE compound file: old .doc, or encrypted OOXML
# An encrypted .docx is a compound file holding a stream with this (UTF-16LE) name.
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")
_DOCX_REQUIRED = frozenset({"[Content_Types].xml", "word/document.xml"})
_DOCX_MACROS = "word/vbaProject.bin"  # .docm saved as .docx: refused, macros never enter
_SCAN_CHUNK = 1024 * 1024
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def detect_kind(path: Path) -> Kind:
    """``pdf`` or ``docx`` from the bytes; raises ``UnsupportedFile`` or ``ProtectedWordFile``."""
    with path.open("rb") as handle:
        head = handle.read(_PDF_MAGIC_WITHIN)
    if _PDF_MAGIC in head:
        return "pdf"
    if head.startswith(_ZIP_MAGIC):
        if _is_docx(path):
            return "docx"
        raise UnsupportedFile
    if head.startswith(_CFB_MAGIC) and _contains(path, _ENCRYPTED_PACKAGE):
        raise ProtectedWordFile
    raise UnsupportedFile


def _is_docx(path: Path) -> bool:
    """Reads only the ZIP's central directory (names), never decompresses anything."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return names >= _DOCX_REQUIRED and _DOCX_MACROS not in names


def _contains(path: Path, needle: bytes) -> bool:
    overlap = len(needle) - 1
    tail = b""
    with path.open("rb") as handle:
        while chunk := handle.read(_SCAN_CHUNK):
            if needle in tail + chunk:
                return True
            tail = chunk[-overlap:]
    return False


def clean_filename(raw: str) -> str:
    """The base name only (browsers may send ``C:\\fakepath\\x.pdf``), without control characters,
    at most 255 characters; ``document`` when nothing is left."""
    base = PureWindowsPath(PurePosixPath(raw).name).name
    cleaned = " ".join(_CONTROL.sub("", base).split())[:FILENAME_MAX]
    return cleaned or "document"


def name_from_filename(filename: str) -> str:
    """The default document name: the file name without its extension (§2.4)."""
    stem = filename.rsplit(".", 1)[0] if "." in filename.strip(".") else filename
    return " ".join(stem.split())[:NAME_MAX] or "Document"
