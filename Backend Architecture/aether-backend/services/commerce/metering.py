"""
Aether Service — Commerce Metering

Records meter records for challenged / paid / entitled commerce usage so tenant
metering is auditable and reconcilable against silver facts. The metering
service is write-side only: it persists one ``MeterRecord`` per stage and
provides tenant-scoped rollups for diagnostics and the kyber operator pages.

The repository (table ``commerce_metering``) lives here because the commerce
metering store is additive and must not require touching the shared
``repositories.commerce_repos`` module.

Design rules:
- Meter records are immutable facts: once written they are never mutated.
- ``meter_type`` is one of ``challenge_issued`` / ``payment_paid`` /
  ``access_granted`` / ``entitled`` — matching the control-plane lifecycle.
- Rollups are additive; the singleton is safe to share across requests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.logger.logger import get_logger

logger = get_logger("aether.service.commerce.metering")

# Re-home note: the branch modeled meter records with a pydantic
# ``MeterRecord`` in ``services/x402/commerce_models.py``, which main does not
# carry. To keep this additive module self-contained (no main-owned file
# modification required), records are built as plain dicts with the same
# stable field surface (``meter_record_id`` / ``observed_at`` etc.).


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_meter_record(
    *,
    tenant_id: str,
    resource_id: str,
    holder_id: str,
    meter_type: str,
    amount_usd: float,
    chain: Optional[str],
    asset_symbol: Optional[str],
    challenge_id: Optional[str],
    authorization_id: Optional[str],
    entitlement_id: Optional[str],
    metadata: Optional[dict],
) -> dict:
    import uuid

    return {
        "meter_record_id": f"mtr_{uuid.uuid4().hex[:16]}",
        "tenant_id": tenant_id,
        "resource_id": resource_id,
        "holder_id": holder_id,
        "meter_type": meter_type,
        "amount_usd": float(amount_usd or 0.0),
        "chain": chain,
        "asset_symbol": asset_symbol,
        "challenge_id": challenge_id,
        "authorization_id": authorization_id,
        "entitlement_id": entitlement_id,
        "observed_at": _now_iso(),
        "metadata": metadata or {},
    }


class CommerceMeterRepository(BaseRepository):
    """Durable metering store (table ``commerce_metering``)."""

    def __init__(self) -> None:
        super().__init__("commerce_metering")

    async def create(self, tenant_id: str, data: dict) -> dict:
        import uuid
        record_id = f"mtr_{uuid.uuid4().hex[:16]}"
        record = {**data, "id": record_id, "tenant_id": tenant_id}
        return await self.insert(record_id, record)

    async def list_for_tenant(self, tenant_id: str, meter_type: Optional[str] = None, limit: int = 500) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if meter_type:
            filters["meter_type"] = meter_type
        return await self.find_many(filters=filters, limit=limit)


class CommerceMeteringService:
    """Writes and rolls up commerce metering records."""

    def __init__(self, repo: Optional[CommerceMeterRepository] = None) -> None:
        self._repo = repo or CommerceMeterRepository()

    async def record(
        self,
        tenant_id: str,
        meter_type: str,
        *,
        resource_id: str = "",
        holder_id: str = "",
        amount_usd: float = 0.0,
        chain: Optional[str] = None,
        asset_symbol: Optional[str] = None,
        challenge_id: Optional[str] = None,
        authorization_id: Optional[str] = None,
        entitlement_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        if meter_type not in (
            "challenge_issued", "payment_paid", "access_granted", "entitled",
        ):
            raise ValueError(f"unknown meter_type: {meter_type!r}")
        data = _build_meter_record(
            tenant_id=tenant_id,
            resource_id=resource_id,
            holder_id=holder_id,
            meter_type=meter_type,
            amount_usd=amount_usd,
            chain=chain,
            asset_symbol=asset_symbol,
            challenge_id=challenge_id,
            authorization_id=authorization_id,
            entitlement_id=entitlement_id,
            metadata=metadata,
        )
        return await self._repo.create(tenant_id, data)

    async def record_challenge(self, tenant_id: str, *, resource_id: str = "", holder_id: str = "",
                               amount_usd: float = 0.0, chain: Optional[str] = None,
                               asset_symbol: Optional[str] = None, challenge_id: Optional[str] = None,
                               metadata: Optional[dict] = None) -> dict:
        return await self.record(
            tenant_id, "challenge_issued", resource_id=resource_id, holder_id=holder_id,
            amount_usd=amount_usd, chain=chain, asset_symbol=asset_symbol,
            challenge_id=challenge_id, metadata=metadata,
        )

    async def record_payment(self, tenant_id: str, *, resource_id: str = "", holder_id: str = "",
                             amount_usd: float = 0.0, chain: Optional[str] = None,
                             asset_symbol: Optional[str] = None, challenge_id: Optional[str] = None,
                             authorization_id: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
        return await self.record(
            tenant_id, "payment_paid", resource_id=resource_id, holder_id=holder_id,
            amount_usd=amount_usd, chain=chain, asset_symbol=asset_symbol,
            challenge_id=challenge_id, authorization_id=authorization_id, metadata=metadata,
        )

    async def record_access_granted(self, tenant_id: str, *, resource_id: str = "", holder_id: str = "",
                                    amount_usd: float = 0.0, challenge_id: Optional[str] = None,
                                    entitlement_id: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
        return await self.record(
            tenant_id, "access_granted", resource_id=resource_id, holder_id=holder_id,
            amount_usd=amount_usd, challenge_id=challenge_id,
            entitlement_id=entitlement_id, metadata=metadata,
        )

    async def record_entitled(self, tenant_id: str, *, resource_id: str = "", holder_id: str = "",
                              amount_usd: float = 0.0, challenge_id: Optional[str] = None,
                              entitlement_id: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
        return await self.record(
            tenant_id, "entitled", resource_id=resource_id, holder_id=holder_id,
            amount_usd=amount_usd, challenge_id=challenge_id,
            entitlement_id=entitlement_id, metadata=metadata,
        )

    async def summarize(self, tenant_id: str) -> dict:
        """Tenant rollup keyed by meter_type with counts and summed USD."""
        rows = await self._repo.list_for_tenant(tenant_id, limit=10000)
        by_type: dict[str, dict[str, Any]] = {}
        for r in rows:
            t = r.get("meter_type", "unknown")
            agg = by_type.setdefault(t, {"count": 0, "amount_usd": 0.0})
            agg["count"] += 1
            agg["amount_usd"] += float(r.get("amount_usd") or 0.0)
        return {
            "tenant_id": tenant_id,
            "by_type": by_type,
            "total_records": len(rows),
        }


# ── Module-level singleton ──────────────────────────────────────────────

_metering: Optional[CommerceMeteringService] = None


def get_metering_service() -> CommerceMeteringService:
    global _metering
    if _metering is None:
        _metering = CommerceMeteringService()
    return _metering


def reset_metering_service() -> None:
    """Reset the metering service — for tests only."""
    global _metering
    _metering = None


__all__ = [
    "CommerceMeteringService",
    "CommerceMeterRepository",
    "get_metering_service",
    "reset_metering_service",
]
