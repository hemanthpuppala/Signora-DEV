"""Table definitions in code must match the migrated database exactly."""

from __future__ import annotations

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine

import signora.models  # noqa: F401  (registers every table)
from signora.kernel.db import metadata

# Tables created by migrations whose code definitions arrive in later tasks. Remove each entry when
# its module adds the table definition; the test then compares it too.
NOT_YET_MODELLED = {"audit_events"}


def _include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    if type_ == "table":
        return name not in NOT_YET_MODELLED and name != "alembic_version"
    return True


def test_models_match_migrations(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True, "include_object": _include},
        )
        differences = compare_metadata(context, metadata)

    assert differences == []
