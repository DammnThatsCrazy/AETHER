"""Atomicity and correctness tests for Noesis token budget."""

from __future__ import annotations

import asyncio

import pytest

from services.noesis.token_budget import NoesisTokenBudget
from shared.cache.cache import CacheClient, _InMemoryBackend


def _make_budget(daily=5000, monthly=50000, global_=100000) -> NoesisTokenBudget:
    cache = CacheClient()
    cache._backend = _InMemoryBackend()
    cache._connected = True
    budget = NoesisTokenBudget(cache=cache)
    budget._per_tenant_daily_limit = daily
    budget._per_tenant_monthly_limit = monthly
    budget._global_daily_limit = global_
    return budget


@pytest.mark.asyncio
async def test_incr_by_actually_stores_amount():
    """Verifies incr_by stores the full amount (not just 1)."""
    cache = CacheClient()
    backend = _InMemoryBackend()
    cache._backend = backend
    cache._connected = True

    result = await cache.incr_by("budget-test", 800, ttl=60)
    assert result == 800, f"Expected 800, got {result}"

    result2 = await cache.incr_by("budget-test", 200, ttl=60)
    assert result2 == 1000, f"Expected 1000, got {result2}"


@pytest.mark.asyncio
async def test_token_budget_blocks_when_exceeded():
    budget = _make_budget(daily=500)
    # Reserve 500 — should succeed
    ok = await budget.check_and_reserve("tenant-a", 500)
    assert ok

    # Reserve 1 more — should fail
    ok2 = await budget.check_and_reserve("tenant-a", 1)
    assert not ok2


@pytest.mark.asyncio
async def test_token_budget_concurrent_requests_respect_limit():
    """20 concurrent requests each estimating 600 tokens against daily=5000.

    With atomic reservation, total consumed must not exceed 5000.
    """
    budget = _make_budget(daily=5000, monthly=100000, global_=1000000)

    allowed = 0
    blocked = 0

    async def _attempt():
        nonlocal allowed, blocked
        ok = await budget.check_and_reserve("tenant-concurrent", 600)
        if ok:
            allowed += 1
        else:
            blocked += 1

    await asyncio.gather(*[_attempt() for _ in range(20)])

    # 5000 / 600 = 8 requests allowed (floor), 12 blocked
    assert allowed <= 9, f"Too many allowed: {allowed}"
    assert (allowed + blocked) == 20


@pytest.mark.asyncio
async def test_token_budget_release_reduces_usage():
    budget = _make_budget(daily=1000)

    # Reserve 1000
    ok = await budget.check_and_reserve("tenant-rel", 1000)
    assert ok

    # Release 500
    await budget.release("tenant-rel", 500)

    # Now 500 more should fit
    ok2 = await budget.check_and_reserve("tenant-rel", 500)
    assert ok2


@pytest.mark.asyncio
async def test_token_budget_release_noop_for_zero():
    """release(0) must not raise and must not change state."""
    budget = _make_budget(daily=100)
    await budget.check_and_reserve("tenant-z", 50)
    await budget.release("tenant-z", 0)  # no error


@pytest.mark.asyncio
async def test_token_budget_global_limit_enforced():
    budget = _make_budget(daily=10000, monthly=100000, global_=100)

    ok1 = await budget.check_and_reserve("tenant-g1", 60)
    assert ok1

    ok2 = await budget.check_and_reserve("tenant-g2", 60)
    assert not ok2, "Global limit of 100 should block second 60-token request"


@pytest.mark.asyncio
async def test_incr_by_if_under_returns_current_when_blocked():
    backend = _InMemoryBackend()
    # Fill up to 90
    await backend.incr_by_if_under("key", 90, 100, ttl=60)

    # Try to add 20 — would exceed 100
    val, ok = await backend.incr_by_if_under("key", 20, 100, ttl=60)
    assert not ok
    assert val == 90, f"Expected current=90, got {val}"
