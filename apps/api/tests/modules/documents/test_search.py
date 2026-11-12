"""A department's templates: newest first or as sorted, searched by name with typos forgiven, best
match first (ADR S-1); and how many wait for approval (the Templates dot)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from tests.modules.documents.conftest import DEPARTMENTS, create_department, new_document
from tests.support.files import pdf_bytes

NAMES = ["Mutual NDA", "Employment Agreement", "Consulting Agreement", "100%_Plan"]


def _templates(api: TestClient, department_id: str, **params: Any) -> list[str]:
    answer = api.get(f"{DEPARTMENTS}/{department_id}/documents", params=params)
    assert answer.status_code == 200, answer.text
    return [document["name"] for document in answer.json()]


def _department(owner: TestClient) -> tuple[str, dict[str, Any]]:
    department = create_department(owner)
    made = {}
    for name in NAMES:  # created one after another: the last is the newest
        created = new_document(owner, department["id"], pdf_bytes(text=name), name=name)
        assert created.status_code == 201, created.text
        made[name] = created.json()
    return department["id"], made


def test_templates_are_newest_first_and_sort_as_asked(owner: TestClient) -> None:
    department_id, _ = _department(owner)

    assert _templates(owner, department_id) == NAMES[::-1]
    assert _templates(owner, department_id, sort="oldest") == NAMES
    assert _templates(owner, department_id, sort="name") == sorted(NAMES, key=str.lower)
    assert (
        owner.get(f"{DEPARTMENTS}/{department_id}/documents", params={"sort": "x"}).status_code
        == 422
    )


def test_a_search_forgives_typos_and_puts_the_best_match_first(owner: TestClient) -> None:
    department_id, _ = _department(owner)

    assert _templates(owner, department_id, q="emplyment") == ["Employment Agreement"]
    # Both contain it: equal matches, newest first.
    assert _templates(owner, department_id, q="AGREEMENT") == [
        "Consulting Agreement",
        "Employment Agreement",
    ]
    assert _templates(owner, department_id, q="  mutual   nda ") == ["Mutual NDA"]  # spaces
    assert _templates(owner, department_id, q="%") == ["100%_Plan"]  # a letter, not a pattern
    assert _templates(owner, department_id, q="_") == ["100%_Plan"]
    assert _templates(owner, department_id, q="zzzz") == []
    assert len(_templates(owner, department_id, q="   ")) == len(NAMES)  # no search at all


def test_templates_waiting_for_approval_are_counted_for_the_department(
    owner: TestClient, ready: Callable[..., None]
) -> None:
    department_id, made = _department(owner)
    counts = owner.get(f"{DEPARTMENTS}/{department_id}").json()["counts"]
    assert counts["to_approve"] == 0  # still being read

    for name in ("Mutual NDA", "100%_Plan"):
        ready(str(made[name]["versions"][0]["id"]))

    assert owner.get(f"{DEPARTMENTS}/{department_id}").json()["counts"]["to_approve"] == 2
    home = {d["id"]: d["counts"] for d in owner.get(DEPARTMENTS).json()}
    assert home[department_id]["to_approve"] == 2


def test_a_sort_chosen_while_searching_orders_the_matches(owner: TestClient) -> None:
    department_id, _ = _department(owner)

    assert _templates(owner, department_id, q="agreement", sort="name") == [
        "Consulting Agreement",
        "Employment Agreement",
    ]
    assert _templates(owner, department_id, q="agreement", sort="oldest") == [
        "Employment Agreement",
        "Consulting Agreement",
    ]
