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
from signora.kernel.jobs import JobContext
from signora.modules.detection.ai import Assigner
from signora.modules.detection.jobs import RUN
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


@pytest.fixture
def detect(committing_db: Database, settings: Settings) -> Callable[..., None]:  # noqa: F811
    """Run detection for a version as its job would, with the given AI."""

    def go(version_id: str, assigner: Assigner, *, run_id: str | None = None) -> None:
        payload = {"version_id": version_id, **({"run_id": run_id} if run_id else {})}
        with committing_db.unit_of_work() as uow:
            job_id = uow.session.execute(
                text(
                    "INSERT INTO jobs (kind, status, attempts, payload) "
                    "VALUES (:k, 'running', 1, CAST(:p AS jsonb)) RETURNING id"
                ),
                {"k": RUN, "p": json.dumps(payload)},
            ).scalar_one()
        run_detection(
            JobContext(job_id, RUN, payload, {}, 1, committing_db),
            uuid.UUID(version_id),
            run_id=uuid.UUID(run_id) if run_id else None,
            store=LocalBlobStore(settings.blob_store.dir),
            assigner=assigner,
        )

    return go
