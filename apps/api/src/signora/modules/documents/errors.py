"""Errors of the documents module (Phase 4 LLD). Titles are what people read (§2.5)."""

from __future__ import annotations

from signora.kernel.errors import DomainError


class UnsupportedFile(DomainError):
    code = "unsupported-file"
    status = 415
    title = "Upload a PDF or Word (.docx) file"


class ProtectedWordFile(DomainError):
    code = "protected-word-file"
    status = 422
    title = "Remove the password in Word and upload it again"
