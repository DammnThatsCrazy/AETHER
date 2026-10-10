"""Tests for the raw provider record store (raw-before-canonical Bronze)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from shared.integration_contracts.events import make_raw_record

from connectors.provider_runtime.raw_store import (
    RawProviderRecordStore,
)
from connectors.provider_runtime.rights_admission import (
    PROVIDER_RAW_RIGHTS_METADATA_KEY,
    ProviderRawRightsDenied,
    ProviderRawRightsEvidence,
    provider_account_source_id,
)


class _TestRightsAdmission:
    """Explicit test grant seam; production defaults use EffectiveRightsResolver."""

    async def admit(self, record):
        return ProviderRawRightsEvidence(
            tenant_id=record.tenant_id,
            source_id=provider_account_source_id(record.connection_id, record.account_id),
            source_grant_ref="drg_test",
            rights_decision_ref=f"rdec_{record.idempotency_key}",
            decision_identity=f"rdid_{record.idempotency_key}",
            policy_version="irrl-2",
            evaluated_at="2026-10-03T00:00:00+00:00",
        )

    @asynccontextmanager
    async def hold_grant(self, record, admission):
        yield

    async def verify_persisted(self, record, *, current_admission):
        assert record.metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY]["source_grant_ref"] == (
            current_admission.source_grant_ref
        )


class _AdmittedBronzeRepository(BronzeRepository):
    """Test seam for rows whose provenance was approved by trusted setup."""

    async def ingest(self, **kwargs):
        kwargs.update(
            provenance_status="valid",
            license_status="public_api",
            terms_status="approved",
        )
        return await super().ingest(**kwargs)


@pytest.fixture
def store() -> RawProviderRecordStore:
    reset_in_memory_stores()
    return RawProviderRecordStore(
        repository=_AdmittedBronzeRepository("test_provider_records"),
        rights_admission=_TestRightsAdmission(),
    )


def _record(*, tenant_id: str = "tenant-1", record_id: str = "ord_123", **overrides):
    return make_raw_record(
        provider_identity="shopify.orders.catalog",
        provider_record_id=record_id,
        provider_record_type=overrides.pop("provider_record_type", "order"),
        payload={"order_id": record_id, "total": "12.50"},
        tenant_id=tenant_id,
        connection_id=overrides.pop("connection_id", "conn-1"),
        account_id=overrides.pop("account_id", "conn-1:shop:test"),
        **overrides,
    )


@pytest.mark.asyncio
async def test_missing_rights_denies_before_full_raw_payload_is_persisted():
    repository = BronzeRepository("test_quarantined_provider_records")
    record = _record(
        record_id="source-pii-canary",
        metadata={"license_status": "public_api", "terms_status": "approved"},
    )
    store = RawProviderRecordStore(repository=repository)

    with pytest.raises(ProviderRawRightsDenied) as excinfo:
        await store.ingest([record])

    assert str(excinfo.value) == "provider raw record has no current tenant rights admission"
    assert "source-pii-canary" not in str(excinfo.value)
    rows = await repository.find_many(
        filters={
            "tenant_id": "tenant-1",
            "provider_record_id": record.bronze_provider_record_id,
        },
        limit=1,
    )
    assert rows == []


@pytest.mark.asyncio
async def test_invalid_checksum_is_rejected_before_full_raw_payload_is_persisted():
    repository = BronzeRepository("test_invalid_checksum_provider_records")
    record = _record(record_id="checksum-canary").model_copy(update={"checksum": "invalid"})
    store = RawProviderRecordStore(
        repository=repository,
        rights_admission=_TestRightsAdmission(),
    )

    with pytest.raises(ValueError, match="checksum is invalid"):
        await store.ingest([record])

    rows = await repository.find_many(filters={"tenant_id": "tenant-1"}, limit=10)
    assert rows == []


@pytest.mark.asyncio
async def test_ingest_marks_new_records(store: RawProviderRecordStore):
    record = _record()
    outcomes = await store.ingest([record])
    assert outcomes[0][1] is True
    assert outcomes[0][0].record_id == record.record_id
    assert outcomes[0][0].metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY]["source_grant_ref"] == (
        "drg_test"
    )


@pytest.mark.asyncio
async def test_ingest_is_idempotent_on_dedup_key(store: RawProviderRecordStore):
    record = _record()
    first = await store.ingest([record])
    second = await store.ingest([record])
    assert first[0][1] is True
    assert second[0][1] is False  # duplicate — not re-inserted
    assert second[0][0].record_id == first[0][0].record_id


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


@pytest.mark.asyncio
async def test_revision_aware_raw_ingest_keeps_distinct_object_states_and_stable_lineage(
    store: RawProviderRecordStore,
):
    common = {
        "schema_version": "2",
        "source_account_key": "gid://shopify/Shop/71",
        "source_account_realm": "live",
        "source_object_type": "order",
        "source_object_id": "gid://shopify/Order/123",
    }
    first = _record(
        record_id="123", source_revision_key="snapshot:2026-01-01:aaa", **common
    )
    second = _record(
        record_id="123", source_revision_key="snapshot:2026-01-02:bbb", **common
    )
    retry = _record(
        record_id="123", source_revision_key="snapshot:2026-01-01:aaa", **common
    )

    (stored_first, new_first), = await store.ingest([first])
    (stored_second, new_second), = await store.ingest([second])
    (stored_retry, new_retry), = await store.ingest([retry])

    assert new_first and new_second and not new_retry
    assert stored_first.record_id != stored_second.record_id
    assert stored_retry.record_id == stored_first.record_id
    assert first.bronze_provider_record_id != second.bronze_provider_record_id
    assert retry.idempotency_key == first.idempotency_key
    assert await store.count(tenant_id="tenant-1", provider_identity="shopify.orders.catalog") == 2


def test_partial_or_unscoped_source_revision_is_rejected():
    with pytest.raises(ValueError, match="source revision requires"):
        _record(record_id="123", source_revision_key="snapshot:revision")
    with pytest.raises(ValueError, match="source revision requires"):
        _record(
            tenant_id="", record_id="123", source_revision_key="snapshot:revision",
            source_account_key="shop-1", source_object_type="order", source_object_id="123",
        )
    with pytest.raises(ValueError, match="live/test realm"):
        _record(
            record_id="123", schema_version="2", source_revision_key="snapshot:revision",
            source_account_key="shop-1", source_object_type="order", source_object_id="123",
        )


def test_raw_revision_realm_separates_live_and_test_objects():
    common = {
        "schema_version": "2",
        "source_account_key": "gid://shopify/Shop/71",
        "source_object_type": "order",
        "source_object_id": "gid://shopify/Order/123",
        "source_revision_key": "snapshot:none:same",
    }
    live = _record(record_id="123", source_account_realm="live", **common)
    test = _record(record_id="123", source_account_realm="test", **common)
    assert live.bronze_provider_record_id != test.bronze_provider_record_id
    assert live.idempotency_key != test.idempotency_key


@pytest.mark.asyncio
async def test_concurrent_v2_unique_conflict_returns_winning_raw_lineage():
    common = {
        "schema_version": "2",
        "source_account_key": "gid://shopify/Shop/71",
        "source_account_realm": "live",
        "source_object_type": "order",
        "source_object_id": "gid://shopify/Order/123",
        "source_revision_key": "snapshot:none:abc",
    }
    winner = _record(record_id="123", **common)
    concurrent_retry = _record(record_id="123", **common)
    rights_admission = _TestRightsAdmission()
    evidence = await rights_admission.admit(winner)
    winner_metadata = dict(winner.metadata or {})
    winner_metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY] = evidence.model_dump(mode="json")
    winner = winner.model_copy(update={"metadata": winner_metadata})

    class UniqueRevisionConflict(Exception):
        constraint_name = "ux_bronze_provider_raw_v2_revision"

    class ConcurrentRepo:
        async def ingest(self, **kwargs):
            raise UniqueRevisionConflict()

        async def find_many(self, *, filters, limit):
            assert filters == {
                "tenant_id": "tenant-1",
                "idempotency_key": concurrent_retry.idempotency_key,
            }
            return [
                {
                    "payload": winner.model_dump(),
                    "provenance_status": "valid",
                    "quarantine_status": "not_quarantined",
                }
            ]

    outcomes = await RawProviderRecordStore(
        repository=ConcurrentRepo(), rights_admission=rights_admission
    ).ingest([concurrent_retry])
    assert outcomes[0][1] is False
    assert outcomes[0][0].record_id == winner.record_id
