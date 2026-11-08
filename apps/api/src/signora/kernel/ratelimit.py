"""Rate limiting (Phase 2 LLD §7.1).

One ``RateLimiter`` enforces every limit: sliding-window counts (e.g. one sign-up email per address
per 60 s, 100 failed log-ins per IP per 15 min) and failure streaks with doubling waits (log-in per
email). Callers namespace their keys (``login:email:…``, ``email:signup:…``).

``InMemoryRateLimiter`` serves a single API process; its state resets on restart, which attackers
cannot trigger. A Redis implementation is one new class behind the same protocol plus a setting
value (``RATE_LIMITER_BACKEND``), with no change to callers.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from signora.kernel.config import RateLimitSettings


class RateLimiter(Protocol):
    def check(self, key: str, *, limit: int, window: timedelta) -> int | None:
        """Seconds until ``key`` may act again when ``limit`` events already happened within
        ``window``; ``None`` when it may act now. Records nothing."""
        ...

    def hit(self, key: str, *, limit: int, window: timedelta) -> int | None:
        """Like ``check``, and records the event when allowed (a refused event is not counted)."""
        ...

    def backoff(self, key: str) -> int | None:
        """Seconds left in the current failure wait for ``key``, or ``None``."""
        ...

    def record_failure(self, key: str, *, free: int, base: timedelta, cap: timedelta) -> None:
        """Count a consecutive failure. From the ``free``-th one on, the next attempt waits
        ``base``, then twice as long after each further failure, up to ``cap``."""
        ...

    def reset(self, key: str) -> None:
        """Forget ``key`` (e.g. after a successful log-in)."""
        ...


def _ceil_seconds(value: float) -> int:
    return max(1, math.ceil(value))


@dataclass
class _Entry:
    events: deque[float] = field(default_factory=deque)
    streak: int = 0
    blocked_until: float = 0.0


class InMemoryRateLimiter:
    """Thread-safe and bounded: at most ``max_keys`` keys, least recently used evicted first.

    Each key holds at most ``limit`` timestamps (refused events are not stored), so memory is
    O(max_keys x limit) and every operation is O(1) amortised.
    """

    def __init__(self, *, max_keys: int, clock: Callable[[], float] = time.monotonic) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be at least 1")
        self._max_keys = max_keys
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._entries)

    def _entry(self, key: str) -> _Entry:
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry()
            self._entries[key] = entry
            if len(self._entries) > self._max_keys:
                self._entries.popitem(last=False)
        else:
            self._entries.move_to_end(key)
        return entry

    @staticmethod
    def _window_retry(entry: _Entry, now: float, limit: int, window: float) -> int | None:
        while entry.events and entry.events[0] <= now - window:
            entry.events.popleft()
        if len(entry.events) < limit:
            return None
        return _ceil_seconds(entry.events[0] + window - now)

    def check(self, key: str, *, limit: int, window: timedelta) -> int | None:
        with self._lock:
            now = self._clock()
            return self._window_retry(self._entry(key), now, limit, window.total_seconds())

    def hit(self, key: str, *, limit: int, window: timedelta) -> int | None:
        with self._lock:
            now = self._clock()
            entry = self._entry(key)
            retry = self._window_retry(entry, now, limit, window.total_seconds())
            if retry is None:
                entry.events.append(now)
            return retry

    def backoff(self, key: str) -> int | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            remaining = entry.blocked_until - self._clock()
            return _ceil_seconds(remaining) if remaining > 0 else None

    def record_failure(self, key: str, *, free: int, base: timedelta, cap: timedelta) -> None:
        with self._lock:
            entry = self._entry(key)
            entry.streak += 1
            if entry.streak >= free:
                # The exponent is capped so a very long streak cannot overflow the float.
                doublings = min(entry.streak - free, 62)
                wait = min(base.total_seconds() * 2**doublings, cap.total_seconds())
                entry.blocked_until = self._clock() + wait

    def reset(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)


def create_rate_limiter(settings: RateLimitSettings) -> RateLimiter:
    """The configured limiter. Only ``memory`` exists today; ``redis`` is added with its class."""
    match settings.backend:
        case "memory":
            return InMemoryRateLimiter(max_keys=settings.max_keys)
