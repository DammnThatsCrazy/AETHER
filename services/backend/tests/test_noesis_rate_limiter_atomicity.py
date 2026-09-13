"""Atomicity tests for Noesis rate limiter.

Verifies that concurrent requests cannot all slip through when the limit is 1.
Uses the in-memory CacheClient (AETHER_ENV=local) which is safe for concurrent
asyncio tasks since asyncio is cooperative — the lock in _InMemoryBackend.incr_if_under
prevents the TOCTOU race.
"""

from __future__ import annotations

import asyncio

import pytest

from services.noesis.rate_limiter import NoesisRateLimiter
from shared.cache.cache import CacheClient
from shared.common.common import RateLimitedError


@pytest.mark.asyncio
async def test_rate_limiter_qpm_atomicity_in_memory():
    """100 concurrent requests against QPM=10 must allow exactly 10."""
    cache = CacheClient()
    # Force in-memory backend
    from shared.cache.cache import _InMemoryBackend
    cache._backend = _InMemoryBackend()
    cache._connected = True

    limiter = NoesisRateLimiter(cache=cache)
    limiter._qpm_limit = 10
    limiter._daily_limit = 10_000

    allowed = 0
    blocked = 0

    async def _attempt():
        nonlocal allowed, blocked
        try:
            await limiter.check_and_increment("tenant-atomic")
            allowed += 1
        except RateLimitedError:
            blocked += 1

    await asyncio.gather(*[_attempt() for _ in range(100)])

    assert allowed == 10, f"Expected exactly 10 allowed, got {allowed}"
    assert blocked == 90, f"Expected 90 blocked, got {blocked}"


@pytest.mark.asyncio
async def test_rate_limiter_daily_atomicity_in_memory():
    """100 concurrent requests against daily=5 must allow exactly 5."""
    cache = CacheClient()
    from shared.cache.cache import _InMemoryBackend
    cache._backend = _InMemoryBackend()
    cache._connected = True

    limiter = NoesisRateLimiter(cache=cache)
    limiter._qpm_limit = 10_000
    limiter._daily_limit = 5

    allowed = 0
    blocked = 0

    async def _attempt():
        nonlocal allowed, blocked
        try:
            await limiter.check_and_increment("tenant-daily-atomic")
            allowed += 1
        except RateLimitedError:
            blocked += 1

    await asyncio.gather(*[_attempt() for _ in range(100)])

    assert allowed == 5, f"Expected exactly 5 allowed, got {allowed}"
    assert blocked == 95, f"Expected 95 blocked, got {blocked}"


@pytest.mark.asyncio
async def test_incr_if_under_in_memory_respects_limit():
    from shared.cache.cache import _InMemoryBackend
    backend = _InMemoryBackend()

    results = await asyncio.gather(*[
        backend.incr_if_under("test-key", limit=3, ttl=60)
        for _ in range(10)
    ])

    allowed = [r for r in results if r[1]]
    blocked = [r for r in results if not r[1]]
    assert len(allowed) == 3
    assert len(blocked) == 7


@pytest.mark.asyncio
async def test_incr_if_under_returns_correct_count():
    from shared.cache.cache import _InMemoryBackend
    backend = _InMemoryBackend()

    count1, ok1 = await backend.incr_if_under("counter", limit=2, ttl=60)
    count2, ok2 = await backend.incr_if_under("counter", limit=2, ttl=60)
    count3, ok3 = await backend.incr_if_under("counter", limit=2, ttl=60)

    assert count1 == 1 and ok1
    assert count2 == 2 and ok2
    assert count3 == 3 and not ok3
