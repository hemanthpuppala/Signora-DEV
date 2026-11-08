"""Department tests reuse the identity fixtures (real app, committed database, accounts)."""

from tests.modules.identity_access.conftest import (  # noqa: F401 - fixtures by name
    add_member,
    client,
    make_client,
    make_workspace,
    settings,
)
