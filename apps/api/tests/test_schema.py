"""Table definitions in code must match the migrated database exactly."""

from __future__ import annotations

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine

import signora.models  # noqa: F401  (registers every table)
from signora.kernel.db import metadata


def _include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    return not (type_ == "table" and name == "alembic_version")


def test_models_match_migrations(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True, "include_object": _include},
        )
        differences = compare_metadata(context, metadata)

    assert differences == []
