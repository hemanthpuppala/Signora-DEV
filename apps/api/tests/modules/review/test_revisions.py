"""Editing an approved version makes the next version (Phase 6 LLD §1.2, §6.2, §10.3)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from signora.modules.documents import lifecycle
from signora.modules.documents.lifecycle import derived_name
from signora.modules.review.editing import (
    Stored,
    StoredField,
    StoredParty,
    StoredPlace,
    rekey,
    settle,
)
from signora.modules.review.fieldset import FieldSet
from tests.modules.documents.conftest import csrf_headers, log_in
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.review.test_save import DOCUMENTS, _body, _drawn, _in_review, _save, _view
from tests.support.actors import actor_for


def _approve(db: Database, account: Account, document_id: str, version_id: str) -> None:
    with db.unit_of_work() as uow:
        assert lifecycle.approve_version(
            uow,
            actor=actor_for(db, account),
            document_id=uuid.UUID(document_id),
            version_id=uuid.UUID(version_id),
        )


def _revise(
    api: TestClient,
    document_id: str,
    version_id: str,
    body: dict[str, Any],
    key: dict[str, str] | None = None,
) -> Any:
    return api.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/revisions",
        json=body,
        headers={**csrf_headers(api), **(key if key is not None else idempotency_key())},
    )


def _version(api: TestClient, document_id: str, number: int) -> Any:
    document = api.get(f"{DOCUMENTS}/{document_id}").json()
    return next(v for v in document["versions"] if v["number"] == number)


def test_an_edit_of_an_approved_version_becomes_the_next_version(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
    company: Account,
) -> None:
    document_id, source_id = _in_review(owner, run, detect)
    _approve(committing_db, company, document_id, source_id)
    before = _view(owner, document_id, source_id)
    body = _body(before)
    body["fields"][0]["label"] = "Governing law: state"
    body["fields"].append(_drawn("Matter number", None))

    revised = _revise(owner, document_id, source_id, body)

    assert revised.status_code == 201, revised.text
    made = revised.json()
    assert (made["number"], made["revision"]) == (2, 1)
    new_id = made["version_id"]
    after = _view(owner, document_id, new_id)
    assert (after["status"], after["revision"]) == ("ready", 1)
    assert [f["label"] for f in after["fields"]] == [f["label"] for f in body["fields"]]
    assert after["flags"] == before["flags"]
    old_ids = {f["id"] for f in before["fields"]} | {r["id"] for r in before["roles"]}
    old_ids |= {p["id"] for f in before["fields"] for p in f["placements"]}
    new_ids = {f["id"] for f in after["fields"]} | {r["id"] for r in after["roles"]}
    new_ids |= {p["id"] for f in after["fields"] for p in f["placements"]}
    assert not old_ids & new_ids  # ids are the new version's own
    assert [f["party_id"] is None for f in after["fields"]] == [
        f["party_id"] is None for f in body["fields"]
    ]
    assert _view(owner, document_id, source_id) == before  # the approved version never changes

    source, version = _version(owner, document_id, 1), _version(owner, document_id, 2)
    named = source["name"] or owner.get(f"{DOCUMENTS}/{document_id}").json()["name"]
    assert version["name"] == f"{named} - 2"
    assert (version["description"], version["derived_from"]) == (source["description"], 1)
    assert version["field_count"] == len(body["fields"])
    assert (source["is_current"], version["is_current"]) == (True, False)
    with committing_db.unit_of_work() as uow:
        files = uow.session.execute(
            text(
                "SELECT pdf_sha256, source_sha256, pages FROM document_versions "
                "WHERE document_id = :d ORDER BY version_no"
            ),
            {"d": document_id},
        ).all()
        pdf_fields = [
            sorted(
                uow.session.execute(
                    text(
                        "SELECT pdf_field FROM field_placements "
                        "WHERE version_id = :v AND pdf_field IS NOT NULL"
                    ),
                    {"v": v},
                ).scalars()
            )
            for v in (source_id, new_id)
        ]
        actions: dict[str, Any] = dict(
            uow.session.execute(
                text(
                    "SELECT action, data FROM audit_events WHERE subject_id = :d "
                    "AND action IN ('document.version_derived', 'document.fields_saved')"
                ),
                {"d": document_id},
            ).all()
        )
    assert files[0] == files[1]  # the same stored file, no upload
    assert pdf_fields[0] and pdf_fields[0] == pdf_fields[1]  # boxes from the PDF keep their names
    assert actions["document.version_derived"]["derived_from"] == 1
    saved = actions["document.fields_saved"]
    assert (saved["version_no"], saved["derived_from"], saved["added"]) == (2, 1, 1)

    # The new version is in review: saved in place, and once approved it becomes current.
    in_place = _save(owner, document_id, new_id, _body(after))
    assert (in_place.status_code, in_place.json()) == (200, {"revision": 2})
    _approve(committing_db, company, document_id, new_id)
    assert _version(owner, document_id, 2)["is_current"]

    # Editing it again names the next one after the same source name, not "… - 2 - 3".
    again = _revise(owner, document_id, new_id, _body(_view(owner, document_id, new_id)))
    assert again.status_code == 201, again.text
    assert _version(owner, document_id, 3)["name"] == version["name"].removesuffix(" - 2") + " - 3"


def test_a_retried_request_makes_one_version(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
    company: Account,
) -> None:
    document_id, source_id = _in_review(owner, run, detect)
    _approve(committing_db, company, document_id, source_id)
    body = _body(_view(owner, document_id, source_id))
    key = idempotency_key()

    first = _revise(owner, document_id, source_id, body, key)
    retried = _revise(owner, document_id, source_id, body, key)

    assert (first.status_code, retried.status_code) == (201, 201)
    assert retried.json() == first.json()
    versions = owner.get(f"{DOCUMENTS}/{document_id}").json()["versions"]
    assert len(versions) == 2
    reused = _revise(owner, document_id, source_id, {**body, "fields": []}, key)
    assert (reused.status_code, reused.json()["code"]) == (422, "idempotency-key-reused")


def test_revisions_are_refused_unless_approved_current_and_editable(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
    company: Account,
    make_client: Callable[..., TestClient],
    add_member: Callable[..., Account],
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))

    in_review = _revise(owner, document_id, version_id, body)
    assert (in_review.status_code, in_review.json()["code"]) == (409, "version-not-approved")
    no_key = owner.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/revisions",
        json=body,
        headers=csrf_headers(owner),
    )
    assert (no_key.status_code, no_key.json()["code"]) == (400, "idempotency-key-missing")

    assert _save(owner, document_id, version_id, body).status_code == 200  # revision 1
    _approve(committing_db, company, document_id, version_id)
    stale = _revise(owner, document_id, version_id, body)  # started from revision 0
    assert (stale.status_code, stale.json()["code"]) == (409, "fields-changed")
    body["revision"] = 1
    body["fields"][0]["places"][0]["page"] = 99
    invalid = _revise(owner, document_id, version_id, body)
    assert invalid.status_code == 422
    body["fields"][0]["places"][0]["page"] = 1

    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert _revise(theirs, document_id, version_id, body).status_code == 403

    archived = owner.post(f"{DOCUMENTS}/{document_id}/archive", headers=csrf_headers(owner))
    assert archived.status_code == 200, archived.text
    refused = _revise(owner, document_id, version_id, body)
    assert (refused.status_code, refused.json()["code"]) == (409, "document-archived")
    assert len(owner.get(f"{DOCUMENTS}/{document_id}").json()["versions"]) == 1


def test_an_archived_documents_fields_cannot_be_saved(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    assert owner.post(f"{DOCUMENTS}/{document_id}/archive", headers=csrf_headers(owner)).is_success

    refused = _save(owner, document_id, version_id, body)

    assert (refused.status_code, refused.json()["code"]) == (409, "document-archived")


def test_rekey_moves_every_reference_with_its_id() -> None:
    party, field, choice, place, option = (uuid.uuid4() for _ in range(5))
    fieldset = FieldSet.model_validate(
        {
            "revision": 0,
            "parties": [{"id": str(party), "label": "Client", "kind": "signer"}],
            "fields": [
                {
                    "id": str(choice),
                    "label": "Plan",
                    "holds": "choice",
                    "filled_by": "role",
                    "party_id": str(party),
                    "required": True,
                    "places": [
                        {
                            "id": str(option),
                            "page": 1,
                            "rect": [10, 10, 20, 20],
                            "kind": "radio",
                            "option_value": "Gold",
                        }
                    ],
                },
                {
                    "id": str(field),
                    "label": "Card",
                    "holds": "text",
                    "filled_by": "role",
                    "party_id": str(party),
                    "required": True,
                    "depends_on": {"field_id": str(choice), "option": "Gold"},
                    "places": [
                        {"id": str(place), "page": 1, "rect": [30, 30, 90, 50], "kind": "text"}
                    ],
                },
            ],
        }
    )
    stored = Stored(
        parties={party: StoredParty(party, "Client", "signer", None, 1)},
        fields={
            field: StoredField(
                field,
                "Card",
                "text",
                None,
                None,  # no format: text has none
                "role",
                party,
                True,
                False,
                (choice, "Gold"),
                "x",
                "pdf",
            )
        },
        places={
            place: StoredPlace(place, field, 1, (30, 30, 90, 50), "text", "card", None, None),
            option: StoredPlace(option, choice, 1, (10, 10, 20, 20), "radio", "plan", "Gold", None),
        },
    )

    settled, moved, ids = rekey(settle(fieldset), stored)
    assert set(ids) >= {party, field, choice, place, option}

    ((new_party, slug),) = settled.parties
    plan, card = (item for item, _ in settled.fields)
    every = {new_party.id, plan.id, card.id, *(p.id for f in (plan, card) for p in f.places)}
    assert not every & {party, field, choice, place, option} and len(every) == 5
    assert (slug, plan.party_id, card.party_id) == ("client", new_party.id, new_party.id)
    assert card.depends_on is not None and card.depends_on.field_id == plan.id
    assert moved.fields[card.id].depends_on == (plan.id, "Gold")
    assert moved.fields[card.id].party_id == new_party.id
    assert moved.places_of(card.id) == {
        card.places[0].id: StoredPlace(
            card.places[0].id, card.id, 1, (30, 30, 90, 50), "text", "card", None, None
        )
    }


def test_a_derived_name_replaces_the_number_editing_added() -> None:
    assert derived_name("Financial NDA", 1, False, 6) == "Financial NDA - 6"
    assert derived_name("Financial NDA - 6", 6, True, 7) == "Financial NDA - 7"
    assert derived_name("Plan - 2", 2, False, 3) == "Plan - 2 - 3"  # the AI's own name, kept
