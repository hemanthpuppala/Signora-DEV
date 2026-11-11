"""Signing tests: an envelope sent through the API as a sender would, to sign or decline.

Reuses the envelope fixtures (owner, company, uploads, detection) by name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

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
