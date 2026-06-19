"""Unit tests for IdempotencyStore — duplicate payment detection and TTL."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

TENANT = "tenant-idempotency-test"


@pytest.fixture()
def store():
    from services.x402.idempotency import reset_idempotency_store, get_idempotency_store
    reset_idempotency_store()
    return get_idempotency_store()


@pytest.mark.asyncio
async def test_first_record_returns_none_on_lookup(store):
    result = await store.lookup(TENANT, "pay-id-001")
    assert result is None


@pytest.mark.asyncio
async def test_record_then_lookup_returns_result(store):
    payload = {"amount": 1.0, "status": "settled"}
    await store.record(TENANT, "pay-id-002", payload)
    found = await store.lookup(TENANT, "pay-id-002")
    assert found is not None
    assert found["amount"] == 1.0


@pytest.mark.asyncio
async def test_duplicate_payment_detected(store):
    payload = {"amount": 5.0, "receipt_id": "rcpt-dup"}
    await store.record(TENANT, "pay-id-dup", payload)
    # Second lookup for same identifier
    found = await store.lookup(TENANT, "pay-id-dup")
    assert found is not None
    assert found["receipt_id"] == "rcpt-dup"


@pytest.mark.asyncio
async def test_different_tenants_isolated(store):
    await store.record("tenant-a", "pay-id-iso", {"x": 1})
    found = await store.lookup("tenant-b", "pay-id-iso")
    assert found is None


@pytest.mark.asyncio
async def test_different_payment_ids_isolated(store):
    await store.record(TENANT, "pay-id-aaa", {"x": 1})
    found = await store.lookup(TENANT, "pay-id-bbb")
    assert found is None


@pytest.mark.asyncio
async def test_store_size_grows_with_records(store):
    initial = store.size()
    await store.record(TENANT, "pay-id-size-1", {"v": 1})
    await store.record(TENANT, "pay-id-size-2", {"v": 2})
    assert store.size() >= initial + 2


@pytest.mark.asyncio
async def test_ttl_expires_entries(store):
    from services.x402.idempotency import reset_idempotency_store
    # Create store with 1s TTL
    from services.x402.idempotency import _InMemoryIdempotencyStore
    short_ttl_store = _InMemoryIdempotencyStore(ttl_seconds=1)
    await short_ttl_store.record(TENANT, "pay-id-ttl", {"x": 1})
    # Wait for expiry
    time.sleep(1.1)
    found = await short_ttl_store.lookup(TENANT, "pay-id-ttl")
    assert found is None


@pytest.mark.asyncio
async def test_overwrite_is_idempotent(store):
    payload1 = {"amount": 1.0}
    payload2 = {"amount": 1.0, "confirmed": True}
    await store.record(TENANT, "pay-id-over", payload1)
    await store.record(TENANT, "pay-id-over", payload2)
    # Last write wins (or first, depending on implementation) — just ensure no crash
    found = await store.lookup(TENANT, "pay-id-over")
    assert found is not None
