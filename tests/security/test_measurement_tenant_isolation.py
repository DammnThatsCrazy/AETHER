"""Security tests — cross-tenant isolation in the measurement pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

from datetime import datetime, timezone
from uuid import uuid4


def _ts():
    return datetime.now(timezone.utc).isoformat()


TENANT_A = "tenant-iso-A"
TENANT_B = "tenant-iso-B"
PROFILE_A = "profile-A-001"
PROFILE_B = "profile-B-001"


class TestTouchpointTenantIsolation:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.touchpoint_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_list_by_profile_scoped_to_tenant(self):
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        tp_a = {
            "tenant_id": TENANT_A, "profile_id": PROFILE_A,
            "touchpoint_type": "click", "occurred_at": _ts(),
            "idempotency_key": f"tp-a-{uuid4()}",
        }
        tp_b = {
            "tenant_id": TENANT_B, "profile_id": PROFILE_A,
            "touchpoint_type": "click", "occurred_at": _ts(),
            "idempotency_key": f"tp-b-{uuid4()}",
        }
        await repo.upsert(tp_a)
        await repo.upsert(tp_b)
        results = await repo.list_by_profile(TENANT_A, PROFILE_A)
        assert all(r.get("tenant_id") == TENANT_A for r in results), (
            "list_by_profile must not return rows from another tenant"
        )

    @pytest.mark.asyncio
    async def test_get_does_not_leak_cross_tenant(self):
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        shared_id = str(uuid4())
        tp_a = {
            "touchpoint_id": shared_id,
            "tenant_id": TENANT_A, "profile_id": PROFILE_A,
            "touchpoint_type": "click", "occurred_at": _ts(),
            "idempotency_key": f"get-a-{uuid4()}",
        }
        await repo.upsert(tp_a)
        # Attempt to fetch tenant-A's touchpoint as tenant-B
        result = await repo.get(TENANT_B, shared_id)
        assert result is None, "get() must return None when tenant does not match"

    @pytest.mark.asyncio
    async def test_tombstone_scoped_to_tenant(self):
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository, _local_store
        repo = TouchpointRepository()
        key_a = f"iso-tp-a-{uuid4()}"
        key_b = f"iso-tp-b-{uuid4()}"
        tp_a = {"tenant_id": TENANT_A, "profile_id": PROFILE_A, "touchpoint_type": "click",
                "occurred_at": _ts(), "idempotency_key": key_a}
        tp_b = {"tenant_id": TENANT_B, "profile_id": PROFILE_A, "touchpoint_type": "click",
                "occurred_at": _ts(), "idempotency_key": key_b}
        await repo.upsert(tp_a)
        await repo.upsert(tp_b)
        await repo.tombstone_for_profile(TENANT_A, PROFILE_A)
        row_b = _local_store.get(key_b)
        if row_b:
            assert row_b.get("privacy_class") != "deleted", (
                "Tombstone for tenant-A must not affect tenant-B touchpoints"
            )


class TestConversionTenantIsolation:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.conversion_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_get_conversion_scoped_to_tenant(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()
        conv_id = str(uuid4())
        row = {
            "conversion_id": conv_id,
            "tenant_id": TENANT_A,
            "conversion_type": "purchase",
            "currency": "USD",
            "occurred_at": _ts(),
            "observed_at": _ts(),
            "deduplication_key": f"dedup-{uuid4()}",
        }
        await repo.upsert(row)
        result = await repo.get(TENANT_B, conv_id)
        assert result is None, "get() must return None when tenant does not match"

    @pytest.mark.asyncio
    async def test_list_by_profile_scoped_to_tenant(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()
        for tenant in (TENANT_A, TENANT_B):
            await repo.upsert({
                "tenant_id": tenant,
                "profile_id": PROFILE_A,
                "conversion_type": "purchase",
                "currency": "USD",
                "occurred_at": _ts(),
                "observed_at": _ts(),
                "deduplication_key": f"iso-{tenant}-{uuid4()}",
            })
        results = await repo.list_by_profile(TENANT_A, PROFILE_A)
        assert all(r.get("tenant_id") == TENANT_A for r in results), (
            "list_by_profile must not return conversions from another tenant"
        )

    @pytest.mark.asyncio
    async def test_tombstone_does_not_cross_tenant(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository, _local_store
        repo = ConversionRepository()
        key_a = f"tomb-a-{uuid4()}"
        key_b = f"tomb-b-{uuid4()}"
        await repo.upsert({"tenant_id": TENANT_A, "profile_id": PROFILE_A,
                           "conversion_type": "purchase", "currency": "USD",
                           "occurred_at": _ts(), "observed_at": _ts(),
                           "deduplication_key": key_a, "attribution_eligible": True})
        await repo.upsert({"tenant_id": TENANT_B, "profile_id": PROFILE_A,
                           "conversion_type": "purchase", "currency": "USD",
                           "occurred_at": _ts(), "observed_at": _ts(),
                           "deduplication_key": key_b, "attribution_eligible": True})
        await repo.tombstone_for_profile(TENANT_A, PROFILE_A)
        row_b = _local_store.get(key_b)
        if row_b:
            assert row_b.get("attribution_eligible") is not False, (
                "Tombstone for tenant-A must not affect tenant-B conversions"
            )


class TestSpendTenantIsolation:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.spend_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_list_by_campaign_scoped_to_tenant(self):
        from services.measurement.repositories.spend_repo import SpendRepository
        repo = SpendRepository()
        for tenant in (TENANT_A, TENANT_B):
            await repo.upsert({
                "tenant_id": tenant,
                "campaign_id": "campaign-shared",
                "billing_currency": "USD",
                "period_start": _ts(),
                "period_end": _ts(),
                "idempotency_key": f"spend-{tenant}-{uuid4()}",
            })
        results = await repo.list_by_campaign(TENANT_A, "campaign-shared")
        assert all(r.get("tenant_id") == TENANT_A for r in results), (
            "list_by_campaign must not return spend records from another tenant"
        )
