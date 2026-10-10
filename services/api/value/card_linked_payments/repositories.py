"""Card-linked payment rail observability — durable, tenant-scoped stores.

Mirrors the payment-rails repository pattern (shared durable-store
abstraction, tenant-prefixed keys, idempotent on (tenant_id,
idempotency_key)). Five stores:

- ``card_linked_flows``           normalized CardLinkedFlowObserved facts
- ``card_linked_benchmarks``      PaymentScan benchmark observations
- ``card_linked_provider_health`` one row per (tenant, source)
- ``card_linked_reconciliation``  cross-source match records
- ``card_linked_audit``           blocked-PII attempts, region/consent
                                  suppressions, basis-mislabel warnings

No store ever holds PAN/CVV/KYC/bank data — ingestion rejects those
fields before anything reaches a repository.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.store import get_store

from datetime import datetime, timezone

logger = get_logger("aether.card_linked.repositories")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CardLinkedFlowRepository:
    """CardLinkedFlowObserved facts, idempotent on (tenant_id, idempotency_key)."""

    def __init__(self) -> None:
        self._store = get_store("card_linked_flows")

    @staticmethod
    def _key(tenant_id: str, flow_id: str) -> str:
        return f"{tenant_id}:{flow_id}"

    async def find_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> Optional[dict]:
        records = await self._store.find(tenant_id=tenant_id, idempotency_key=idempotency_key)
        return records[0] if records else None

    async def get(self, tenant_id: str, flow_id: str) -> Optional[dict]:
        return await self._store.get(self._key(tenant_id, flow_id))

    async def insert_idempotent(self, tenant_id: str, record: dict) -> tuple[dict, str]:
        """Returns (record, disposition) — disposition ``created`` | ``duplicate``."""
        existing = await self.find_by_idempotency_key(tenant_id, record["idempotency_key"])
        if existing is not None:
            metrics.increment("card_linked_flows_upserted_total",
                              labels={"source": record.get("source", "unknown"), "disposition": "duplicate"})
            return existing, "duplicate"
        record.setdefault("created_at", utc_now_iso())
        record["updated_at"] = utc_now_iso()
        await self._store.set(self._key(tenant_id, record["id"]), record)
        metrics.increment("card_linked_flows_upserted_total",
                          labels={"source": record.get("source", "unknown"), "disposition": "created"})
        return record, "created"

    async def save(self, tenant_id: str, record: dict) -> dict:
        record["updated_at"] = utc_now_iso()
        await self._store.set(self._key(tenant_id, record["id"]), record)
        return record

    async def list_for_tenant(self, tenant_id: str, limit: int = 500, **filters: Any) -> list[dict]:
        records = await self._store.find(tenant_id=tenant_id, **{k: v for k, v in filters.items() if v is not None})
        records.sort(key=lambda r: r.get("occurred_at") or "", reverse=True)
        return records[:limit]


class CardBenchmarkRepository:
    """PaymentScan benchmark observations — never user-level truth."""

    def __init__(self) -> None:
        self._store = get_store("card_linked_benchmarks")

    async def upsert(self, tenant_id: str, record: dict) -> dict:
        key = f"{tenant_id}:{record['idempotency_key']}"
        record["updated_at"] = utc_now_iso()
        await self._store.set(key, record)
        return record

    async def list_for_tenant(self, tenant_id: str, limit: int = 500, **filters: Any) -> list[dict]:
        records = await self._store.find(tenant_id=tenant_id, **{k: v for k, v in filters.items() if v is not None})
        records.sort(key=lambda r: r.get("observed_at") or "", reverse=True)
        return records[:limit]


class CardProviderHealthRepository:
    def __init__(self) -> None:
        self._store = get_store("card_linked_provider_health")

    async def record_event(self, tenant_id: str, source: str, *, error: bool = False) -> dict:
        key = f"{tenant_id}:{source}"
        record = await self._store.get(key) or {
            "tenant_id": tenant_id, "source": source,
            "last_event_at": None, "last_sync_at": None,
            "event_count_24h": 0, "error_count_24h": 0, "status": "unknown",
        }
        record["last_event_at"] = utc_now_iso()
        record["event_count_24h"] = int(record.get("event_count_24h", 0)) + 1
        if error:
            record["error_count_24h"] = int(record.get("error_count_24h", 0)) + 1
        record["status"] = "degraded" if error else "healthy"
        await self._store.set(key, record)
        return record

    async def record_sync(self, tenant_id: str, source: str) -> dict:
        key = f"{tenant_id}:{source}"
        record = await self._store.get(key) or {
            "tenant_id": tenant_id, "source": source,
            "last_event_at": None, "last_sync_at": None,
            "event_count_24h": 0, "error_count_24h": 0, "status": "unknown",
        }
        record["last_sync_at"] = utc_now_iso()
        record["status"] = "healthy"
        await self._store.set(key, record)
        return record

    async def list_for_tenant(self, tenant_id: str) -> list[dict]:
        return await self._store.find(tenant_id=tenant_id)


class CardReconciliationRepository:
    def __init__(self) -> None:
        self._store = get_store("card_linked_reconciliation")

    async def save(self, tenant_id: str, record: dict) -> dict:
        record["updated_at"] = utc_now_iso()
        await self._store.set(f"{tenant_id}:{record['reconciliation_id']}", record)
        return record

    async def list_for_tenant(self, tenant_id: str, limit: int = 500, **filters: Any) -> list[dict]:
        records = await self._store.find(tenant_id=tenant_id, **{k: v for k, v in filters.items() if v is not None})
        return records[:limit]


class CardLinkedAuditRepository:
    """Audit trail: blocked-PII attempts, suppressions, basis warnings."""

    def __init__(self) -> None:
        self._store = get_store("card_linked_audit")

    async def record(self, tenant_id: str, kind: str, detail: dict[str, Any]) -> dict:
        ts = utc_now_iso()
        record = {
            "id": f"{tenant_id}:{kind}:{ts}",
            "tenant_id": tenant_id,
            "kind": kind,  # blocked_pii | region_suppressed | consent_suppressed | basis_warning
            "detail": detail,
            "created_at": ts,
        }
        await self._store.set(record["id"], record)
        metrics.increment("card_linked_audit_total", labels={"kind": kind})
        return record

    async def list_for_tenant(self, tenant_id: str, kind: str | None = None, limit: int = 500) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if kind:
            filters["kind"] = kind
        records = await self._store.find(**filters)
        records.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return records[:limit]


class CardLinkedRepositories:
    def __init__(self) -> None:
        self.flows = CardLinkedFlowRepository()
        self.benchmarks = CardBenchmarkRepository()
        self.provider_health = CardProviderHealthRepository()
        self.reconciliation = CardReconciliationRepository()
        self.audit = CardLinkedAuditRepository()


_repositories: CardLinkedRepositories | None = None


def get_card_linked_repositories() -> CardLinkedRepositories:
    global _repositories
    if _repositories is None:
        _repositories = CardLinkedRepositories()
    return _repositories


def reset_card_linked_repositories() -> None:
    """Test helper — drop the singleton so a fresh store binding is created."""
    global _repositories
    _repositories = None
