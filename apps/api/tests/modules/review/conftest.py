"""Review tests reuse the detection and documents fixtures: owner, uploads, detection."""

from __future__ import annotations

from tests.modules.detection.conftest import detect  # noqa: F401 - fixtures by name
from tests.modules.documents.conftest import (  # noqa: F401 - fixtures by name
    approved,
    company,
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
