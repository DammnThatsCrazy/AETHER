"""Repositories for decision and outcome intelligence records."""
from __future__ import annotations

import asyncio
import json

from repositories.repos import BaseRepository
from shared.common.common import utc_now


class RecommendationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("recommendations")

    async def list_for_tenant(self, tenant_id: str, limit: int = 50, entity_id: str | None = None) -> list[dict]:
        filters = {"tenant_id": tenant_id}
        if entity_id:
            filters["entity_id"] = entity_id
        return await self.find_many(filters=filters, limit=limit, sort_by="created_at", sort_order="desc")


class DecisionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("decision_records")


class ActionFeedbackRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("action_feedback")


class OutcomeRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("outcome_observations")

    async def list_for_tenant(self, tenant_id: str, limit: int = 50, entity_id: str | None = None) -> list[dict]:
        filters = {"tenant_id": tenant_id}
        if entity_id:
            filters["entity_id"] = entity_id
        return await self.find_many(filters=filters, limit=limit, sort_by="created_at", sort_order="desc")


class PlaybookRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("playbook_definitions")


class PlaybookRunRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("playbook_runs")


class RecommendationFeedbackRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("recommendation_feedback")


class ActionIntegrationConfigRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("action_integration_configs")


class ActionDispatchRepository(BaseRepository):
    _idempotency_lock: asyncio.Lock | None = None
    _idempotency_lock_loop = None

    def __init__(self) -> None:
        super().__init__("action_dispatches")

    @classmethod
    def _lock(cls) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if cls._idempotency_lock is None or cls._idempotency_lock_loop is not loop:
            cls._idempotency_lock = asyncio.Lock()
            cls._idempotency_lock_loop = loop
        return cls._idempotency_lock

    async def reserve(
        self, tenant_id: str, action_id: str, idempotency_key: str, data: dict
    ) -> tuple[dict, bool]:
        """Atomically reserve an action dispatch key within a tenant/action.

        The reservation is durable before any connector call.  PostgreSQL uses
        a unique expression index plus ``ON CONFLICT DO NOTHING``; local mode
        uses the same process-wide lock as its in-memory database.  The bool
        indicates whether this caller created the reservation.
        """
        if not tenant_id or not action_id or not idempotency_key:
            raise ValueError("tenant_id, action_id, and idempotency_key are required")
        pool = await self._ensure_pool()
        if pool is None:
            async with self._lock():
                existing = await self.find_many(
                    {"tenant_id": tenant_id, "action_id": action_id, "idempotency_key": idempotency_key},
                    limit=1,
                )
                if existing:
                    return existing[0], False
                return await self.insert(data["dispatch_id"], dict(data)), True

        await self._ensure_table()
        await pool.execute(
            f"""CREATE UNIQUE INDEX IF NOT EXISTS uq_{self.table_name}_tenant_action_key
                ON {self.table_name} (tenant_id, (data->>'action_id'), (data->>'idempotency_key'))
                WHERE (data->>'idempotency_key') IS NOT NULL"""
        )
        now = utc_now().isoformat()
        row_data = dict(data)
        row_data["id"] = row_data["dispatch_id"]
        row_data["created_at"] = now
        row_data["updated_at"] = now
        inserted = await pool.fetchrow(
            f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                ON CONFLICT DO NOTHING
                RETURNING data""",
            row_data["dispatch_id"], json.dumps(row_data, default=str), tenant_id,
        )
        if inserted is not None:
            return json.loads(inserted["data"]), True
        existing = await self.find_many(
            {"tenant_id": tenant_id, "action_id": action_id, "idempotency_key": idempotency_key},
            limit=1,
        )
        if not existing:
            raise RuntimeError("idempotency reservation conflicted but existing dispatch was not readable")
        return existing[0], False


class ActionDeliveryReceiptRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("action_delivery_receipts")


class RevenueMeteringEventRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("revenue_metering_events")


class AuditExportRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("audit_exports_intelligence")

class CustomerSuccessAccountRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("customer_success_accounts")

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)


class CustomerSuccessTriggerRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("customer_success_triggers")

    async def open_for_tenant_type(self, tenant_id: str, trigger_type: str) -> list[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id, "trigger_type": trigger_type}, limit=100)
        return [row for row in rows if row.get("status") in (None, "open", "in_progress")]


class ExpansionOpportunityRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("customer_expansion_opportunities")


class RenewalRiskRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("customer_renewal_risks")


class ExecutiveBusinessReviewRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("executive_business_reviews")


class AccountPlanRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("account_plans")
