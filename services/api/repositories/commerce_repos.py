"""
Aether Commerce Repositories — Agentic Commerce Control Plane (L3b+).

Seven Postgres-backed repositories with full tenant isolation, in-memory
fallback for local dev, and shared _IN_MEMORY_STORES for cross-module
consistency.  All extend BaseRepository from repos.py.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now


# ── Challenges ────────────────────────────────────────────────────────────────

class ChallengesRepository(BaseRepository):
    """Stores PaymentChallenge records (one per challenge_id)."""

    def __init__(self) -> None:
        super().__init__("commerce_challenges")

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        record.setdefault("created_at", utc_now().isoformat())
        record.setdefault("status", "pending")
        await self.insert(record["challenge_id"], record)
        return record

    async def get(self, challenge_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(challenge_id)

    async def get_or_fail(self, challenge_id: str) -> dict[str, Any]:
        return await self.find_by_id_or_fail(challenge_id)

    async def update_status(
        self, challenge_id: str, status: str, **extra: Any
    ) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(challenge_id)
        if record is None:
            return None
        record["status"] = status
        record["updated_at"] = utc_now().isoformat()
        record.update(extra)
        await self.insert(challenge_id, record)
        return record

    async def list_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            filters={"tenant_id": tenant_id}, limit=limit, offset=offset
        )


# ── Approvals ─────────────────────────────────────────────────────────────────

class ApprovalsRepository(BaseRepository):
    """Stores ApprovalRequest records with full lifecycle state."""

    def __init__(self) -> None:
        super().__init__("commerce_approvals")

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        record.setdefault("created_at", utc_now().isoformat())
        record.setdefault("status", "pending")
        record.setdefault("escalation_chain", [])
        await self.insert(record["approval_id"], record)
        return record

    async def get(self, approval_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(approval_id)

    async def get_or_fail(self, approval_id: str) -> dict[str, Any]:
        return await self.find_by_id_or_fail(approval_id)

    async def update(self, approval_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(approval_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = utc_now().isoformat()
        await self.insert(approval_id, record)
        return record

    async def queue(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        assignee_id: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        if assignee_id:
            filters["assigned_to"] = assignee_id
        if priority:
            filters["priority"] = priority
        return await self.find_many(filters=filters, limit=limit, offset=offset)

    async def list_expired(self, tenant_id: str) -> list[dict[str, Any]]:
        now = utc_now().isoformat()
        all_pending = await self.find_many(
            filters={"tenant_id": tenant_id, "status": "pending"}, limit=1000
        )
        return [r for r in all_pending if r.get("expires_at", "9999") < now]

    async def list_for_execution(
        self, *, tenant_id: str, execution_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return only commerce approvals explicitly bound to one exact run."""
        return await self.find_many(
            filters={"tenant_id": tenant_id, "execution_id": execution_id},
            limit=max(0, min(int(limit), 500)),
        )

    async def count_pending(self, tenant_id: str) -> int:
        records = await self.find_many(
            filters={"tenant_id": tenant_id, "status": "pending"}, limit=10000
        )
        return len(records)


class ApprovalDecisionsRepository(BaseRepository):
    """Append-only decision evidence for the canonical commerce approval owner."""

    def __init__(self) -> None:
        super().__init__("commerce_approval_decisions")

    async def insert_immutable(self, record_id: str, data: dict[str, Any]) -> bool:
        """Insert once, with conflicts resolved atomically in PostgreSQL."""
        payload = dict(data)
        payload["id"] = record_id
        now = utc_now().isoformat()
        payload["created_at"] = now
        payload["updated_at"] = now
        pool = await self._ensure_pool()
        if pool is None:
            if record_id in self._store:
                return False
            self._store[record_id] = payload
            return True
        await self._ensure_table()
        if not self._jsonb_mode:
            raise RuntimeError("commerce_approval_decisions must use the JSONB repository schema")
        row = await pool.fetchrow(
            f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING RETURNING id""",
            record_id, json.dumps(payload, default=str), payload.get("tenant_id"),
        )
        return row is not None

    async def list_for_executions(
        self, *, tenant_id: str, execution_ids: list[str], limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return decisions bound to exact execution IDs inside one tenant."""
        selected_ids = list(dict.fromkeys(value for value in execution_ids if value))[:500]
        bounded_limit = max(0, min(int(limit), 5000))
        if not selected_ids or bounded_limit == 0:
            return []

        pool = await self._ensure_pool()
        if pool is None:
            rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=10000)
            selected = [
                row
                for row in rows
                if row.get("tenant_id") == tenant_id
                and row.get("execution_id") in selected_ids
            ]
            selected.sort(key=lambda row: str(row.get("decided_at") or ""))
            return selected[:bounded_limit]

        await self._ensure_table()
        if not self._jsonb_mode:
            raise RuntimeError("commerce_approval_decisions must use the JSONB repository schema")
        records = await pool.fetch(
            f"""
            SELECT data
            FROM {self.table_name}
            WHERE tenant_id = $1
              AND data->>'execution_id' = ANY($2::text[])
            ORDER BY data->>'decided_at' ASC, id ASC
            LIMIT $3
            """,
            tenant_id,
            selected_ids,
            bounded_limit,
        )
        import json

        return [json.loads(row["data"]) for row in records]


# ── Entitlements ──────────────────────────────────────────────────────────────

class EntitlementsRepository(BaseRepository):
    """Stores Entitlement records with reuse/expiry tracking."""

    def __init__(self) -> None:
        super().__init__("commerce_entitlements")

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        record.setdefault("created_at", utc_now().isoformat())
        record.setdefault("status", "active")
        record.setdefault("reuse_count", 0)
        await self.insert(record["entitlement_id"], record)
        return record

    async def get(self, entitlement_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(entitlement_id)

    async def get_or_fail(self, entitlement_id: str) -> dict[str, Any]:
        return await self.find_by_id_or_fail(entitlement_id)

    async def increment_reuse(self, entitlement_id: str) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(entitlement_id)
        if record is None:
            return None
        record["reuse_count"] = record.get("reuse_count", 0) + 1
        record["last_reused_at"] = utc_now().isoformat()
        await self.insert(entitlement_id, record)
        return record

    async def revoke(self, entitlement_id: str, reason: str) -> Optional[dict[str, Any]]:
        return await self._set_status(entitlement_id, "revoked", revoke_reason=reason)

    async def expire(self, entitlement_id: str) -> Optional[dict[str, Any]]:
        return await self._set_status(entitlement_id, "expired")

    async def _set_status(self, entitlement_id: str, status: str, **extra: Any) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(entitlement_id)
        if record is None:
            return None
        record["status"] = status
        record["updated_at"] = utc_now().isoformat()
        record.update(extra)
        await self.insert(entitlement_id, record)
        return record

    async def list_active_for_agent(
        self, agent_id: str, tenant_id: str
    ) -> list[dict[str, Any]]:
        now = utc_now().isoformat()
        records = await self.find_many(
            filters={"tenant_id": tenant_id, "granted_to": agent_id, "status": "active"},
            limit=200,
        )
        return [
            r for r in records
            if not r.get("expires_at") or r["expires_at"] > now
        ]


# ── Settlements ───────────────────────────────────────────────────────────────

class SettlementsRepository(BaseRepository):
    """Stores SettlementRecord with FSM state tracking."""

    def __init__(self) -> None:
        super().__init__("commerce_settlements")

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        record.setdefault("created_at", utc_now().isoformat())
        record.setdefault("state", "pending")
        record.setdefault("retries", 0)
        await self.insert(record["settlement_id"], record)
        return record

    async def get(self, settlement_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(settlement_id)

    async def get_or_fail(self, settlement_id: str) -> dict[str, Any]:
        return await self.find_by_id_or_fail(settlement_id)

    async def transition(
        self, settlement_id: str, new_state: str, **extra: Any
    ) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(settlement_id)
        if record is None:
            return None
        record["state"] = new_state
        record["updated_at"] = utc_now().isoformat()
        record.update(extra)
        await self.insert(settlement_id, record)
        return record

    async def increment_retry(self, settlement_id: str) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(settlement_id)
        if record is None:
            return None
        record["retries"] = record.get("retries", 0) + 1
        record["last_retry_at"] = utc_now().isoformat()
        await self.insert(settlement_id, record)
        return record

    async def list_stuck(
        self, tenant_id: str, timeout_seconds: int = 300
    ) -> list[dict[str, Any]]:
        from datetime import datetime, timezone, timedelta
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        ).isoformat()
        records = await self.find_many(
            filters={"tenant_id": tenant_id}, limit=500
        )
        return [
            r for r in records
            if r.get("state") in ("pending", "verifying")
            and r.get("created_at", "9999") < cutoff
        ]

    async def list_failed(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await self.find_many(
            filters={"tenant_id": tenant_id, "state": "failed"}, limit=limit
        )


# ── Protected Resources ───────────────────────────────────────────────────────

class ResourcesRepository(BaseRepository):
    """Stores ProtectedResource registrations."""

    def __init__(self) -> None:
        super().__init__("commerce_resources")

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        record.setdefault("created_at", utc_now().isoformat())
        record.setdefault("active", True)
        await self.insert(record["resource_id"], record)
        return record

    async def get(self, resource_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(resource_id)

    async def get_or_fail(self, resource_id: str) -> dict[str, Any]:
        return await self.find_by_id_or_fail(resource_id)

    async def update(self, resource_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(resource_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = utc_now().isoformat()
        await self.insert(resource_id, record)
        return record

    async def list_active(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"active": True}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        return await self.find_many(filters=filters, limit=500)

    async def find_by_path_pattern(
        self, path: str, tenant_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        import re
        filters: dict[str, Any] = {"active": True}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        records = await self.find_many(filters=filters, limit=500)
        for record in records:
            pattern = record.get("path_pattern", "")
            if pattern and re.match(pattern, path):
                return record
        return None


# ── Policies ──────────────────────────────────────────────────────────────────

class PoliciesRepository(BaseRepository):
    """Stores price/budget/treasury policy records."""

    def __init__(self) -> None:
        super().__init__("commerce_policies")

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        record.setdefault("created_at", utc_now().isoformat())
        record.setdefault("active", True)
        await self.insert(record["policy_id"], record)
        return record

    async def get(self, policy_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(policy_id)

    async def get_or_fail(self, policy_id: str) -> dict[str, Any]:
        return await self.find_by_id_or_fail(policy_id)

    async def update(self, policy_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(policy_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = utc_now().isoformat()
        await self.insert(policy_id, record)
        return record

    async def list_active_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            filters={"tenant_id": tenant_id, "active": True}, limit=200
        )

    async def list_by_rule_type(
        self, rule_type: str, tenant_id: str
    ) -> list[dict[str, Any]]:
        records = await self.find_many(
            filters={"tenant_id": tenant_id, "active": True}, limit=200
        )
        return [r for r in records if r.get("rule_type") == rule_type]

    async def deactivate(self, policy_id: str) -> Optional[dict[str, Any]]:
        return await self.update(policy_id, {"active": False})


# ── Facilitators ──────────────────────────────────────────────────────────────

class FacilitatorsRepository(BaseRepository):
    """Stores FacilitatorRecord with health and routing metadata."""

    def __init__(self) -> None:
        super().__init__("commerce_facilitators")

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        record.setdefault("created_at", utc_now().isoformat())
        record.setdefault("active", True)
        record.setdefault("health_status", "unknown")
        await self.insert(record["facilitator_id"], record)
        return record

    async def get(self, facilitator_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(facilitator_id)

    async def get_or_fail(self, facilitator_id: str) -> dict[str, Any]:
        return await self.find_by_id_or_fail(facilitator_id)

    async def update_health(
        self,
        facilitator_id: str,
        health_status: str,
        latency_ms: Optional[int] = None,
        error_rate: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        updates: dict[str, Any] = {
            "health_status": health_status,
            "last_health_check": utc_now().isoformat(),
        }
        if latency_ms is not None:
            updates["latency_ms"] = latency_ms
        if error_rate is not None:
            updates["error_rate"] = error_rate
        return await self._update_record(facilitator_id, updates)

    async def _update_record(
        self, facilitator_id: str, updates: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(facilitator_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = utc_now().isoformat()
        await self.insert(facilitator_id, record)
        return record

    async def list_active(self) -> list[dict[str, Any]]:
        return await self.find_many(filters={"active": True}, limit=100)

    async def list_healthy(self) -> list[dict[str, Any]]:
        records = await self.list_active()
        return [r for r in records if r.get("health_status") == "healthy"]

    async def register_asset(
        self, facilitator_id: str, asset: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(facilitator_id)
        if record is None:
            return None
        assets: list[dict] = record.get("accepted_assets", [])
        assets.append(asset)
        record["accepted_assets"] = assets
        record["updated_at"] = utc_now().isoformat()
        await self.insert(facilitator_id, record)
        return record


# ── Additional repositories (payment lifecycle objects) ───────────────────────

class AssetsRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("commerce_assets")


class AuthorizationsRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("commerce_authorizations")


class ReceiptsRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("commerce_receipts")


class AccessGrantsRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("commerce_grants")


class FulfillmentsRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("commerce_fulfillments")


class TreasuriesRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("commerce_treasuries")


class BudgetPoliciesRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("commerce_budget_policies")
