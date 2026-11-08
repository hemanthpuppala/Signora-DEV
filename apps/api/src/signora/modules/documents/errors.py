"""Errors of the documents module (Phase 4 LLD). Titles are what people read (§2.5)."""

from __future__ import annotations

from signora.kernel.errors import Conflict, DomainError


class UnsupportedFile(DomainError):
    code = "unsupported-file"
    status = 415
    title = "Upload a PDF or Word (.docx) file"


class ProtectedWordFile(DomainError):
    code = "protected-word-file"
    status = 422
    title = "Remove the password in Word and upload it again"


class DocumentNameTaken(Conflict):
    code = "document-name-taken"
    title = "Another document in this department already has this name"


class DocumentArchived(Conflict):
    code = "document-archived"
    title = "This document is archived. Restore it to make changes"


class DuplicateFile(Conflict):
    code = "duplicate-file"
    title = "This file is already in this department"


class UploadNotFound(DomainError):
    code = "upload-not-found"
    status = 404
    title = "This upload has expired. Upload the file again"


class UploadUsed(Conflict):
    code = "upload-used"
    title = "This upload has already been used"


class CannotRetry(Conflict):
    code = "cannot-retry"
    title = "Only a version that failed for a passing reason can be tried again"


class NotLocked(Conflict):
    code = "version-not-locked"
    title = "This version doesn't need a password"


class WrongPassword(DomainError):
    code = "wrong-password"
    status = 422
    title = "Wrong password"
