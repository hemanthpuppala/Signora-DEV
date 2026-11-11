"""Signing tests: an envelope sent through the API as a sender would, to sign or decline.

Reuses the envelope fixtures (owner, company, uploads, detection) by name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import LocalBlobStore
from signora.kernel.db import Database
from signora.kernel.jobs import JobContext
from signora.modules.signing import completion
from tests.modules.detection.conftest import detect  # noqa: F401 - fixtures by name
from tests.modules.documents.conftest import (  # noqa: F401 - fixtures by name
    approved,
    company,
    owner,
    ready,
    run,
    settings,
)
from tests.modules.envelopes.conftest import Sendable, sendable
from tests.modules.envelopes.test_send import request_for, send
from tests.modules.identity_access.conftest import (  # noqa: F401 - fixtures by name
    Account,
    add_member,
    client,
    make_client,
    make_workspace,
)
from tests.modules.review.test_save import _drawn


@dataclass(frozen=True)
class Sent:
    doc: Sendable
    envelope: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.envelope["id"])

    def recipient(self, kind: str) -> dict[str, Any]:
        return next(r for r in self.envelope["recipients"] if r["kind"] == kind)


def sent_envelope(
    api: TestClient,
    run_job: Callable[..., None],
    detect_fields: Callable[..., None],
    colleague: Account,
    **override: Any,
) -> Sent:
    """The test NDA sent to one signer (Client), countersigned by ``colleague`` (Firm)."""
    doc = sendable(api, run_job, detect_fields)
    response = send(api, doc, request_for(api, doc, colleague, **override))
    assert response.status_code == 201, response.text
    return Sent(doc, response.json())


def client_fields(party: str) -> list[dict[str, Any]]:
    """What the client fills besides signing: a required title, an optional phone, a private tax
    number, and a box that, ticked, asks which marketing topics."""
    marketing = _drawn("Client marketing", party, holds="checkbox", rect=[300, 752, 316, 768])
    marketing["required"] = False
    return [
        _drawn("Client title", party, rect=[60, 720, 240, 740]),
        {
            **_drawn("Client phone", party, holds="phone", rect=[60, 750, 240, 770]),
            "required": False,
        },
        _drawn("Client tax number", party, holds="tax_id", rect=[300, 720, 480, 740]),
        marketing,
        {
            **_drawn("Marketing topics", party, rect=[330, 750, 480, 770]),
            "required": False,
            "depends_on": {"field_id": marketing["id"], "option": "checked"},
        },
    ]


def signable_envelope(
    api: TestClient,
    run_job: Callable[..., None],
    detect_fields: Callable[..., None],
    colleague: Account,
    **override: Any,
) -> Sent:
    """The test NDA with the client's own fields (``client_fields``), sent."""
    doc = sendable(api, run_job, detect_fields, extra=client_fields)
    response = send(api, doc, request_for(api, doc, colleague, **override))
    assert response.status_code == 201, response.text
    return Sent(doc, response.json())


def run_completion(db: Database, envelope_id: str, store: LocalBlobStore) -> None:
    """The completion job queued by the last countersignature, run here as the worker would."""
    with db.unit_of_work() as uow:
        job = uow.session.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1 "
                "WHERE dedupe_key = :k RETURNING id, attempts"
            ),
            {"k": f"{completion.COMPLETE}:{envelope_id}"},
        ).one()
    payload = {"envelope_id": envelope_id}
    context = JobContext(job.id, completion.COMPLETE, payload, {}, job.attempts, db)
    completion.complete(context, store=store)
