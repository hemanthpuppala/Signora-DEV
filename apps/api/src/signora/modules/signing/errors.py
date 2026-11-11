"""Signing's refusals (Phase 8 LLD). Titles are what people read."""

from __future__ import annotations

from signora.kernel.errors import NotFound, Unauthenticated


class LinkClosed(NotFound):
    """One answer for every link that cannot be used, so a guess learns nothing (§1.1.6)."""

    code = "link-closed"
    title = "This request is no longer open. Nothing more is needed from you"


class SessionEnded(Unauthenticated):
    code = "session-ended"
    title = "Your session ended. Open the link in your email again"
