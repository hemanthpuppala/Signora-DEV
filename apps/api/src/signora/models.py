"""Registry of table definitions.

Importing this module imports every module that declares tables, so ``signora.kernel.db.metadata``
is complete for Alembic and for the "models match migrations" test. Add each new model module here.
"""

from __future__ import annotations
