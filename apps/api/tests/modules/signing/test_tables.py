"""What the database itself keeps true for signing (Phase 8 LLD §15): consent is a fact, a signature
signed with never changes, a decline is recorded with its reason, and a completed envelope's files
are set together, once."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.identity_access.conftest import Account
from tests.modules.signing.conftest import Sent, sent_envelope


@pytest.fixture
def sent(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None], company: Account
) -> Sent:
    return sent_envelope(owner, run, detect, company)


def _ids(db: Database, recipient_id: str) -> dict[str, object]:
    with db.unit_of_work() as uow:
        row = uow.session.execute(
            text("SELECT id, workspace_id FROM envelope_recipients WHERE id = :r"),
            {"r": recipient_id},
        ).one()
    return {"r": row.id, "w": row.workspace_id}


def _refused(db: Database, statement: str, params: Mapping[str, object], match: str) -> None:
    with pytest.raises(sqlalchemy.exc.DBAPIError, match=match), db.unit_of_work() as uow:
        uow.session.execute(text(statement), params)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE signing_consents SET disclosure_version = 'v2' WHERE recipient_id = :r",
        "DELETE FROM signing_consents WHERE recipient_id = :r",
    ],
)
def test_a_consent_once_given_never_changes(
    sent: Sent, committing_db: Database, statement: str
) -> None:
    ids = _ids(committing_db, sent.recipient("signer")["id"])
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "INSERT INTO signing_consents (recipient_id, workspace_id, disclosure_version, ip,"
                " user_agent) VALUES (:r, :w, 'esign-disclosure-v1', '203.0.113.7', 'Firefox')"
            ),
            ids,
        )
    _refused(committing_db, statement, ids, "a consent cannot change")


def test_a_signature_changes_until_its_signer_has_signed_then_never(
    sent: Sent, committing_db: Database
) -> None:
    ids = _ids(committing_db, sent.recipient("signer")["id"])
    adopt = (
        "INSERT INTO signing_signatures (recipient_id, workspace_id, kind, method, text, font,"
        " sha256) VALUES (:r, :w, 'signature', 'typed', 'Maya Chen', 'f', :h)"
    )
    change = "UPDATE signing_signatures SET text = 'M. Chen' WHERE recipient_id = :r"
    with committing_db.unit_of_work() as uow:
        uow.session.execute(text(adopt), {**ids, "h": bytes(32)})
        uow.session.execute(text(change), ids)  # before signing: Change replaces it
        uow.session.execute(
            text(
                "UPDATE envelope_recipients SET status = 'signed', signed_at = now() WHERE id = :r"
            ),
            ids,
        )
    _refused(committing_db, change, ids, "signed with cannot change")
    _refused(
        committing_db,
        "DELETE FROM signing_signatures WHERE recipient_id = :r",
        ids,
        "signed with cannot change",
    )


@pytest.mark.parametrize(
    ("method", "words", "font", "strokes"),
    [
        ("typed", "Maya Chen", None, None),  # typed needs its font
        ("drawn", "Maya", "f", None),  # drawn is strokes, not text
        ("typed", "", "f", None),  # empty text
        ("typed", "Maya", "f", "[[[1, 2]]]"),  # typed carries no strokes
    ],
)
def test_a_signature_is_either_text_in_a_font_or_strokes(
    sent: Sent,
    committing_db: Database,
    method: str,
    words: str | None,
    font: str | None,
    strokes: str | None,
) -> None:
    ids = _ids(committing_db, sent.recipient("signer")["id"])
    _refused(
        committing_db,
        "INSERT INTO signing_signatures (recipient_id, workspace_id, kind, method, text, font,"
        " strokes, sha256) VALUES (:r, :w, 'initials', :m, :t, :f, CAST(:s AS jsonb), :h)",
        {**ids, "m": method, "t": words, "f": font, "s": strokes, "h": bytes(32)},
        "ck_signing_signatures_",
    )


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "UPDATE envelope_recipients SET status = 'declined' WHERE id = :r",
            "declined_is_recorded",
        ),
        (
            "UPDATE envelope_recipients SET status = 'declined', declined_at = now(),"
            " decline_reason = '   ' WHERE id = :r",
            "decline_reason",
        ),
        (
            "UPDATE envelope_recipients SET declined_at = now(), decline_reason = 'Fee'"
            " WHERE id = :r",
            "declined_is_recorded",
        ),
    ],
)
def test_a_decline_is_recorded_with_when_and_why(
    sent: Sent, committing_db: Database, statement: str, constraint: str
) -> None:
    ids = _ids(committing_db, sent.recipient("signer")["id"])
    _refused(committing_db, statement, ids, constraint)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "UPDATE envelope_recipients SET status = 'declined', declined_at = now(),"
                " decline_reason = 'I would like to discuss the fee' WHERE id = :r"
            ),
            ids,
        )


def test_a_completed_envelope_has_both_files_set_once(sent: Sent, committing_db: Database) -> None:
    e = {"e": sent.id, "h": bytes(32)}
    _refused(
        committing_db,
        "UPDATE envelopes SET status = 'completed', completed_at = now() WHERE id = :e",
        e,
        "completed_has_files",
    )
    complete = (
        "UPDATE envelopes SET status = 'completed', completed_at = now(), signed_blob = 'a',"
        " signed_sha256 = :h, certificate_blob = 'b', certificate_sha256 = :h WHERE id = :e"
    )
    with committing_db.unit_of_work() as uow:
        uow.session.execute(text(complete), e)
    _refused(
        committing_db,
        "UPDATE envelopes SET signed_blob = 'c' WHERE id = :e",
        e,
        "files cannot change",
    )


def test_an_email_attachment_names_a_file_kept_elsewhere(committing_db: Database) -> None:
    email = uuid.uuid4()
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "INSERT INTO email_messages (id, category, to_address, subject) VALUES"
                " (:e, 'test', 'a@example.com', 's')"
            ),
            {"e": email},
        )
        uow.session.execute(
            text(
                "INSERT INTO email_attachments (email_id, position, blob_key, filename,"
                " content_type) VALUES (:e, 1, 'envelopes/x/signed.pdf', 'NDA.pdf',"
                " 'application/pdf')"
            ),
            {"e": email},
        )
    _refused(
        committing_db,
        "INSERT INTO email_attachments (email_id, position, blob_key, filename, content_type)"
        " VALUES (:e, 0, 'k', 'f.pdf', 'application/pdf')",
        {"e": email},
        "position_positive",
    )
