"""Registry of table definitions.

Importing this module imports every module that declares tables, so ``signora.kernel.db.metadata``
is complete for Alembic and for the "models match migrations" test. Add each new model module here.
"""

from __future__ import annotations

from signora.kernel.idempotency import tables as _idempotency_tables  # noqa: F401
from signora.kernel.jobs import tables as _jobs_tables  # noqa: F401
from signora.modules.audit import models as _audit_models  # noqa: F401
from signora.modules.departments import models as _departments_models  # noqa: F401
from signora.modules.identity_access import models as _identity_access_models  # noqa: F401
from signora.modules.notifications import models as _notifications_models  # noqa: F401
