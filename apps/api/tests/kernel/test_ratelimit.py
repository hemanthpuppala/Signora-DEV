"""Rate limiter tests (Phase 2 LLD §7.1)."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from signora.kernel.config import RateLimitSettings
from signora.kernel.ratelimit import InMemoryRateLimiter, create_rate_limiter

MINUTE = timedelta(minutes=1)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(clock: FakeClock) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(max_keys=1000, clock=clock)


def test_window_allows_up_to_the_limit_then_reports_the_wait(
    limiter: InMemoryRateLimiter, clock: FakeClock
) -> None:
    window = timedelta(seconds=60)
    assert [limiter.hit("k", limit=3, window=window) for _ in range(3)] == [None, None, None]

    clock.advance(10)
    assert limiter.hit("k", limit=3, window=window) == 50  # the oldest event leaves at t+60

    clock.advance(50)
    assert limiter.hit("k", limit=3, window=window) is None


def test_refused_hits_are_not_counted(limiter: InMemoryRateLimiter, clock: FakeClock) -> None:
    window = timedelta(seconds=60)
    limiter.hit("k", limit=1, window=window)
    for _ in range(10):
        clock.advance(5)
        assert limiter.hit("k", limit=1, window=window) is not None

    clock.advance(10)  # 60 s after the only counted event
    assert limiter.hit("k", limit=1, window=window) is None


def test_check_never_records(limiter: InMemoryRateLimiter) -> None:
    for _ in range(5):
        assert limiter.check("k", limit=1, window=MINUTE) is None
    assert limiter.hit("k", limit=1, window=MINUTE) is None
    assert limiter.check("k", limit=1, window=MINUTE) == 60


def test_keys_are_independent(limiter: InMemoryRateLimiter) -> None:
    assert limiter.hit("a", limit=1, window=MINUTE) is None
    assert limiter.hit("b", limit=1, window=MINUTE) is None
    assert limiter.hit("a", limit=1, window=MINUTE) == 60


def test_failure_waits_start_after_the_free_attempts_and_double_to_the_cap(
    limiter: InMemoryRateLimiter, clock: FakeClock
) -> None:
    def fail() -> int | None:
        limiter.record_failure("k", free=5, base=timedelta(seconds=1), cap=timedelta(seconds=10))
        return limiter.backoff("k")

    assert [fail() for _ in range(4)] == [None, None, None, None]
    assert fail() == 1  # the 5th failure: wait 1 s
    assert fail() == 2
    assert fail() == 4
    assert fail() == 8
    assert fail() == 10  # capped
    assert fail() == 10

    clock.advance(10)
    assert limiter.backoff("k") is None


def test_a_very_long_failure_streak_stays_at_the_cap(limiter: InMemoryRateLimiter) -> None:
    for _ in range(2000):
        limiter.record_failure("k", free=5, base=timedelta(seconds=1), cap=timedelta(minutes=15))
    assert limiter.backoff("k") == 900


def test_reset_clears_the_streak_and_window(limiter: InMemoryRateLimiter) -> None:
    for _ in range(6):
        limiter.record_failure("k", free=5, base=timedelta(seconds=1), cap=MINUTE)
    limiter.hit("k", limit=1, window=MINUTE)

    limiter.reset("k")

    assert limiter.backoff("k") is None
    assert limiter.hit("k", limit=1, window=MINUTE) is None


def test_keys_are_bounded_and_least_recently_used_go_first(clock: FakeClock) -> None:
    limiter = InMemoryRateLimiter(max_keys=3, clock=clock)
    for key in ("a", "b", "c"):
        limiter.hit(key, limit=1, window=MINUTE)
    limiter.check("a", limit=1, window=MINUTE)  # "a" is now the most recently used

    limiter.hit("d", limit=1, window=MINUTE)  # evicts "b"

    assert len(limiter) == 3
    assert limiter.check("a", limit=1, window=MINUTE) == 60
    assert limiter.check("b", limit=1, window=MINUTE) is None  # forgotten


def test_concurrent_hits_never_exceed_the_limit() -> None:
    limiter = InMemoryRateLimiter(max_keys=10)
    allowed: list[bool] = []
    lock = threading.Lock()
    start = threading.Barrier(20)

    def worker() -> None:
        start.wait()
        for _ in range(50):
            ok = limiter.hit("shared", limit=100, window=timedelta(hours=1)) is None
            with lock:
                allowed.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(allowed) == 100


def test_factory_builds_the_configured_backend() -> None:
    limiter = create_rate_limiter(RateLimitSettings(backend="memory", max_keys=5000))
    assert isinstance(limiter, InMemoryRateLimiter)
