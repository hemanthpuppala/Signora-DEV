"""Saving a version's fields (Phase 6 LLD §6.2, §10.2, §10.5, §1.4, §1.6, NFR-R1)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.documents.conftest import create_department, csrf_headers, log_in, new_document
from tests.modules.identity_access.conftest import Account
from tests.support import forms
from tests.support.ai import FakeAssigner

DOCUMENTS = "/api/v1/documents"


def _in_review(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> tuple[str, str]:
    department = create_department(owner)
    document = new_document(owner, department["id"], forms.nda_like()).json()
    version_id = document["versions"][0]["id"]
    run(version_id)
    detect(version_id, FakeAssigner())
    return document["id"], version_id


def _view(api: TestClient, document_id: str, version_id: str) -> Any:
    response = api.get(f"{DOCUMENTS}/{document_id}/versions/{version_id}/fields")
    assert response.status_code == 200, response.text
    return response.json()


def _body(view: Any) -> dict[str, Any]:
    """The set as the editor holds it, built from the fields view (as the web editor does)."""
    id_of = {f["key"]: f["id"] for f in view["fields"]}
    return {
        "revision": view["revision"],
        "parties": [
            {"id": r["id"], "label": r["label"], "kind": r["kind"], "kind_label": r["kind_label"]}
            for r in view["roles"]
        ],
        "fields": [
            {
                "id": f["id"],
                "label": f["label"],
                "holds": f["holds"],
                "holds_label": f["holds_label"],
                "format": f["format"],
                "filled_by": f["filled_by"],
                "party_id": f["party_id"],
                "required": f["required"],
                "sensitive": f["sensitive"],
                "depends_on": {
                    "field_id": id_of[f["depends_on"]["key"]],
                    "option": f["depends_on"]["option"],
                }
                if f["depends_on"]
                else None,
                "places": [
                    {
                        "id": p["id"],
                        "page": p["page"],
                        "rect": p["rect"],
                        "kind": p["kind"],
                        "option_value": p["option_value"],
                        "option_text": p["option_text"],
                    }
                    for p in f["placements"]
                ],
            }
            for f in view["fields"]
        ],
    }


def _save(api: TestClient, document_id: str, version_id: str, body: dict[str, Any]) -> Any:
    return api.put(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/fields",
        json=body,
        headers=csrf_headers(api),
    )


def _drawn(
    label: str, party_id: str | None, x: float = 300.0, y: float = 700.0, **extra: Any
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "label": label,
        "holds": extra.pop("holds", "text"),
        "holds_label": extra.pop("holds_label", None),
        "filled_by": "role" if party_id else "sender",
        "party_id": party_id,
        "required": True,
        "sensitive": False,
        "depends_on": None,
        "places": [
            {
                "id": str(uuid.uuid4()),
                "page": 1,
                "rect": extra.pop("rect", [x, y, x + 160, y + 20]),
                "kind": "blank",
                "option_value": None,
                "option_text": None,
            }
        ],
        **extra,
    }


def test_a_save_writes_the_set_moves_the_revision_and_records_the_changes(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    view = _view(owner, document_id, version_id)
    body = _body(view)
    client_id = body["parties"][0]["id"]
    body["parties"].append(
        {"id": str(uuid.uuid4()), "label": "Witness", "kind": "signer", "kind_label": "Witness"}
    )
    body["fields"][0]["label"] = "Governing law: state"
    body["fields"].append(_drawn("Matter number", None, holds="other", holds_label="Matter number"))
    body["fields"].append(_drawn("Client email", client_id, holds="email", y=740))
    removed = body["fields"].pop(1)

    saved = _save(owner, document_id, version_id, body)

    assert (saved.status_code, saved.json()) == (200, {"revision": 1})
    after = _view(owner, document_id, version_id)
    assert after["revision"] == 1
    labels = {f["label"]: f for f in after["fields"]}
    assert "Governing law: state" in labels and removed["label"] not in labels
    matter = labels["Matter number"]
    assert (matter["holds"], matter["holds_label"], matter["origin"]) == (
        "other",
        "Matter number",
        "added",
    )
    assert matter["key"] == "agreement.matter_number"
    assert labels["Client email"]["key"] == "client.email"  # keys follow parties and labels
    witness = next(r for r in after["roles"] if r["label"] == "Witness")
    assert (witness["kind"], witness["kind_label"], witness["position"]) == ("signer", "Witness", 2)
    with committing_db.unit_of_work() as uow:
        data = uow.session.execute(
            text(
                "SELECT data FROM audit_events "
                "WHERE action = 'document.fields_saved' AND subject_id = :d"
            ),
            {"d": document_id},
        ).scalar_one()
    assert (data["revision"], data["added"], data["removed"], data["changed"]) == (1, 3, 1, 1)
    assert {c["what"] for c in data["changes"]} == {"party", "field"}
    document = owner.get(f"{DOCUMENTS}/{document_id}").json()
    assert document["versions"][0]["field_count"] == len(after["fields"])


def test_a_stale_save_an_approved_version_and_one_still_finding_fields_are_refused(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    approved: Callable[..., None],
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    assert _save(owner, document_id, version_id, body).status_code == 200

    stale = _save(owner, document_id, version_id, body)  # still revision 0
    assert (stale.status_code, stale.json()["code"]) == (409, "fields-changed")

    approved(version_id)
    frozen = _save(owner, document_id, version_id, {**body, "revision": 1})
    assert (frozen.status_code, frozen.json()["code"]) == (409, "fields-approved")

    department = create_department(owner, "Legal")
    other = new_document(owner, department["id"], forms.nda_like()).json()
    other_version = other["versions"][0]["id"]
    run(other_version)  # detecting: not yet in review
    waiting = _save(owner, other["id"], other_version, {"revision": 0, "parties": [], "fields": []})
    assert (waiting.status_code, waiting.json()["code"]) == (409, "version-not-in-review")


def test_malformed_sets_are_refused_naming_the_item(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    base = _body(_view(owner, document_id, version_id))
    client_id = base["parties"][0]["id"]
    pdf_place = base["fields"][0]["places"][0]

    def refused(change: Callable[[dict[str, Any]], None]) -> set[str]:
        body = _body(_view(owner, document_id, version_id))
        change(body)
        response = _save(owner, document_id, version_id, body)
        assert response.status_code == 422, response.text
        return {error["field"] for error in response.json()["errors"]}

    assert refused(
        lambda b: b["parties"].append(
            {**b["parties"][0], "id": str(uuid.uuid4()), "label": "CLIENT"}
        )
    ) == {"parties[1].label"}
    assert refused(
        lambda b: b["fields"].append(_drawn("X", None, holds="text", holds_label="X"))
    ) == {f"fields[{len(base['fields'])}].holds_label"}
    assert refused(lambda b: b["fields"].append(_drawn("X", client_id, filled_by="sender"))) == {
        f"fields[{len(base['fields'])}].party_id"
    }
    assert refused(
        lambda b: b["fields"].append(
            _drawn("X", None, depends_on={"field_id": str(uuid.uuid4()), "option": "checked"})
        )
    ) == {f"fields[{len(base['fields'])}].depends_on"}
    assert refused(lambda b: b["fields"].append(_drawn("Tiny", None, rect=[10, 10, 14, 14]))) == {
        f"fields[{len(base['fields'])}].places[0].rect"
    }
    assert refused(lambda b: b["fields"].append(_drawn("Off", None, rect=[590, 10, 700, 30]))) == {
        f"fields[{len(base['fields'])}].places[0].rect"
    }
    # The PDF's kind is kept; a drawn box is blank (each may also be wrong for the field's type).
    assert "fields[0].places[0].kind" in refused(
        lambda b: b["fields"][0]["places"].__setitem__(0, {**pdf_place, "kind": "blank"})
    )
    drawn = _drawn("New", None)
    drawn["places"][0]["kind"] = "signature"
    assert f"fields[{len(base['fields'])}].places[0].kind" in refused(
        lambda b: b["fields"].append(drawn)
    )

    def loop(body: dict[str, Any]) -> None:
        one = _drawn("One", None, holds="checkbox", rect=[300, 300, 312, 312])
        two = _drawn("Two", None, holds="checkbox", rect=[300, 330, 312, 342])
        one["depends_on"] = {"field_id": two["id"], "option": "checked"}
        two["depends_on"] = {"field_id": one["id"], "option": "checked"}
        body["fields"] += [one, two]

    assert any(path.endswith(".depends_on") for path in refused(loop))


def test_a_second_signature_of_a_party_becomes_more_places_of_the_first(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    client_id = body["parties"][0]["id"]
    before = [f for f in body["fields"] if f["holds"] == "signature" and f["party_id"] == client_id]
    body["fields"].append(
        _drawn("Client signature again", client_id, holds="signature", rect=[300, 700, 480, 736])
    )

    assert _save(owner, document_id, version_id, body).status_code == 200

    after = _view(owner, document_id, version_id)
    signatures = [
        f for f in after["fields"] if f["holds"] == "signature" and f["party_id"] == client_id
    ]
    assert len(signatures) == 1  # one value per party, wherever it is asked
    assert len(signatures[0]["placements"]) == sum(len(f["places"]) for f in before) + 1


def test_a_flag_stays_while_its_field_is_unchanged_and_clears_when_edited(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE version_fields SET needs_review = 'two answers' WHERE version_id = :v"),
            {"v": version_id},
        )
    body = _body(_view(owner, document_id, version_id))
    body["fields"][0]["required"] = not body["fields"][0]["required"]

    assert _save(owner, document_id, version_id, body).status_code == 200

    after = {f["id"]: f for f in _view(owner, document_id, version_id)["fields"]}
    assert after[body["fields"][0]["id"]]["needs_review"] is None  # edited: a person decided
    assert after[body["fields"][1]["id"]]["needs_review"] == "two answers"  # untouched


def test_read_only_members_cannot_save(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert _save(theirs, document_id, version_id, body).status_code == 403


def large_set(body: dict[str, Any], fields: int = 2000) -> dict[str, Any]:
    """``fields`` drawn fields with two places each, on a grid that fits a Letter page."""
    body["fields"] = []
    for n in range(fields):
        x, y = 20 + (n % 40) * 13, 20 + (n // 40) * 14
        field = _drawn(f"Field {n}", None, rect=[x, y, x + 10, y + 10])
        field["places"].append({**field["places"][0], "id": str(uuid.uuid4())})
        body["fields"].append(field)
    return body


def with_statistics(db: Database) -> None:
    """A running database has planner statistics (autovacuum); a freshly migrated test database has
    none, and its foreign-key checks then read whole tables. Timings are of the former."""
    with db.unit_of_work() as uow:
        uow.session.execute(
            text("ANALYZE document_versions, version_roles, version_fields, field_placements")
        )


def test_two_thousand_fields_save_in_under_a_second(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    """NFR-R1: 2 000 fields and 4 000 places, linear and in a constant number of statements; the
    first save of them, and the worst later one, every row replaced by new ones."""
    document_id, version_id = _in_review(owner, run, detect)
    body = large_set(_body(_view(owner, document_id, version_id)))
    with_statistics(committing_db)

    timings = []
    for revision in (0, 1):
        body = large_set({**body, "revision": revision})  # all new ids the second time
        started = time.monotonic()
        saved = _save(owner, document_id, version_id, body)
        timings.append(time.monotonic() - started)
        assert saved.status_code == 200, saved.text[:500]

    assert max(timings) < 1.0, [f"{t:.2f} s" for t in timings]


def test_a_pdf_boxs_option_keeps_its_value_and_its_words_through_a_save(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    """§4: the editor sees an option's words with the field inside them read as "…"; sent back so,
    the stored words (with the field) stay. A PDF radio's value is its widget's: never changed."""
    document_id, version_id = _in_review(owner, run, detect)
    view = _view(owner, document_id, version_id)
    choice = next(f for f in view["fields"] if f["holds"] == "choice")
    shown = next(p for p in choice["placements"] if "…" in (p["option_text"] or ""))

    def stored() -> str:
        with committing_db.unit_of_work() as uow:
            words: str = uow.session.execute(
                text("SELECT option_text FROM field_placements WHERE id = :p"), {"p": shown["id"]}
            ).scalar_one()
        return words

    before = stored()
    assert "{f" in before and "…" not in before
    assert _save(owner, document_id, version_id, _body(view)).status_code == 200
    assert stored() == before

    body = _body(_view(owner, document_id, version_id))
    field = next(f for f in body["fields"] if f["id"] == choice["id"])
    at = body["fields"].index(field)
    field["places"][0]["option_value"] = "Something the widget has not got"
    refused = _save(owner, document_id, version_id, body)
    assert refused.status_code == 422, refused.text
    # The field asked under that option also says its option is gone.
    assert f"fields[{at}].places[0].option_value" in {e["field"] for e in refused.json()["errors"]}


def test_making_an_other_value_private_is_a_change() -> None:
    """§1.4, §2.2: a field's privacy is one of its attributes: turning it on clears the field's
    flag and is one change in the audit entry."""
    from signora.modules.review.editing import (
        Stored,
        StoredField,
        StoredPlace,
        changes,
        settle,
        unchanged,
    )
    from signora.modules.review.fieldset import FieldSet

    field_id, place_id = uuid.uuid4(), uuid.uuid4()
    stored = Stored(
        parties={},
        fields={
            field_id: StoredField(
                id=field_id,
                label="Matter",
                holds="other",
                holds_label="Matter number",
                format=None,
                filled_by="sender",
                party_id=None,
                required=True,
                sensitive=False,
                depends_on=None,
                needs_review="check it",
                origin="added",
            )
        },
        places={
            place_id: StoredPlace(
                id=place_id,
                field_id=field_id,
                page=1,
                rect=(1.0, 2.0, 30.0, 40.0),
                kind="blank",
                pdf_field=None,
                option_value=None,
                option_text=None,
            )
        },
    )
    fieldset = FieldSet.model_validate(
        {
            "revision": 1,
            "parties": [],
            "fields": [
                {
                    "id": str(field_id),
                    "label": "Matter",
                    "holds": "other",
                    "holds_label": "Matter number",
                    "filled_by": "sender",
                    "party_id": None,
                    "required": True,
                    "sensitive": True,
                    "depends_on": None,
                    "places": [
                        {
                            "id": str(place_id),
                            "page": 1,
                            "rect": [1, 2, 30, 40],
                            "kind": "blank",
                            "option_value": None,
                            "option_text": None,
                        }
                    ],
                }
            ],
        }
    )
    assert not unchanged(fieldset.fields[0], stored.fields[field_id], stored)
    assert changes(stored, settle(fieldset))["changed"] == 1


def test_a_drawn_box_can_hold_anything_a_pdf_box_keeps_its_nature(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    """Phase 6 §4, §5: the palette's checkbox and a hand-made choice are drawn boxes."""
    document_id, version_id = _in_review(owner, run, detect)
    view = _view(owner, document_id, version_id)
    assert view["allowed"]["blank"][-2:] == ["note", "other"]
    assert view["allowed"]["checkbox"] == ["checkbox"]
    body = _body(view)
    body["fields"].append(_drawn("Agree", None, holds="checkbox", rect=[300, 40, 312, 52]))
    choice = _drawn("Plan", None, holds="choice", rect=[300, 80, 312, 92])
    choice["places"][0] |= {"option_value": "Gold", "option_text": "Gold"}
    choice["places"].append(
        {**choice["places"][0], "id": str(uuid.uuid4()), "rect": [300, 100, 312, 112]}
        | {"option_value": "Silver", "option_text": "Silver"}
    )
    body["fields"].append(choice)
    assert _save(owner, document_id, version_id, body).status_code == 200

    body = _body(_view(owner, document_id, version_id))
    pdf_text = next(f for f in body["fields"] if any(p["kind"] == "text" for p in f["places"]))
    pdf_text["holds"] = "checkbox"
    refused = _save(owner, document_id, version_id, body)
    assert refused.status_code == 422
