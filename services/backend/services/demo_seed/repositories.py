from __future__ import annotations

import os
from typing import Any, Optional

from repositories.repos import (
    AdminRepository,
    AlertRepository,
    BaseRepository,
    CampaignRepository,
    EconomicResourceRepository,
    EntityRepository,
    PaymentIntentRepository,
    ProvidersRepository,
    SettlementEventRepository,
    UserRepository,
    InvestigationRepository,
)
from repositories.commerce_repos import (
    ApprovalsRepository,
    EntitlementsRepository,
    FacilitatorsRepository,
    PoliciesRepository,
    ResourcesRepository,
    SettlementsRepository,
)
from repositories.imports_repo import ImportsRepository
from repositories.continuation_repo import ContinuationRepository, get_continuation_repository
from services.data_quality.repositories import IntelligenceQualityRepository
from services.kyber.ops.repository import ExceptionRepository, IncidentRepository
from services.metering_evidence.service import MeteringEvidenceRepository
from services.notification_intelligence.inbox import NotificationInboxRepository
from shared.common.common import utc_now
from shared.store import DurableStore, InMemoryStore, get_store

from .errors import SeedSafetyError


def domain_repositories() -> dict[str, Any]:
    """Canonical repositories used by the normal API read paths.

    Every entry satisfies the demo-seed contract (``find_by_id`` / ``find_many`` /
    ``count`` / ``insert`` / ``update`` / ``delete``). Most are BaseRepository
    tables; ``runs`` and ``reviews`` adapt the DurableStore-backed
    ``AgentRuntimeRepository`` stores so seeded records are visible to the SAME
    store the agent runtime reads. ``continuations`` is deliberately absent: its
    repository is tenant-scope-scoped and cannot resolve a scope from an id
    alone — the seed service resolves it per-tenant (see ``service.py``).
    """
    imports = ImportsRepository()
    return {
        "tenants": AdminRepository(),
        "users": UserRepository(),
        "entities": EntityRepository(),
        "campaigns": CampaignRepository(),
        "economic_resources": EconomicResourceRepository(),
        "payment_intents": PaymentIntentRepository(),
        "settlement_events": SettlementEventRepository(),
        "alerts": AlertRepository(),
        "providers": ProvidersRepository(),
        "metering_evidence": MeteringEvidenceRepository(),
        "data_quality_scores": IntelligenceQualityRepository(),
        "import_sessions": imports.sessions,
        "investigations": InvestigationRepository(),
        "commerce_resources": ResourcesRepository(),
        "commerce_policies": PoliciesRepository(),
        "commerce_facilitators": FacilitatorsRepository(),
        "commerce_approvals": ApprovalsRepository(),
        "commerce_settlements": SettlementsRepository(),
        "commerce_entitlements": EntitlementsRepository(),
        "notifications": NotificationInboxRepository(),
        "exceptions": ExceptionRepository(),
        "incidents": IncidentRepository(),
        "runs": DurableStoreSeedRepository("agent_worker_runs", "run_id"),
        "reviews": DurableStoreSeedRepository("agent_review_batches", "batch_id"),
    }


class DurableStoreSeedRepository:
    """BaseRepository-compatible adapter over a named DurableStore.

    ``AgentRuntimeRepository`` reads and writes agent runs / review batches
    through ``get_store(name)`` (a process-wide singleton). Seeding through this
    adapter writes to that SAME store, so a seeded run or review batch is visible
    to the real API read paths — not to a parallel JSONB table.

    Process-local guard (M8-C1): without Redis configured the resolved store is
    an ``InMemoryStore``, which is a per-process singleton. A seed CLI run as a
    SEPARATE process from the backend (the design-partner ``make demo-seed``
    host-CLI flow) would write runs/reviews into a store the backend API never
    reads — a silent parallel copy. The guard surfaces this as a
    ``SeedSafetyError`` unless an explicit ``AETHER_ALLOW_INMEMORY_SEED=1``
    override is set (test/dev use).
    """

    def __init__(self, store_name: str, identity_field: str) -> None:
        self.store_name = store_name
        self.identity_field = identity_field
        self._store: DurableStore = get_store(store_name)
        self.store_kind = "in_memory" if isinstance(self._store, InMemoryStore) else "durable"

    @property
    def is_process_local(self) -> bool:
        """True when the underlying store is process-local (InMemoryStore)."""
        return self.store_kind == "in_memory"

    def _assert_writable(self) -> None:
        """Refuse writes into a process-local store (M8-C1).

        Without Redis configured the resolved store is an ``InMemoryStore`` — a
        per-process singleton. A seed CLI run as a SEPARATE process from the
        backend (the design-partner ``make demo-seed`` host flow) would write
        runs/reviews into a store the backend API never reads and that vanishes
        on exit — a silent parallel copy. Fail closed unless the operator
        explicitly opts into the in-memory path with
        ``AETHER_ALLOW_INMEMORY_SEED=1`` (test/dev in-process use).
        """
        if self.is_process_local and os.getenv("AETHER_ALLOW_INMEMORY_SEED", "") != "1":
            raise SeedSafetyError(
                f"refusing to write durable domain {self.store_name!r} into a "
                "process-local in-memory store — records written here are "
                "invisible to the backend API in a separate process and are lost "
                "on exit. Run the seed inside the backend container/process (or "
                "configure REDIS_HOST/REDIS_URL so the DurableStore is shared), or "
                "set AETHER_ALLOW_INMEMORY_SEED=1 to explicitly acknowledge the "
                "in-memory path."
            )

    async def find_by_id(self, record_id: str) -> Optional[dict]:
        return await self._store.get(record_id)

    async def find_many(
        self,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[dict]:
        rows = await self._store.find(**(filters or {}))
        rows.sort(key=lambda row: str(row.get(sort_by, "")), reverse=sort_order == "desc")
        return rows[offset: offset + limit]

    async def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        return await self._store.count(**(filters or {}))

    async def insert(self, record_id: str, data: dict) -> dict:
        self._assert_writable()
        now = utc_now().isoformat()
        payload = dict(data)
        payload["id"] = record_id
        payload[self.identity_field] = record_id
        payload.setdefault("created_at", now)
        payload.setdefault("updated_at", now)
        await self._store.set(record_id, payload)
        return payload

    async def update(self, record_id: str, data: dict) -> dict:
        self._assert_writable()
        existing = await self._store.get(record_id)
        if existing is None:
            raise KeyError(f"{self.store_name} record {record_id!r} not found")
        existing.update(data)
        existing["updated_at"] = utc_now().isoformat()
        await self._store.set(record_id, existing)
        return existing

    async def delete(self, record_id: str) -> bool:
        return await self._store.delete(record_id)


class ContinuationScopedSeedRepository:
    """Scope-scoped adapter over the canonical continuation repository.

    The continuation plane isolates by ``tenant_scope`` (``t:{tenant_id}``) and
    only exposes its CAS/idempotency-shaped interface — not BaseRepository's
    ``find_by_id`` / ``insert`` / ``delete``. The demo-seed machinery resolves
    this adapter with the tenant bound (``service._resolve_repository``) so
    seeding reuses the canonical create path (scope + idempotency) instead of
    writing past it. Only the methods the seed flow calls are implemented.
    """

    def __init__(self, tenant_scope: str, repo: ContinuationRepository | None = None) -> None:
        self.tenant_scope = tenant_scope
        self._repo = repo or get_continuation_repository()

    async def find_by_id(self, record_id: str) -> Optional[dict]:
        return await self._repo.get_scoped(self.tenant_scope, record_id)

    async def insert(self, record_id: str, payload: dict) -> dict:
        return await self._repo.create(
            tenant_scope=self.tenant_scope,
            continuation_id=record_id,
            principal_id=str(payload.get("principal_id") or ""),
            app_kind=str(payload.get("app_kind") or ""),
            source_client=str(payload.get("source_client") or ""),
            surface=str(payload.get("surface") or ""),
            sensitivity=str(payload.get("sensitivity") or "standard"),
            freshness=payload.get("freshness"),
            context=dict(payload),
            idempotency_key=payload.get("_seed_idempotency_key"),
            expires_at=payload.get("expires_at"),
        )

    async def delete(self, record_id: str) -> bool:
        return await self._repo.delete_scoped(self.tenant_scope, record_id)


class SeedRunRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("demo_seed_runs")


class SeedOwnershipRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("demo_seed_record_ownership")


class SeedResetAuditRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("demo_seed_reset_audit")
