"""Tests for the raw provider record store (raw-before-canonical Bronze)."""

from __future__ import annotations

import pytest

from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from shared.integration_contracts.events import make_raw_record

from services.provider_runtime.raw_store import RawProviderRecordStore


@pytest.fixture
def store() -> RawProviderRecordStore:
    reset_in_memory_stores()
    return RawProviderRecordStore(repository=BronzeRepository("test_provider_records"))


def _record(*, tenant_id: str = "tenant-1", record_id: str = "ord_123", **overrides):
    return make_raw_record(
        provider_identity="shopify.orders.catalog",
        provider_record_id=record_id,
        provider_record_type=overrides.pop("provider_record_type", "order"),
        payload={"order_id": record_id, "total": "12.50"},
        tenant_id=tenant_id,
        **overrides,
    )


@pytest.mark.asyncio
async def test_ingest_marks_new_records(store: RawProviderRecordStore):
    record = _record()
    outcomes = await store.ingest([record])
    assert outcomes == [(record, True)]


@pytest.mark.asyncio
async def test_ingest_is_idempotent_on_dedup_key(store: RawProviderRecordStore):
    record = _record()
    first = await store.ingest([record])
    second = await store.ingest([record])
    assert first == [(record, True)]
    assert second == [(record, False)]  # duplicate — not re-inserted


@pytest.mark.asyncio
async def test_ingest_respects_tenant_scoping(store: RawProviderRecordStore):
    r1 = _record(tenant_id="tenant-1", record_id="ord_1")
    r2 = _record(tenant_id="tenant-2", record_id="ord_1")
    (out1,), (out2,) = (await store.ingest([r1])), (await store.ingest([r2]))
    assert out1[1] is True
    assert out2[1] is True  # same provider_record_id, different tenant -> new


@pytest.mark.asyncio
async def test_count_without_record_type(store: RawProviderRecordStore):
    await store.ingest([_record(record_id="ord_1"), _record(record_id="ord_2")])
    count = await store.count(tenant_id="tenant-1", provider_identity="shopify.orders.catalog")
    assert count == 2


@pytest.mark.asyncio
async def test_count_with_record_type(store: RawProviderRecordStore):
    order = _record(record_id="ord_1", provider_record_type="order")
    refund = _record(record_id="ref_1", provider_record_type="refund")
    await store.ingest([order, refund])

    orders = await store.count(
        tenant_id="tenant-1",
        provider_identity="shopify.orders.catalog",
        provider_record_type="order",
    )
    refunds = await store.count(
        tenant_id="tenant-1",
        provider_identity="shopify.orders.catalog",
        provider_record_type="refund",
    )
    assert orders == 1
    assert refunds == 1


@pytest.mark.asyncio
async def test_count_scoped_to_tenant(store: RawProviderRecordStore):
    await store.ingest([_record(tenant_id="tenant-1"), _record(tenant_id="tenant-2")])
    count = await store.count(tenant_id="tenant-1", provider_identity="shopify.orders.catalog")
    assert count == 1


@pytest.mark.asyncio
async def test_ingest_uses_envelope_schema_version(store: RawProviderRecordStore):
    """Bronze schema_version = the record's envelope schema_version ("1"),
    NOT payload_schema_version — so the Bronze dedup key matches
    RawProviderRecord.idempotency_key exactly."""
    record = _record(record_id="ord_1")
    await store.ingest([record])
    rows = await BronzeRepository("test_provider_records").find_many(limit=10)
    assert len(rows) == 1
    assert rows[0]["schema_version"] == "1"
    # A payload-schema bump must NOT create a new Bronze row for the same
    # provider_record_id (idempotency tracks the envelope, not the payload tag).
    bumped = _record(record_id="ord_1", payload_schema_version="2025-01")
    (_, was_new), = await store.ingest([bumped])
    assert was_new is False


@pytest.mark.asyncio
async def test_tenant_id_override(store: RawProviderRecordStore):
    record = _record(tenant_id="tenant-1")
    await store.ingest([record], tenant_id="tenant-9")
    # Stored under the override tenant, not the record's own tenant_id.
    count = await store.count(tenant_id="tenant-9", provider_identity="shopify.orders.catalog")
    assert count == 1
    other = await store.count(tenant_id="tenant-1", provider_identity="shopify.orders.catalog")
    assert other == 0
