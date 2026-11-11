"""Limits on the signer's routes (Phase 8 LLD §13), through the kernel's one rate limiter.

Per address: opening links and trying codes. Per browser session (or signed-in countersigner):
saving drafts, submitting and declining. The limits on a person's codes are kept in Postgres
(``codes``), so they hold across restarts and API processes; these are in the limiter, correct
for this deployment's single API process (Redis, behind the same protocol, for more).
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import Request

from signora.kernel.errors import RateLimited
from signora.kernel.ratelimit import RateLimiter

MINUTE = timedelta(minutes=1)
LIMITS = {
    "open": 20,  # a minute, per address
    "verify": 10,  # a minute, per address
    "draft": 120,  # a minute, per session
    "act": 10,  # submit and decline, a minute, per session
}


def _limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def by_address(request: Request, action: str) -> None:
    address = getattr(request.state, "client_ip", None) or "unknown"
    _hit(request, f"sign:{action}:ip:{address}", LIMITS[action])


def by_session(request: Request, action: str, who: str) -> None:
    _hit(request, f"sign:{action}:session:{who}", LIMITS[action])


def _hit(request: Request, key: str, limit: int) -> None:
    retry = _limiter(request).hit(key, limit=limit, window=MINUTE)
    if retry is not None:
        raise RateLimited(retry, "Too many tries. Try again in a minute.")
