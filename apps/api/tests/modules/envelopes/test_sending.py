"""A send checked against its form (Phase 7 LLD §2, §10.1; 7b): conditions and prefill, pure."""

from __future__ import annotations

import uuid

import pytest

from signora.kernel.errors import ValidationFailed
from signora.modules.envelopes.form import (
    Condition,
    FormField,
    FormSettings,
    FormSigner,
    Option,
    SendForm,
)
from signora.modules.envelopes.sending import SendRequest, plan_send, split_name
from signora.modules.identity_access import normalize_email

CLIENT = uuid.uuid4()
PLAN, CARD, FULL, FIRST, LAST, LEGAL, EMAIL = (uuid.uuid4() for _ in range(7))


FROM = {"full_name": "name", "first_name": "name", "last_name": "name", "email": "email"}


def field(id_: uuid.UUID, holds: str, party: uuid.UUID | None = None, **extra: object) -> FormField:
    return FormField.model_validate(
        {
            "id": id_,
            "label": holds,
            "holds": holds,
            "holds_label": None,
            "party_id": party,
            "required": False,
            "sensitive": False,
            "options": [],
            "depends_on": None,
            "places": [],
            "from_recipient": FROM.get(holds) if party else None,
            **extra,
        }
    )


FORM = SendForm(
    document_id=uuid.uuid4(),
    document_name="Mutual NDA",
    version_id=uuid.uuid4(),
    version_number=1,
    pages=[],
    signers=[
        FormSigner(
            party_id=CLIENT,
            label="Client",
            kind_label=None,
            position=1,
        )
    ],
    countersigners=[],
    fields=[
        field(
            PLAN,
            "choice",
            options=[Option(value="Gold", text="Gold"), Option(value="Silver", text="Silver")],
        ),
        field(CARD, "text", required=True, depends_on=Condition(field_id=PLAN, option="Gold")),
        field(FULL, "full_name", CLIENT),
        field(FIRST, "first_name", CLIENT),
        field(LAST, "last_name", CLIENT),
        field(LEGAL, "party_name", CLIENT),
        field(EMAIL, "email", CLIENT),
    ],
    settings=FormSettings(
        require_email_code=True,
        reminder_interval_hours=24,
        max_reminders=5,
        expiry_days=14,
        notify_emails=[],
    ),
)


def plan(values: dict[uuid.UUID, str]) -> dict[uuid.UUID, str]:
    request = SendRequest.model_validate(
        {
            "version_id": FORM.version_id,
            "signers": [{"party_id": CLIENT, "name": "Maya van Dijk", "email": "Maya@Example.com"}],
            "values": [{"field_id": k, "value": v} for k, v in values.items()],
            "settings": {"reminder_interval_hours": 24, "max_reminders": 5, "expiry_days": 14},
        }
    )
    planned = plan_send(FORM, request, colleagues={}, normalize_email=normalize_email)
    assert not planned.values.keys() & planned.prefill.get(CLIENT, {}).keys()  # never both
    return {**planned.values, **planned.prefill.get(CLIENT, {})}


def test_a_field_under_a_condition_is_asked_only_when_it_is_met() -> None:
    with pytest.raises(ValidationFailed) as refused:
        plan({PLAN: "Gold"})
    assert [e.field for e in refused.value.field_errors] == [f"fields.{CARD}"]

    assert CARD not in plan({PLAN: "Silver", CARD: "4111"})  # not asked: never sent
    assert plan({PLAN: "Gold", CARD: "4111"})[CARD] == "4111"


def test_the_signers_email_fills_their_email_fields_and_their_name_waits_for_signing() -> None:
    values = plan({PLAN: "Silver", LEGAL: "Van Dijk Holdings"})

    assert values[EMAIL] == "maya@example.com"  # DocuSign's Email field: the recipient's email
    assert not values.keys() & {FULL, FIRST, LAST}  # the name they sign as, at signing
    assert values[LEGAL] == "Van Dijk Holdings"  # a legal name may be a company's: the sender's


def test_the_sender_cannot_fill_what_comes_from_the_signer() -> None:
    with pytest.raises(ValidationFailed) as refused:
        plan({PLAN: "Silver", FULL: "M. van Dijk", EMAIL: "other@example.com"})
    assert sorted(e.field for e in refused.value.field_errors) == sorted(
        [f"fields.{FULL}", f"fields.{EMAIL}"]
    )
    assert {e.message for e in refused.value.field_errors} == {"Filled in from the signer"}


def test_split_name() -> None:
    assert split_name("Maya Chen") == ("Maya", "Chen")
    assert split_name("Maya van Dijk") == ("Maya van", "Dijk")
    assert split_name("Cher") == ("Cher", "")
