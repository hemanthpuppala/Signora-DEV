"""Envelope tests: an approved, reviewed document to send, built through the API as a person would.

Reuses the documents, detection and identity fixtures (owner, uploads, detection) by name.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from tests.modules.detection.conftest import detect  # noqa: F401 - fixtures by name
from tests.modules.documents.conftest import (  # noqa: F401 - fixtures by name
    DEPARTMENTS,
    approved,
    company,
    csrf_headers,
    owner,
    ready,
    run,
    settings,
)
from tests.modules.identity_access.conftest import (  # noqa: F401 - fixtures by name
    add_member,
    client,
    make_client,
    make_workspace,
)
from tests.modules.review.test_approve import _approve
from tests.modules.review.test_save import DOCUMENTS, _body, _drawn, _in_review, _save, _view


@dataclass(frozen=True)
class Sendable:
    document_id: str
    version_id: str
    department_id: str
    view: dict[str, Any]  # the approved version's fields view

    def party(self, label: str) -> dict[str, Any]:
        return next(p for p in self.view["roles"] if p["label"] == label)

    def field(self, label: str) -> dict[str, Any]:
        return next(f for f in self.view["fields"] if f["label"] == label)


def sendable(
    api: TestClient,
    run_job: Callable[..., None],
    detect_fields: Callable[..., None],
    extra: Callable[[str], list[dict[str, Any]]] | None = None,
) -> Sendable:
    """The test NDA, reviewed: its client party (with a printed name and an email from the
    signer), a firm party that countersigns, a required effective date and an optional note filled
    in before sending; approved."""
    document_id, version_id = _in_review(api, run_job, detect_fields)
    body = _body(_view(api, document_id, version_id))
    firm = {"id": str(uuid.uuid4()), "label": "Firm", "kind": "countersigner", "kind_label": None}
    body["parties"].append(firm)
    party = next(p for p in body["parties"] if p["label"] == "Client")
    body["fields"] += [
        _drawn("Client printed name", party["id"], holds="full_name", rect=[60, 660, 240, 680]),
        _drawn("Client email", party["id"], holds="email", rect=[60, 690, 240, 710]),
        _drawn("Firm signature", firm["id"], holds="signature", rect=[300, 600, 480, 636]),
        _drawn("Effective date", None, holds="date", rect=[300, 40, 400, 60]),
        {
            **_drawn("Internal note", None, holds="text", rect=[300, 80, 460, 100]),
            "required": False,
        },
    ]
    if extra is not None:  # more fields of the client party, given its id
        body["fields"] += extra(party["id"])
    saved = _save(api, document_id, version_id, body)
    assert saved.status_code == 200, saved.text
    assert _approve(api, document_id, version_id).status_code == 204
    document = api.get(f"{DOCUMENTS}/{document_id}").json()
    return Sendable(
        document_id, version_id, document["department_id"], _view(api, document_id, version_id)
    )


def make_countersigner(api: TestClient, department_id: str, user_ids: list[str]) -> None:
    response = api.put(
        f"{DEPARTMENTS}/{department_id}/countersigners",
        json={"user_ids": user_ids},
        headers=csrf_headers(api),
    )
    assert response.status_code == 200, response.text
