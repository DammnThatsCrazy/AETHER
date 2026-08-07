"""Billing regression: bounded reads over usage events must DISCLOSE truncation
rather than silently under-counting a billing period."""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.billing.revops import UsageMeteringEventRepository


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _seed(repo, n):
    for i in range(n):
        await repo.insert(
            f"evt_{i}",
            {
                "tenant_id": "t1",
                "event_type": "api_call",
                "quantity": 1,
                "billable": True,
                "occurred_at": "2026-01-15T00:00:00Z",
            },
        )


async def test_truncation_disclosed_when_bound_hit():
    repo = UsageMeteringEventRepository()
    await _seed(repo, 3)
    rows, truncated = await repo.list_for_tenant_period(
        "t1", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", limit=2
    )
    assert truncated is True  # 3 events, bound 2 -> population is truncated


async def test_no_truncation_within_bound():
    repo = UsageMeteringEventRepository()
    await _seed(repo, 2)
    rows, truncated = await repo.list_for_tenant_period(
        "t1", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", limit=100
    )
    assert truncated is False
    assert len(rows) == 2
