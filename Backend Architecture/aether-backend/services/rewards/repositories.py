"""
Aether Backend — Reward Enablement Repositories

Durable data access layer for A6 reward enablement. Each repository extends
BaseRepository which auto-selects PostgreSQL (staging/production) or in-memory
dicts (AETHER_ENV=local / AETHER_ENV=test).

All reads and writes are tenant-scoped. Every write is guarded by a tenant_id
check; cross-tenant access raises ForbiddenError.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import ForbiddenError, NotFoundError, utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.service.rewards.repositories")


def _is_durable_required() -> bool:
    env = os.getenv("AETHER_ENV", "local").lower()
    return env not in ("local", "test") and os.getenv("REWARD_REQUIRE_DURABLE_STORE", "1") == "1"


def _assert_durable_available(pool) -> None:
    if _is_durable_required() and pool is None:
        raise RuntimeError(
            "Reward enablement requires a durable PostgreSQL store. "
            "Set DATABASE_URL or AETHER_ENV=local for in-memory mode."
        )


def _new_id() -> str:
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGN REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardCampaignRepository(BaseRepository):
    """CRUD for tenant-scoped reward campaigns."""

    def __init__(self) -> None:
        super().__init__("reward_campaigns")

    async def create(self, tenant_id: str, data: dict) -> dict:
        pool = await self._ensure_pool()
        _assert_durable_available(pool)
        record_id = data.get("id") or _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id, "status": data.get("status", "active")}
        return await self.insert(record_id, record)

    async def get(self, campaign_id: str, tenant_id: str) -> dict:
        record = await self.find_by_id(campaign_id)
        if record is None:
            raise NotFoundError("RewardCampaign")
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("RewardCampaign")
        return record

    async def list(self, tenant_id: str, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        return await self.find_many(filters=filters, limit=limit, offset=offset)

    async def update_status(self, campaign_id: str, tenant_id: str, status: str) -> dict:
        record = await self.get(campaign_id, tenant_id)
        return await self.update(campaign_id, {"status": status})

    async def archive(self, campaign_id: str, tenant_id: str) -> dict:
        record = await self.get(campaign_id, tenant_id)
        return await self.update(campaign_id, {"status": "archived", "archived_at": utc_now().isoformat()})

    async def get_active_for_event(self, tenant_id: str, project_id: Optional[str] = None) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id, "status": "active"}
        records = await self.find_many(filters=filters, limit=200)
        if project_id:
            records = [r for r in records if r.get("project_id") in (None, project_id)]
        return records


# ═══════════════════════════════════════════════════════════════════════════
# RULE REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardRuleRepository(BaseRepository):
    """CRUD for reward rules within campaigns."""

    def __init__(self) -> None:
        super().__init__("reward_rules")

    async def create(self, tenant_id: str, campaign_id: str, data: dict) -> dict:
        pool = await self._ensure_pool()
        _assert_durable_available(pool)
        record_id = _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id, "campaign_id": campaign_id, "active": True}
        return await self.insert(record_id, record)

    async def get(self, rule_id: str, tenant_id: str) -> dict:
        record = await self.find_by_id(rule_id)
        if record is None:
            raise NotFoundError("RewardRule")
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("RewardRule")
        return record

    async def list_for_campaign(self, campaign_id: str, tenant_id: str) -> list[dict]:
        records = await self.find_many(filters={"tenant_id": tenant_id, "campaign_id": campaign_id}, limit=100)
        return sorted(records, key=lambda r: (r.get("priority", 0), r.get("created_at", "")))

    async def set_active(self, rule_id: str, tenant_id: str, active: bool) -> dict:
        await self.get(rule_id, tenant_id)
        return await self.update(rule_id, {"active": active})


# ═══════════════════════════════════════════════════════════════════════════
# DECISION REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardDecisionRepository(BaseRepository):
    """Durable eligibility decisions with idempotency support."""

    def __init__(self) -> None:
        super().__init__("reward_eligibility_decisions")

    async def create(self, tenant_id: str, data: dict) -> dict:
        pool = await self._ensure_pool()
        _assert_durable_available(pool)
        record_id = _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id}
        return await self.insert(record_id, record)

    async def get(self, decision_id: str, tenant_id: str) -> dict:
        record = await self.find_by_id(decision_id)
        if record is None:
            raise NotFoundError("RewardDecision")
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("RewardDecision")
        return record

    async def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> Optional[dict]:
        """Return an existing decision for a (tenant_id, idempotency_key) pair, or None."""
        if not idempotency_key:
            return None
        results = await self.find_many(
            filters={"tenant_id": tenant_id, "idempotency_key": idempotency_key},
            limit=1,
        )
        return results[0] if results else None

    async def create_once(self, tenant_id: str, idempotency_key: Optional[str], data: dict) -> tuple[dict, bool]:
        """Return (decision, created). If idempotency_key exists, return existing."""
        if idempotency_key:
            existing = await self.get_by_idempotency_key(tenant_id, idempotency_key)
            if existing:
                return existing, False
        record = await self.create(tenant_id, {**data, "idempotency_key": idempotency_key})
        return record, True

    async def list(self, tenant_id: str, filters: Optional[dict] = None, limit: int = 50, offset: int = 0) -> list[dict]:
        f: dict = {"tenant_id": tenant_id}
        if filters:
            f.update(filters)
        return await self.find_many(filters=f, limit=limit, offset=offset)

    async def get_eligible_count(self, tenant_id: str, campaign_id: str, user_id: Optional[str], wallet_address: Optional[str]) -> int:
        """Count eligible decisions for a user in a campaign (for cap enforcement)."""
        actor_key = user_id or wallet_address or ""
        records = await self.find_many(
            filters={"tenant_id": tenant_id, "campaign_id": campaign_id, "eligible": True},
            limit=10000,
        )
        if not actor_key:
            return len(records)
        return sum(
            1 for r in records
            if r.get("user_id") == actor_key or r.get("wallet_address", "").lower() == actor_key.lower()
        )

    async def get_last_eligible_at(self, tenant_id: str, campaign_id: str, user_id: Optional[str], wallet_address: Optional[str]) -> Optional[str]:
        """Return ISO timestamp of last eligible decision for cooldown enforcement."""
        actor_key = user_id or wallet_address or ""
        records = await self.find_many(
            filters={"tenant_id": tenant_id, "campaign_id": campaign_id, "eligible": True},
            limit=10000,
            sort_by="created_at",
            sort_order="desc",
        )
        for r in records:
            if r.get("user_id") == actor_key or r.get("wallet_address", "").lower() == actor_key.lower():
                return r.get("created_at")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# ACTION PAYLOAD REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardActionRepository(BaseRepository):
    """CRUD for reward action payloads."""

    def __init__(self) -> None:
        super().__init__("reward_action_payloads")

    async def create(self, tenant_id: str, data: dict) -> dict:
        pool = await self._ensure_pool()
        _assert_durable_available(pool)
        record_id = _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id}
        return await self.insert(record_id, record)

    async def get(self, action_id: str, tenant_id: str) -> dict:
        record = await self.find_by_id(action_id)
        if record is None:
            raise NotFoundError("RewardAction")
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("RewardAction")
        return record

    async def list(self, tenant_id: str, status: Optional[str] = None, rail: Optional[str] = None, limit: int = 50, offset: int = 0) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        if rail:
            filters["rail"] = rail
        return await self.find_many(filters=filters, limit=limit, offset=offset)

    async def transition(self, action_id: str, tenant_id: str, new_status: str, extra: Optional[dict] = None) -> dict:
        await self.get(action_id, tenant_id)
        update_data = {"status": new_status}
        if extra:
            update_data.update(extra)
        if new_status == "delivered":
            update_data["delivered_at"] = utc_now().isoformat()
        return await self.update(action_id, update_data)

    async def increment_delivery_attempts(self, action_id: str, tenant_id: str, error: Optional[str] = None) -> dict:
        record = await self.get(action_id, tenant_id)
        attempts = int(record.get("delivery_attempts", 0)) + 1
        update_data: dict = {"delivery_attempts": attempts}
        if error:
            update_data["last_delivery_error"] = error
        return await self.update(action_id, update_data)


# ═══════════════════════════════════════════════════════════════════════════
# PROOF REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardProofRepository(BaseRepository):
    """CRUD for on-chain claim proofs with replay protection."""

    def __init__(self) -> None:
        super().__init__("reward_proofs")

    async def create(self, tenant_id: str, data: dict) -> dict:
        pool = await self._ensure_pool()
        _assert_durable_available(pool)
        record_id = _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id, "status": "created"}
        return await self.insert(record_id, record)

    async def get(self, proof_id: str, tenant_id: str) -> dict:
        record = await self.find_by_id(proof_id)
        if record is None:
            raise NotFoundError("RewardProof")
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("RewardProof")
        return record

    async def list(self, tenant_id: str, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        return await self.find_many(filters=filters, limit=limit, offset=offset)

    async def is_nonce_used(self, nonce: str) -> bool:
        """Check replay: has any proof with this nonce been created?"""
        results = await self.find_many(filters={"nonce": nonce}, limit=1)
        return len(results) > 0

    async def mark_used(self, proof_id: str, tenant_id: str) -> dict:
        await self.get(proof_id, tenant_id)
        return await self.update(proof_id, {"status": "used", "used_at": utc_now().isoformat()})

    async def mark_revoked(self, proof_id: str, tenant_id: str, reason: Optional[str] = None) -> dict:
        record = await self.get(proof_id, tenant_id)
        if record.get("status") == "used":
            raise ValueError("Cannot revoke a proof that has already been used on-chain")
        update_data: dict = {"status": "revoked", "revoked_at": utc_now().isoformat()}
        if reason:
            update_data["revocation_reason"] = reason
        return await self.update(proof_id, update_data)

    async def get_by_decision(self, decision_id: str, tenant_id: str) -> Optional[dict]:
        results = await self.find_many(filters={"tenant_id": tenant_id, "decision_id": decision_id}, limit=1)
        return results[0] if results else None


# ═══════════════════════════════════════════════════════════════════════════
# RECEIPT REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardReceiptRepository(BaseRepository):
    """Execution receipts submitted by tenant systems."""

    def __init__(self) -> None:
        super().__init__("reward_execution_receipts")

    async def create(self, tenant_id: str, data: dict) -> dict:
        pool = await self._ensure_pool()
        _assert_durable_available(pool)
        record_id = _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id}
        return await self.insert(record_id, record)

    async def get(self, receipt_id: str, tenant_id: str) -> dict:
        record = await self.find_by_id(receipt_id)
        if record is None:
            raise NotFoundError("RewardReceipt")
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("RewardReceipt")
        return record

    async def list(self, tenant_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit, offset=offset)


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT REPOSITORY (append-only)
# ═══════════════════════════════════════════════════════════════════════════

class RewardAuditRepository(BaseRepository):
    """Append-only audit log for all reward lifecycle events."""

    def __init__(self) -> None:
        super().__init__("reward_audit_log")

    async def append(
        self,
        tenant_id: str,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> dict:
        record_id = _new_id()
        record = {
            "id": record_id,
            "tenant_id": tenant_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "before_state": before_state,
            "after_state": after_state,
            "reason": reason,
            "request_id": request_id,
            "created_at": utc_now().isoformat(),
        }
        return await self.insert(record_id, record)

    async def list(self, tenant_id: str, target_type: Optional[str] = None, target_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if target_type:
            filters["target_type"] = target_type
        if target_id:
            filters["target_id"] = target_id
        return await self.find_many(filters=filters, limit=limit)


# ═══════════════════════════════════════════════════════════════════════════
# RAIL CONFIG REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardRailConfigRepository(BaseRepository):
    """Per-tenant rail configuration storage."""

    def __init__(self) -> None:
        super().__init__("tenant_reward_rail_configs")

    async def create_or_update(self, tenant_id: str, rail: str, data: dict) -> dict:
        existing = await self.get_by_rail(tenant_id, rail)
        if existing:
            return await self.update(existing["id"], {**data, "tenant_id": tenant_id, "rail": rail})
        record_id = _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id, "rail": rail}
        return await self.insert(record_id, record)

    async def get_by_rail(self, tenant_id: str, rail: str) -> Optional[dict]:
        results = await self.find_many(filters={"tenant_id": tenant_id, "rail": rail}, limit=1)
        return results[0] if results else None

    async def get(self, config_id: str, tenant_id: str) -> dict:
        record = await self.find_by_id(config_id)
        if record is None:
            raise NotFoundError("RewardRailConfig")
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("RewardRailConfig")
        return record

    async def list(self, tenant_id: str) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=50)

    async def set_status(self, config_id: str, tenant_id: str, status: str, enabled: Optional[bool] = None) -> dict:
        await self.get(config_id, tenant_id)
        update_data: dict = {"status": status}
        if enabled is not None:
            update_data["enabled"] = enabled
        if status == "verified":
            update_data["last_verified_at"] = utc_now().isoformat()
        return await self.update(config_id, update_data)


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT REGISTRY REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class ContractRegistryRepository(BaseRepository):
    """Tenant-owned smart contract registry for proof generation gating.

    tenant_contract_registry uses a columnar schema (not JSONB data column), so
    all Postgres paths are implemented directly here rather than via BaseRepository's
    JSONB insert/find_many helpers.
    """

    def __init__(self) -> None:
        super().__init__("tenant_contract_registry")

    def _row_to_dict(self, row: Any) -> dict:
        """Convert an asyncpg Record to a plain dict."""
        return dict(row)

    async def register(self, tenant_id: str, data: dict) -> dict:
        record_id = _new_id()
        record = {**data, "id": record_id, "tenant_id": tenant_id, "verification_status": "pending"}
        pool = await self._ensure_pool()
        if pool is None:
            self._store[record_id] = record
            return record
        # Columnar INSERT — matches the migration schema exactly.
        import json as _json
        allowed = data.get("allowed_campaign_ids") or []
        await pool.execute(
            """INSERT INTO tenant_contract_registry
               (id, tenant_id, chain_id, contract_address, contract_name, abi_ref,
                verification_status, allowed_campaign_ids, oracle_signer_address,
                created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,'pending',$7,$8,NOW(),NOW())
               ON CONFLICT (tenant_id, chain_id, contract_address)
               DO UPDATE SET updated_at=NOW()""",
            record_id, tenant_id,
            int(data.get("chain_id", 1)),
            data.get("contract_address", ""),
            data.get("contract_name", ""),
            data.get("abi_ref"),
            allowed,
            data.get("oracle_signer_address", ""),
        )
        return record

    async def get(self, registry_id: str, tenant_id: str) -> dict:
        pool = await self._ensure_pool()
        if pool is None:
            record = self._store.get(registry_id)
            if record is None:
                raise NotFoundError("ContractRegistry")
            if record.get("tenant_id") != tenant_id:
                raise ForbiddenError("ContractRegistry")
            return record
        row = await pool.fetchrow(
            "SELECT * FROM tenant_contract_registry WHERE id=$1", registry_id
        )
        if row is None:
            raise NotFoundError("ContractRegistry")
        record = self._row_to_dict(row)
        if record.get("tenant_id") != tenant_id:
            raise ForbiddenError("ContractRegistry")
        return record

    async def find_for_proof(self, tenant_id: str, chain_id: int, contract_address: str, campaign_id: str = "") -> Optional[dict]:
        """Return a verified registry entry for proof generation, or None.

        Queries by (tenant_id, chain_id, contract_address) directly — no Python-side
        pagination over a capped result set.
        """
        pool = await self._ensure_pool()
        if pool is None:
            for r in self._store.values():
                if (r.get("tenant_id") == tenant_id
                        and r.get("verification_status") == "verified"
                        and r.get("chain_id") == chain_id
                        and r.get("contract_address", "").lower() == contract_address.lower()):
                    allowed = r.get("allowed_campaign_ids", [])
                    if not allowed or campaign_id in allowed:
                        return r
            return None
        row = await pool.fetchrow(
            """SELECT * FROM tenant_contract_registry
               WHERE tenant_id=$1 AND chain_id=$2
                 AND LOWER(contract_address)=LOWER($3)
                 AND verification_status='verified'""",
            tenant_id, chain_id, contract_address,
        )
        if row is None:
            return None
        record = self._row_to_dict(row)
        allowed = record.get("allowed_campaign_ids") or []
        if allowed and campaign_id not in allowed:
            return None
        return record

    async def list(self, tenant_id: str) -> list[dict]:
        pool = await self._ensure_pool()
        if pool is None:
            return [r for r in self._store.values() if r.get("tenant_id") == tenant_id]
        rows = await pool.fetch(
            "SELECT * FROM tenant_contract_registry WHERE tenant_id=$1 ORDER BY created_at DESC",
            tenant_id,
        )
        return [self._row_to_dict(r) for r in rows]

    async def verify(self, registry_id: str, tenant_id: str) -> dict:
        record = await self.get(registry_id, tenant_id)
        pool = await self._ensure_pool()
        if pool is None:
            record["verification_status"] = "verified"
            self._store[registry_id] = record
            return record
        await pool.execute(
            "UPDATE tenant_contract_registry SET verification_status='verified', updated_at=NOW() WHERE id=$1",
            registry_id,
        )
        record["verification_status"] = "verified"
        return record
