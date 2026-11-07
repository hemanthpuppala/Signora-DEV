"""Where the current action came from (request id, client IP, user agent).

Set by the HTTP middleware for each request; read by the audit module so entries carry their
origin automatically (backbone LLD §4.3). Outside a request (jobs, CLI) it is ``None``.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Origin:
    request_id: str | None
    ip: str | None
    user_agent: str | None


_origin: ContextVar[Origin | None] = ContextVar("signora_origin", default=None)


def set_origin(origin: Origin | None) -> None:
    _origin.set(origin)


def current_origin() -> Origin | None:
    return _origin.get()
