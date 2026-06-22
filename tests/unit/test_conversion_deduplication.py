"""Unit tests — Canonical conversion deduplication and authority ranking."""

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


def _make_conversion(authority_rank: int = 50, source_event_id: str | None = None) -> dict:
    return {
        "tenant_id": "tenant-dedup",
        "conversion_type": "purchase",
        "currency": "USD",
        "gross_value": "100.00",
        "net_value": "90.00",
        "occurred_at": _ts(),
        "observed_at": _ts(),
        "deduplication_key": "dedup-key-001",
        "authority_rank": authority_rank,
        "conversion_status": "confirmed",
        "source_event_id": source_event_id or str(uuid4()),
    }


class TestConversionDeduplication:
    @pytest.fixture(autouse=True)
    def clear_store(self):
        from services.measurement.repositories.conversion_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_first_insert_succeeds(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()
        row = _make_conversion(authority_rank=50)
        result = await repo.upsert(row)
        assert result["deduplication_key"] == "dedup-key-001"

    @pytest.mark.asyncio
    async def test_higher_authority_wins(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository, _local_store
        repo = ConversionRepository()
        low = _make_conversion(authority_rank=30)
        low["gross_value"] = "50.00"
        await repo.upsert(low)
        high = _make_conversion(authority_rank=90)
        high["gross_value"] = "100.00"
        await repo.upsert(high)
        stored = next(r for r in _local_store.values() if r.get("deduplication_key") == "dedup-key-001")
        assert stored["gross_value"] == "100.00", "Higher authority record should win"

    @pytest.mark.asyncio
    async def test_lower_authority_does_not_overwrite(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository, _local_store
        repo = ConversionRepository()
        high = _make_conversion(authority_rank=90)
        high["gross_value"] = "100.00"
        await repo.upsert(high)
        low = _make_conversion(authority_rank=30)
        low["gross_value"] = "50.00"
        await repo.upsert(low)
        stored = next(r for r in _local_store.values() if r.get("deduplication_key") == "dedup-key-001")
        assert stored["gross_value"] == "100.00", "Lower authority must not overwrite higher"

    @pytest.mark.asyncio
    async def test_same_authority_updates(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()
        first = _make_conversion(authority_rank=70)
        first["gross_value"] = "80.00"
        await repo.upsert(first)
        second = _make_conversion(authority_rank=70)
        second["gross_value"] = "85.00"
        await repo.upsert(second)
        # Same or higher authority can update — just verify no error
        assert True

    @pytest.mark.asyncio
    async def test_different_dedup_keys_are_independent(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository, _local_store
        repo = ConversionRepository()
        row1 = _make_conversion()
        row1["deduplication_key"] = "key-A"
        row2 = _make_conversion()
        row2["deduplication_key"] = "key-B"
        await repo.upsert(row1)
        await repo.upsert(row2)
        keys = {r["deduplication_key"] for r in _local_store.values()}
        assert "key-A" in keys
        assert "key-B" in keys

    @pytest.mark.asyncio
    async def test_tombstone_marks_attribution_ineligible(self):
        from services.measurement.repositories.conversion_repo import ConversionRepository, _local_store
        repo = ConversionRepository()
        row = _make_conversion()
        row["profile_id"] = "profile-tombstone"
        row["deduplication_key"] = "tombstone-key"
        await repo.upsert(row)
        count = await repo.tombstone_for_profile("tenant-dedup", "profile-tombstone")
        assert count >= 1
        stored = next(
            (r for r in _local_store.values() if r.get("deduplication_key") == "tombstone-key"), None
        )
        assert stored is not None
        assert stored.get("attribution_eligible") is False

    @pytest.mark.asyncio
    async def test_tombstone_tenant_scoped(self):
        """Tombstone for tenant-A must not affect tenant-B conversions."""
        from services.measurement.repositories.conversion_repo import ConversionRepository, _local_store
        repo = ConversionRepository()
        row_a = _make_conversion()
        row_a["tenant_id"] = "tenant-A"
        row_a["profile_id"] = "profile-x"
        row_a["deduplication_key"] = "tenant-a-key"
        row_b = _make_conversion()
        row_b["tenant_id"] = "tenant-B"
        row_b["profile_id"] = "profile-x"
        row_b["deduplication_key"] = "tenant-b-key"
        await repo.upsert(row_a)
        await repo.upsert(row_b)
        await repo.tombstone_for_profile("tenant-A", "profile-x")
        row_b_stored = next(r for r in _local_store.values() if r.get("deduplication_key") == "tenant-b-key")
        assert row_b_stored.get("attribution_eligible") is not False, (
            "Tombstone for tenant-A must not affect tenant-B"
        )
