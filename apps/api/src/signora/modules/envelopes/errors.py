"""Envelopes' refusals (Phase 7 LLD §10). Titles are what people read."""

from __future__ import annotations

from signora.kernel.errors import Conflict, DomainError


class SamePerson(Conflict):
    code = "same-person"
    title = "The same email is on two parties. Send anyway if one person signs as both"


class NobodySigns(Conflict):
    code = "nobody-signs"
    title = "Nobody signs this template. Add who signs and where, then send"


class UnreadableFile(DomainError):
    code = "bulk-file-unreadable"
    status = 422
    title = "This file could not be read. Use the spreadsheet downloaded here, as XLSX or CSV"


class TooManyRows(DomainError):
    code = "bulk-file-too-many-rows"
    status = 422
    title = "This file has too many rows. Send it in parts"


class EmptyFile(DomainError):
    code = "bulk-file-empty"
    status = 422
    title = "This file has no rows under its headers"


class RowsNeedFixing(DomainError):
    """A batch whose rows still have problems: nothing of it is sent (Bulk send LLD §4.4)."""

    code = "bulk-rows-need-fixing"
    status = 422
    title = "Some rows still have problems. Fix them or leave them out, then send"


class EnvelopeClosed(Conflict):
    code = "envelope-closed"
    title = "This envelope is closed: it was completed, declined, cancelled or it expired"


class RecipientSigned(Conflict):
    code = "recipient-signed"
    title = "This person has already signed"


class NotTheirTurn(Conflict):
    code = "not-their-turn"
    title = "Countersigners are emailed once every signer has signed"
