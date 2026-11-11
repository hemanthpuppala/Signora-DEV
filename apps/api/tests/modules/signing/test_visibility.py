"""Who sees which value (Phase 8 LLD §4.2, §7.1.5): the rule itself, for parties the test
agreement does not have (a second signer)."""

from __future__ import annotations

import uuid
from dataclasses import replace

from signora.modules.envelopes import FormField, GivenValue, SignerRecipient
from signora.modules.signing.document import _seen

CLIENT, PARTNER, FIRM = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
VIEWER = SignerRecipient(
    id=uuid.uuid4(),
    workspace_id=uuid.uuid4(),
    envelope_id=uuid.uuid4(),
    version_id=uuid.uuid4(),
    party_id=CLIENT,
    kind="signer",
    status="opened",
    name="Maya Chen",
    email="maya@example.com",
    user_id=None,
    link_version=1,
    revoked=False,
    signed_at=None,
    envelope_status="opened",
    expired=False,
    require_email_code=True,
    title="NDA",
    time_zone="UTC",
    font="liberation-sans",
    company="Hale & Ward LLP",
    sender_name="Rosa Hale",
    sender_email="rosa@example.com",
)


def _field(holds: str, party: uuid.UUID | None, *, sensitive: bool = False) -> FormField:
    return FormField(
        id=uuid.uuid4(),
        label=holds,
        holds=holds,  # type: ignore[arg-type]
        holds_label=None,
        format=None,
        party_id=party,
        required=False,
        sensitive=sensitive,
        options=[],
        depends_on=None,
        places=[],
        from_recipient=None,
    )


def _given(field: FormField, value: str, kind: str | None) -> GivenValue:
    return GivenValue(field.id, value, "recipient" if kind else "sender", None, kind)


def test_a_signer_sees_another_signers_values_but_not_their_private_ones() -> None:
    title, tax = _field("text", PARTNER), _field("tax_id", PARTNER)
    other = _field("other", PARTNER, sensitive=True)
    firms = frozenset({FIRM})

    assert _seen(title, _given(title, "Partner", "signer"), VIEWER, firms) == ("Partner", None)
    assert _seen(tax, _given(tax, "12-3456789", "signer"), VIEWER, firms) == (None, "private")
    assert _seen(other, _given(other, "secret", "signer"), VIEWER, firms) == (None, "private")


def test_a_signer_never_sees_a_countersigners_value_and_a_countersigner_sees_all() -> None:
    firm, tax = _field("signature", FIRM), _field("tax_id", PARTNER)
    firms = frozenset({FIRM})

    assert _seen(firm, _given(firm, "signed", "countersigner"), VIEWER, firms) == (
        None,
        "countersigner",
    )
    countersigner = replace(VIEWER, kind="countersigner", party_id=FIRM)
    assert _seen(tax, _given(tax, "12-3456789", "signer"), countersigner, firms) == (
        "12-3456789",
        None,
    )


def test_a_senders_private_value_is_kept_from_signers() -> None:
    account = _field("bank_account", None)

    assert _seen(account, _given(account, "000123", None), VIEWER, frozenset()) == (
        None,
        "private",
    )
