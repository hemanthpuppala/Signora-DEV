"""Extension points other modules register with (dependency stays one-way: they import us).

``on_member_removed``: called inside the removal's transaction, so a module's clean-up (e.g.
departments dropping a removed countersigner) commits or rolls back with the removal itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from signora.kernel.db import UnitOfWork

MemberRemovedHook = Callable[[UnitOfWork, uuid.UUID, uuid.UUID], None]  # (uow, workspace, user)

_member_removed: list[MemberRemovedHook] = []


def on_member_removed(hook: MemberRemovedHook) -> None:
    """Register ``hook``; registering the same function again is a no-op."""
    if hook not in _member_removed:
        _member_removed.append(hook)


def run_member_removed(uow: UnitOfWork, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    for hook in _member_removed:
        hook(uow, workspace_id, user_id)
