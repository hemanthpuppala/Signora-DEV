"""Envelopes' refusals (Phase 7 LLD §10). Titles are what people read."""

from __future__ import annotations

from signora.kernel.errors import Conflict


class SamePerson(Conflict):
    code = "same-person"
    title = "The same email is on two parties. Send anyway if one person signs as both"


class NobodySigns(Conflict):
    code = "nobody-signs"
    title = "Nobody signs this template. Add who signs and where, then send"


class EnvelopeClosed(Conflict):
    code = "envelope-closed"
    title = "This envelope is closed: it was completed, declined, cancelled or it expired"


class RecipientSigned(Conflict):
    code = "recipient-signed"
    title = "This person has already signed"


class NotTheirTurn(Conflict):
    code = "not-their-turn"
    title = "Countersigners are emailed once every signer has signed"
