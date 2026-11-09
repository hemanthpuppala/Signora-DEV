"""Detection tests reuse the documents fixtures (an owner, uploads, processing)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import text

from signora.kernel.blobstore import LocalBlobStore
from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.kernel.events import bus
from signora.kernel.jobs import JobContext
from signora.modules.detection.ai import Assigner
from signora.modules.detection.jobs import SUBSCRIBER
from signora.modules.detection.run import run_detection
from tests.modules.documents.conftest import (  # noqa: F401 - fixtures by name
    company,
    owner,
    run,
    settings,
)
from tests.modules.identity_access.conftest import (  # noqa: F401 - fixtures by name
    add_member,
    client,
    make_client,
    make_workspace,
)

KIND = bus.job_kind("DocumentVersionProcessed", SUBSCRIBER)  # every detection runs as this job


@pytest.fixture
def detect(committing_db: Database, settings: Settings) -> Callable[..., None]:  # noqa: F811
    """Run detection for a version as its job would, with the given AI."""

    def go(version_id: str, assigner: Assigner) -> None:
        payload = {"version_id": version_id}
        with committing_db.unit_of_work() as uow:
            job_id = uow.session.execute(
                text(
                    "INSERT INTO jobs (kind, status, attempts, payload) "
                    "VALUES (:k, 'running', 1, CAST(:p AS jsonb)) RETURNING id"
                ),
                {"k": KIND, "p": json.dumps(payload)},
            ).scalar_one()
        run_detection(
            JobContext(job_id, KIND, payload, {}, 1, committing_db),
            uuid.UUID(version_id),
            store=LocalBlobStore(settings.blob_store.dir),
            assigner=assigner,
        )

    return go
