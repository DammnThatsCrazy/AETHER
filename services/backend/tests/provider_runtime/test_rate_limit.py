"""Tests for the per-provider rate-limit coordinator."""

from __future__ import annotations

import pytest

from services.provider_runtime.rate_limit import RateLimitCoordinator
from shared.integration_contracts.results import RateLimitInfo


@pytest.mark.asyncio
async def test_on_rate_limited_records_signal():
    coordinator = RateLimitCoordinator()
    assert coordinator.signal_count() == 0

    info = RateLimitInfo(
        limit=10, remaining=0, reset_epoch_ms=1_700_000_000_000, retry_after_ms=3000
    )
    await coordinator.on_rate_limited(
        tenant_id="tenant-1", identity_key="shopify.orders.catalog", info=info
    )

    assert coordinator.signal_count() == 1
    signal = coordinator._signals[0]
    assert signal["tenant_id"] == "tenant-1"
    assert signal["identity_key"] == "shopify.orders.catalog"
    assert signal["info"]["retry_after_ms"] == 3000


@pytest.mark.asyncio
async def test_on_rate_limited_accepts_missing_info():
    coordinator = RateLimitCoordinator()
    await coordinator.on_rate_limited(
        tenant_id="tenant-1", identity_key="shopify.orders.catalog", info=None
    )
    assert coordinator.signal_count() == 1
    assert coordinator._signals[0]["info"] is None


def test_retry_after_ms_returns_int_when_set():
    coordinator = RateLimitCoordinator()
    assert coordinator.retry_after_ms(RateLimitInfo(retry_after_ms=500)) == 500


def test_retry_after_ms_zero_when_unset():
    coordinator = RateLimitCoordinator()
    assert coordinator.retry_after_ms(None) == 0
    assert coordinator.retry_after_ms(RateLimitInfo()) == 0
    assert coordinator.retry_after_ms(RateLimitInfo(retry_after_ms=0)) == 0
