"""A send checked against its form (Phase 7 LLD §2, §10.1; 7b): conditions and prefill, pure."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from signora.kernel.errors import ValidationFailed
from signora.modules.envelopes.form import (
    Condition,
    FormField,
    FormSettings,
    FormSigner,
    Option,
    Place,
    SendForm,
)
from signora.modules.envelopes.sending import SendRequest, plan_send, split_name
from signora.modules.identity_access import normalize_email
from signora.modules.typesetting import DEFAULT_FONT, FIT_RULE, font_view

CLIENT = uuid.uuid4()
PLAN, CARD, FULL, FIRST, LAST, LEGAL, EMAIL, YEAR = (uuid.uuid4() for _ in range(8))


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
            "format": None,
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
        # The "20__" of a year: a short box on a line of 11 pt text, two digits written.
        field(
            YEAR,
            "year",
            format="YY",
            places=[Place(page=1, rect=(300, 100, 312, 114), option_value=None, text_size=11.0)],
        ),
    ],
    font=font_view(DEFAULT_FONT),
    fit=FIT_RULE,
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


def test_an_empty_value_is_left_for_the_signer_whatever_the_field() -> None:
    # A client that sends every field, empty where nothing was typed: nothing to refuse.
    values = plan({PLAN: "Silver", FULL: "", EMAIL: "  "})
    assert FULL not in values
    assert values[EMAIL] == "maya@example.com"


def test_what_is_left_in_a_field_no_longer_asked_never_refuses_the_send() -> None:
    # Typed under Gold, then Silver chosen: the year under it is not asked, so a value that
    # would be refused there (a letter, or a year too wide for its box) is dropped, not judged.
    under_gold = FORM.model_copy(
        update={
            "fields": [
                f.model_copy(
                    update={
                        "format": "YYYY",
                        "depends_on": Condition(field_id=PLAN, option="Gold"),
                    }
                )
                if f.id == YEAR
                else f
                for f in FORM.fields
            ]
        }
    )

    def planned(values: dict[uuid.UUID, str]) -> dict[uuid.UUID, str]:
        request = SendRequest.model_validate(
            {
                "version_id": FORM.version_id,
                "signers": [{"party_id": CLIENT, "name": "Maya", "email": "maya@example.com"}],
                "values": [{"field_id": k, "value": v} for k, v in values.items()],
                "settings": {"reminder_interval_hours": 24, "max_reminders": 5, "expiry_days": 14},
            }
        )
        return plan_send(under_gold, request, colleagues={}, normalize_email=normalize_email).values

    assert YEAR not in planned({PLAN: "Silver", YEAR: "2026"})  # too wide for its box
    assert YEAR not in planned({PLAN: "Silver", YEAR: "soon"})  # not a year
    with pytest.raises(ValidationFailed):
        planned({PLAN: "Gold", CARD: "4111", YEAR: "2026"})  # asked: judged


def test_a_year_written_in_two_digits_is_of_the_printed_century() -> None:
    # After a printed "20", 1999 would read 2099.
    with pytest.raises(ValidationFailed) as refused:
        plan({PLAN: "Silver", YEAR: "1999"})
    century = datetime.now(UTC).year // 100
    assert [(e.field, e.message) for e in refused.value.field_errors] == [
        (f"fields.{YEAR}", f"Enter a year from {century}00 to {century}99")
    ]


def test_split_name() -> None:
    assert split_name("Maya Chen") == ("Maya", "Chen")
    assert split_name("Maya van Dijk") == ("Maya van", "Dijk")
    assert split_name("Cher") == ("Cher", "")


def test_a_value_is_measured_as_its_field_writes_it() -> None:
    # Kept as 2026, written "26" after the printed "20": it fits.
    assert plan({PLAN: "Silver", YEAR: "2026"})[YEAR] == "2026"
    assert plan({PLAN: "Silver", YEAR: "26"})[YEAR] == "2026"


def test_a_value_too_long_for_its_box_is_refused() -> None:
    four = FORM.model_copy(
        update={
            "fields": [
                f.model_copy(update={"format": "YYYY"}) if f.id == YEAR else f for f in FORM.fields
            ]
        }
    )
    request = SendRequest.model_validate(
        {
            "version_id": FORM.version_id,
            "signers": [{"party_id": CLIENT, "name": "Maya", "email": "maya@example.com"}],
            "values": [{"field_id": YEAR, "value": "2026"}, {"field_id": PLAN, "value": "Silver"}],
            "settings": {"reminder_interval_hours": 24, "max_reminders": 5, "expiry_days": 14},
        }
    )
    with pytest.raises(ValidationFailed) as refused:  # four digits: smaller than readable there
        plan_send(four, request, colleagues={}, normalize_email=normalize_email)
    assert [(e.field, e.message) for e in refused.value.field_errors] == [
        (f"fields.{YEAR}", "Too long for its box")
    ]
