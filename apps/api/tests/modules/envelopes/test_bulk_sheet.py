"""A bulk send's sheet (Bulk send LLD §4): columns from a form, a row judged as a single send
would judge it, rows against each other. Pure."""

from __future__ import annotations

import uuid

import pytest

from signora.kernel.errors import ValidationFailed
from signora.modules.envelopes.bulk_sheet import (
    SAME_PERSON,
    BatchDefaults,
    RowIn,
    check_row,
    check_rows,
    columns_of,
    countersigner_key,
    field_key,
    header_text,
    known_columns,
    match_headers,
    setting_key,
    signer_key,
)
from signora.modules.envelopes.errors import NobodySigns
from signora.modules.envelopes.form import (
    Colleague,
    Condition,
    FormCountersigner,
    FormField,
    FormSettings,
    FormSigner,
    Option,
    SendForm,
)
from signora.modules.envelopes.sending import SettingsIn, plan_send
from signora.modules.identity_access import normalize_email
from signora.modules.typesetting import DEFAULT_FONT, FIT_RULE, font_view

CLIENT, WITNESS, PARTNER = (uuid.uuid4() for _ in range(3))
MATTER, START, PLAN, CARD, URGENT, CLIENT_EMAIL, CLIENT_PHONE = (uuid.uuid4() for _ in range(7))
ANA = Colleague(user_id=uuid.uuid4(), name="Ana Ruiz", email="ana@firm.example")
BEN = Colleague(user_id=uuid.uuid4(), name="Ben Okoro", email="ben@firm.example")


def field(
    id_: uuid.UUID, label: str, holds: str, party: uuid.UUID | None = None, **extra: object
) -> FormField:
    return FormField.model_validate(
        {
            "id": id_,
            "label": label,
            "holds": holds,
            "holds_label": None,
            "party_id": party,
            "required": False,
            "sensitive": False,
            "options": [],
            "depends_on": None,
            "places": [],
            "from_recipient": "email" if party and holds == "email" else None,
            "format": None,
            **extra,
        }
    )


def form(*, countersigner: bool = True, witness: bool = False) -> SendForm:
    signers = [FormSigner(party_id=CLIENT, label="Client", kind_label=None, position=1)]
    if witness:
        signers.append(FormSigner(party_id=WITNESS, label="Witness", kind_label=None, position=2))
    return SendForm(
        document_id=uuid.uuid4(),
        document_name="Engagement Letter",
        version_id=uuid.uuid4(),
        version_number=2,
        pages=[],
        signers=signers,
        countersigners=[
            FormCountersigner(party_id=PARTNER, label="Partner", position=3, default=ANA)
        ]
        if countersigner
        else [],
        colleagues=[ANA, BEN],
        fields=[
            field(MATTER, "Matter", "text", required=True),
            field(START, "Start date", "date"),
            field(
                PLAN,
                "Plan",
                "choice",
                options=[Option(value="gold", text="Gold"), Option(value="silver", text="Silver")],
            ),
            field(
                CARD,
                "Card number",
                "text",
                required=True,
                depends_on=Condition(field_id=PLAN, option="gold"),
            ),
            field(URGENT, "Urgent", "checkbox"),
            field(CLIENT_EMAIL, "Email", "email", CLIENT),  # the signer's own: never a column
            field(CLIENT_PHONE, "Phone", "phone", CLIENT),  # the signer's to fill; may be prefilled
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


def defaults(sheet_form: SendForm, **settings: object) -> BatchDefaults:
    return BatchDefaults(
        settings=SettingsIn(
            **{"reminder_interval_hours": 24, "max_reminders": 5, "expiry_days": 14, **settings}  # type: ignore[arg-type]
        ),
    )


NAME, EMAIL = signer_key(CLIENT, "name"), signer_key(CLIENT, "email")


def cells(**given: str) -> dict[str, str]:
    """A valid row, with what a test changes."""
    return {
        NAME: "Avery Lin",
        EMAIL: "avery@example.com",
        countersigner_key(PARTNER): ANA.email,  # ignored by a form nobody countersigns
        field_key(MATTER): "Lease review",
        **given,
    }


def judge(sheet_form: SendForm, row: dict[str, str]) -> dict[str, str]:
    result = check_row(sheet_form, row, defaults(sheet_form), normalize_email=normalize_email)
    return {problem.key: problem.message for problem in result.problems}


# --- columns --------------------------------------------------------------------------------------


def test_columns_are_what_the_form_asks_per_envelope() -> None:
    columns = columns_of(form())
    assert [(c.header, c.kind, c.required) for c in columns] == [
        ("Client name", "text", True),
        ("Client email", "email", True),
        ("Partner countersigner", "choice", True),
        ("Matter", "text", True),
        ("Start date", "date", False),
        ("Plan", "choice", False),
        ("Card number", "text", True),
        ("Urgent", "checkbox", False),
        ("Phone", "text", False),
    ]
    # A field that comes from the signer's own email is never asked.
    assert field_key(CLIENT_EMAIL) not in {c.key for c in columns}
    assert [o.value for o in columns[2].options] == [ANA.email, BEN.email]
    assert header_text(columns[0]) == "Client name *"


def test_repeated_labels_get_unique_headers() -> None:
    sheet_form = form(witness=True)
    sheet_form.fields.extend(
        [
            field(uuid.uuid4(), "Address", "address", CLIENT),
            field(uuid.uuid4(), "Address", "address", WITNESS),
            field(uuid.uuid4(), "Notes", "text"),
            field(uuid.uuid4(), "Notes", "text"),
        ]
    )
    headers = [c.header for c in columns_of(sheet_form)]
    assert "Client: Address" in headers and "Witness: Address" in headers
    assert "Notes" in headers and "Notes (2)" in headers
    assert len(headers) == len(set(headers))


def test_headers_match_ignoring_case_spaces_and_the_star() -> None:
    known = known_columns(form())
    matched = match_headers(
        ["client NAME *", " Client  email", "", "Matter*", "Expires after (days)"], known
    )
    assert matched.problems == []
    assert matched.keys == [NAME, EMAIL, None, field_key(MATTER), setting_key("expiry_days")]
    # The sheet's columns come back in the form's order, the optional setting last.
    assert [c.key for c in matched.columns][-1] == setting_key("expiry_days")


def test_a_file_with_the_wrong_columns_says_which() -> None:
    matched = match_headers(["Client name", "Client name", "Shoe size"], known_columns(form()))
    assert matched.problems == [
        'The column "Client name" is in this file twice',
        'This file has a column "Shoe size" that this template does not ask for',
    ]
    # What the file lacks but a row must give is still a column, to be filled where it is shown.
    assert [c.header for c in matched.columns] == [
        "Client name",
        "Client email",
        "Partner countersigner",
        "Matter",
        "Card number",
    ]


def test_a_problem_about_a_column_the_file_lacks_brings_the_column_in() -> None:
    sheet_form = form(countersigner=False)
    sheet_form.fields[3].required = False  # Card number: no longer asked for
    reference = field(
        uuid.uuid4(),
        "Reference",
        "text",
        required=True,
        depends_on=Condition(field_id=PLAN, option="gold"),
    )
    sheet_form.fields.append(reference)
    matched = match_headers(
        ["Client name", "Client email", "Matter", "Plan"], known_columns(sheet_form)
    )
    assert matched.problems == []
    checked = check_rows(
        sheet_form,
        [c for c in matched.columns if c.header != "Reference"],
        [RowIn(row_no=2, cells=cells(**{field_key(PLAN): "Gold"}))],
        defaults(sheet_form),
        normalize_email=normalize_email,
    )
    assert [c.header for c in checked.sheet.columns][-1] == "Reference"
    assert [p.message for p in checked.sheet.rows[0].problems] == ["Fill this in before sending"]


# --- a row ----------------------------------------------------------------------------------------


def test_a_valid_row_is_the_request_a_single_send_accepts() -> None:
    sheet_form = form()
    row = cells(**{field_key(START): "2026-12-01", field_key(URGENT): "Yes"})
    result = check_row(sheet_form, row, defaults(sheet_form), normalize_email=normalize_email)
    assert result.problems == [] and result.request is not None
    # The same request, given to the single send's check, is accepted (NFR-1).
    plan = plan_send(
        sheet_form,
        result.request,
        colleagues={c.user_id: c for c in sheet_form.colleagues},
        normalize_email=normalize_email,
    )
    assert plan.signers[0].email == "avery@example.com"
    assert plan.countersigners[0].user_id == ANA.user_id
    assert plan.values[START] == "2026-12-01" and plan.values[URGENT] == "true"


@pytest.mark.parametrize(
    ("change", "key", "message"),
    [
        ({NAME: ""}, NAME, "Enter a name"),
        ({EMAIL: ""}, EMAIL, "Enter an email address"),
        ({EMAIL: "avery@"}, EMAIL, "Enter a valid email address"),
        ({NAME: "x" * 121}, NAME, "Use 120 or fewer characters"),
        ({field_key(MATTER): ""}, field_key(MATTER), "Fill this in before sending"),
        ({field_key(START): "next week"}, field_key(START), "Enter a date"),
        ({field_key(PLAN): "Platinum"}, field_key(PLAN), "Choose one of the options"),
        ({field_key(URGENT): "maybe"}, field_key(URGENT), "Tick it or leave it"),
        ({field_key(PLAN): "Gold"}, field_key(CARD), "Fill this in before sending"),
        (
            {countersigner_key(PARTNER): "zed@else.example"},
            countersigner_key(PARTNER),
            "Not a colleague's email",
        ),
    ],
)
def test_a_problem_is_on_its_cell_in_the_single_sends_words(
    change: dict[str, str], key: str, message: str
) -> None:
    assert judge(form(), cells(**change)) == {key: message}


def test_bulk_and_a_single_send_refuse_the_same_data() -> None:
    """NFR-1: what bulk reports for a row is what ``plan_send`` raises for its request."""
    sheet_form = form()
    row = cells(**{field_key(MATTER): "", field_key(START): "soon", EMAIL: "not-an-email"})
    bulk = judge(sheet_form, row)

    from signora.modules.envelopes.sending import SendRequest

    request = SendRequest.model_validate(
        {
            "version_id": sheet_form.version_id,
            "signers": [{"party_id": CLIENT, "name": "Avery Lin", "email": "not-an-email"}],
            "countersigners": [{"party_id": PARTNER, "user_id": ANA.user_id}],
            "values": [{"field_id": START, "value": "soon"}],
            "settings": {"reminder_interval_hours": 24, "max_reminders": 5, "expiry_days": 14},
        }
    )
    with pytest.raises(ValidationFailed) as refused:
        plan_send(
            sheet_form,
            request,
            colleagues={c.user_id: c for c in sheet_form.colleagues},
            normalize_email=normalize_email,
        )
    assert sorted(bulk.values()) == sorted(e.message for e in refused.value.field_errors)


def test_a_choice_is_given_by_its_words_or_its_value_and_a_tick_many_ways() -> None:
    sheet_form = form()
    for text in ("Silver", "silver", " SILVER "):
        result = check_row(
            sheet_form,
            cells(**{field_key(PLAN): text}),
            defaults(sheet_form),
            normalize_email=normalize_email,
        )
        assert result.plan is not None and result.plan.values[PLAN] == "silver"
    for text, kept in (("x", True), ("TRUE", True), ("1", True), ("no", False), ("0", False)):
        result = check_row(
            sheet_form,
            cells(**{field_key(URGENT): text}),
            defaults(sheet_form),
            normalize_email=normalize_email,
        )
        assert result.plan is not None and (URGENT in result.plan.values) is kept


def test_a_rows_own_countersigner_and_settings_replace_the_batchs() -> None:
    sheet_form = form()
    row = cells(
        **{
            countersigner_key(PARTNER): "BEN@firm.example",
            setting_key("expiry_days"): "30",
            setting_key("require_email_code"): "no",
        }
    )
    result = check_row(sheet_form, row, defaults(sheet_form), normalize_email=normalize_email)
    assert result.request is not None and result.plan is not None
    assert result.plan.countersigners[0].user_id == BEN.user_id
    assert result.request.settings.expiry_days == 30
    assert result.request.settings.require_email_code is False
    assert result.request.settings.max_reminders == 5  # untouched: the batch's


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("expiry_days", "400", "Enter a whole number from 1 to 365"),
        ("expiry_days", "soon", "Enter a whole number from 1 to 365"),
        ("max_reminders", "-1", "Enter a whole number from 0 to 20"),
        ("reminder_interval_hours", "0", "Enter a whole number from 1 to 720"),
        ("require_email_code", "perhaps", "Give yes or no"),
    ],
)
def test_a_rows_setting_out_of_range_is_named(name: str, text: str, message: str) -> None:
    assert judge(form(), cells(**{setting_key(name): text})) == {setting_key(name): message}


def test_a_row_that_names_no_countersigner_is_asked_for_one_on_that_cell() -> None:
    """Who countersigns is the row's to say: an empty cell is a problem to fix in the table, not
    something chosen on a later step."""
    assert judge(form(), cells(**{countersigner_key(PARTNER): ""})) == {
        countersigner_key(PARTNER): "Choose who countersigns as Partner"
    }


def test_a_judged_rows_cells_are_given_back_as_they_were_read() -> None:
    """Whoever shows a row shows these cells: a choice as its option's value, a tick as yes, a
    colleague as their email, however the file wrote them."""
    sheet_form = form()
    row = cells(
        **{
            field_key(PLAN): " SILVER ",
            field_key(URGENT): "X",
            countersigner_key(PARTNER): "Ben Okoro · ben@firm.example",
        }
    )
    result = check_row(sheet_form, row, defaults(sheet_form), normalize_email=normalize_email)
    assert result.problems == []
    assert result.cells[field_key(PLAN)] == "silver"
    assert result.cells[field_key(URGENT)] == "yes"
    assert result.cells[countersigner_key(PARTNER)] == BEN.email
    # What cannot be read is given back as typed, with its problem.
    unread = check_row(
        sheet_form,
        cells(**{field_key(PLAN): "Platinum", field_key(URGENT): "maybe"}),
        defaults(sheet_form),
        normalize_email=normalize_email,
    )
    assert unread.cells[field_key(PLAN)] == "Platinum"
    assert unread.cells[field_key(URGENT)] == "maybe"


def test_one_person_on_two_parties_of_a_row_is_refused_on_both_cells() -> None:
    sheet_form = form(witness=True, countersigner=False)
    row = cells(
        **{
            signer_key(WITNESS, "name"): "Avery L.",
            signer_key(WITNESS, "email"): "AVERY@example.com",
        }
    )
    assert judge(sheet_form, row) == {
        EMAIL: SAME_PERSON,
        signer_key(WITNESS, "email"): SAME_PERSON,
    }


def test_a_problem_with_the_batch_itself_is_said_once_not_on_every_row() -> None:
    sheet_form = form()
    batch = defaults(sheet_form)
    batch.settings.notify_emails = ["not-an-email"]
    checked = check_rows(
        sheet_form,
        columns_of(sheet_form),
        [RowIn(row_no=2, cells=cells()), RowIn(row_no=3, cells=cells(**{EMAIL: "b@example.com"}))],
        batch,
        normalize_email=normalize_email,
    )
    assert checked.sheet.problems == ["Enter a valid email address"]
    assert all(row.problems == [] for row in checked.sheet.rows)
    assert checked.blocked and checked.sendable == []


# --- the sheet ------------------------------------------------------------------------------------


def test_rows_sending_to_the_same_signer_are_flagged_but_not_stopped() -> None:
    sheet_form = form()
    rows = [
        RowIn(row_no=2, cells=cells()),
        RowIn(row_no=3, cells=cells(**{EMAIL: "other@example.com"})),
        RowIn(row_no=7, cells=cells(**{EMAIL: " Avery@Example.com "})),
    ]
    checked = check_rows(
        sheet_form,
        columns_of(sheet_form),
        rows,
        defaults(sheet_form),
        normalize_email=normalize_email,
    )
    said = {
        row.row_no: [(p.key, p.message, p.level) for p in row.problems]
        for row in checked.sheet.rows
    }
    assert said == {
        2: [(EMAIL, "Also in row 7", "warning")],
        3: [],
        7: [(EMAIL, "Also in row 2", "warning")],
    }
    assert not checked.blocked
    assert [number for number, _, _ in checked.sendable] == [2, 3, 7]
    assert checked.sendable[0][1] == "Avery Lin · avery@example.com"


def test_only_rows_without_errors_are_sendable() -> None:
    sheet_form = form()
    rows = [RowIn(row_no=2, cells=cells()), RowIn(row_no=3, cells=cells(**{EMAIL: ""}))]
    checked = check_rows(
        sheet_form,
        columns_of(sheet_form),
        rows,
        defaults(sheet_form),
        normalize_email=normalize_email,
    )
    assert checked.blocked
    assert [number for number, _, _ in checked.sendable] == [2]


def test_a_template_nobody_signs_cannot_be_sent_in_bulk() -> None:
    sheet_form = form(countersigner=False)
    sheet_form.signers.clear()
    with pytest.raises(NobodySigns):
        check_rows(sheet_form, [], [], defaults(sheet_form), normalize_email=normalize_email)


def test_checking_a_thousand_rows_is_fast() -> None:
    """NFR-2: 1,000 rows well inside the two-second budget."""
    import time

    sheet_form = form()
    rows = [
        RowIn(row_no=n + 2, cells=cells(**{EMAIL: f"client{n}@example.com"})) for n in range(1000)
    ]
    started = time.perf_counter()
    checked = check_rows(
        sheet_form,
        columns_of(sheet_form),
        rows,
        defaults(sheet_form),
        normalize_email=normalize_email,
    )
    assert len(checked.sendable) == 1000
    assert time.perf_counter() - started < 2.0
