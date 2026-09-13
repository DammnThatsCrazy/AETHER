"""Durable, tenant-scoped stores for Cluster Targeting Intelligence.

All keys are tenant-prefixed; cross-tenant reads are NotFound. Eligibility
snapshots are idempotent on (tenant, intent, asOf): recomputing the same
asOf deterministically replaces the prior snapshot rather than duplicating.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.common.common import NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

from services.targeting_intelligence.models import new_id, utc_now_iso

logger = get_logger("aether.targeting.repository")


class _TenantStore:
    """Thin tenant-scoped wrapper shared by all targeting stores."""

    def __init__(self, store_name: str, id_field: str):
        self._store = get_store(store_name)
        self._id_field = id_field

    def _key(self, tenant_id: str, record_id: str) -> str:
        return f"{tenant_id}:{record_id}"

    async def save(self, tenant_id: str, record: dict) -> dict:
        record["tenantId"] = tenant_id
        record.setdefault("updatedAt", utc_now_iso())
        await self._store.set(self._key(tenant_id, record[self._id_field]), record)
        return record

    async def get_optional(self, tenant_id: str, record_id: str) -> Optional[dict]:
        return await self._store.get(self._key(tenant_id, record_id))

    async def get(self, tenant_id: str, record_id: str) -> dict:
        record = await self.get_optional(tenant_id, record_id)
        if record is None:
            raise NotFoundError("Targeting record")
        return record

    async def list_for_tenant(self, tenant_id: str, *, limit: int = 100, **filters) -> list[dict]:
        query: dict[str, Any] = {"tenantId": tenant_id}
        query.update({k: v for k, v in filters.items() if v is not None})
        records = await self._store.find(**query)
        records.sort(
            key=lambda r: r.get("computedAt") or r.get("createdAt") or r.get("asOf") or "",
            reverse=True,
        )
        return records[: max(1, min(limit, 500))]

    async def list_all(self) -> list[dict]:
        """Cross-tenant listing — Kyber operator aggregates only."""
        return await self._store.find()

    async def delete(self, tenant_id: str, record_id: str) -> bool:
        return await self._store.delete(self._key(tenant_id, record_id))


class EligibilitySnapshotStore(_TenantStore):
    """Snapshots keyed by (tenant, intent, asOf) for recompute idempotency."""

    async def save_snapshot(self, tenant_id: str, record: dict) -> dict:
        existing = await self.find_by_intent_as_of(
            tenant_id, record["targetingIntentId"], record["asOf"]
        )
        if existing is not None:
            # Deterministic replacement: preserve the original snapshot id so
            # references stay stable across recomputes of the same asOf.
            record["snapshotId"] = existing["snapshotId"]
            metrics.increment("targeting_snapshot_recomputed_total")
        return await self.save(tenant_id, record)

    async def find_by_intent_as_of(
        self, tenant_id: str, intent_id: str, as_of: str
    ) -> Optional[dict]:
        matches = await self._store.find(
            tenantId=tenant_id, targetingIntentId=intent_id, asOf=as_of
        )
        return matches[0] if matches else None


class TargetingAuditStore:
    def __init__(self) -> None:
        self._store = get_store("targeting_audit")

    async def record(self, tenant_id: str, action: str, detail: dict | None = None,
                     actor: str = "system") -> dict:
        entry = {
            "id": new_id("aud"),
            "tenantId": tenant_id,
            "action": action,
            "actor": actor,
            "detail": detail or {},
            "occurredAt": utc_now_iso(),
        }
        await self._store.set(f"{tenant_id}:{entry['id']}", entry)
        return entry

    async def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[dict]:
        records = await self._store.find(tenantId=tenant_id)
        records.sort(key=lambda r: r.get("occurredAt") or "", reverse=True)
        return records[:limit]

    async def list_all(self, limit: int = 200) -> list[dict]:
        records = await self._store.find()
        records.sort(key=lambda r: r.get("occurredAt") or "", reverse=True)
        return records[:limit]


class TargetingRepositories:
    def __init__(self) -> None:
        self.intents = _TenantStore("targeting_intents", "id")
        self.snapshots = EligibilitySnapshotStore("targeting_eligibility_snapshots", "snapshotId")
        self.observations = _TenantStore("targeting_observations", "observationId")
        self.outcome_snapshots = _TenantStore("targeting_outcome_snapshots", "snapshotId")
        self.leakage = _TenantStore("targeting_leakage_findings", "findingId")
        self.holdouts = _TenantStore("targeting_holdouts", "holdoutId")
        self.journey_deltas = _TenantStore("targeting_journey_deltas", "deltaId")
        self.exports = _TenantStore("targeting_export_packages", "exportId")
        self.policy_decisions = _TenantStore("targeting_policy_decisions", "id")
        self.audit = TargetingAuditStore()


_repositories: Optional[TargetingRepositories] = None


def get_targeting_repositories() -> TargetingRepositories:
    global _repositories
    if _repositories is None:
        _repositories = TargetingRepositories()
    return _repositories
