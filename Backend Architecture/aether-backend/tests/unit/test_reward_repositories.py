"""
Unit tests for reward repositories (A6).

Covers: tenant isolation, idempotency key uniqueness, proof status
transitions, audit log append-only behavior, and CRUD operations.
All tests use in-memory backend (AETHER_ENV=local).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import ForbiddenError, NotFoundError
from services.rewards.repositories import (
    ContractRegistryRepository,
    RewardActionRepository,
    RewardAuditRepository,
    RewardCampaignRepository,
    RewardDecisionRepository,
    RewardProofRepository,
    RewardRailConfigRepository,
    RewardReceiptRepository,
    RewardRuleRepository,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _now():
    return datetime.now(timezone.utc).isoformat()


TENANT_A = "tenant_isolation_a"
TENANT_B = "tenant_isolation_b"


# ═══════════════════════════════════════════════════════════════════════════
# TENANT ISOLATION: Campaign repository
# ═══════════════════════════════════════════════════════════════════════════

def test_campaign_tenant_isolation():
    repo = RewardCampaignRepository()

    async def run():
        # Create campaign for Tenant A
        camp_a = await repo.create(TENANT_A, {
            "name": "Campaign A",
            "status": "active",
            "default_rail": "recommend_only",
            "default_execution_mode": "recommend_only",
            "budget_policy": {},
            "attribution_model": "last_touch",
            "created_at": _now(),
            "updated_at": _now(),
        })
        # Tenant B cannot access Tenant A's campaign
        with pytest.raises((ForbiddenError, NotFoundError)):
            await repo.get(camp_a["id"], TENANT_B)

    _run(run())


def test_campaign_list_scoped_to_tenant():
    repo = RewardCampaignRepository()

    async def run():
        await repo.create(TENANT_A, {"name": "A Campaign", "status": "active",
                                     "default_rail": "recommend_only",
                                     "default_execution_mode": "recommend_only",
                                     "budget_policy": {}, "attribution_model": "last_touch",
                                     "created_at": _now(), "updated_at": _now()})
        await repo.create(TENANT_B, {"name": "B Campaign", "status": "active",
                                     "default_rail": "recommend_only",
                                     "default_execution_mode": "recommend_only",
                                     "budget_policy": {}, "attribution_model": "last_touch",
                                     "created_at": _now(), "updated_at": _now()})
        a_list = await repo.list(TENANT_A)
        b_list = await repo.list(TENANT_B)
        a_names = {c["name"] for c in a_list}
        b_names = {c["name"] for c in b_list}
        return a_names, b_names

    a_names, b_names = _run(run())
    assert "A Campaign" in a_names
    assert "B Campaign" not in a_names
    assert "B Campaign" in b_names
    assert "A Campaign" not in b_names


# ═══════════════════════════════════════════════════════════════════════════
# TENANT ISOLATION: Decision repository
# ═══════════════════════════════════════════════════════════════════════════

def test_decision_tenant_isolation():
    repo = RewardDecisionRepository()

    async def run():
        dec_a = await repo.create(TENANT_A, {
            "eligible": True, "decision": "eligible",
            "created_at": _now(),
        })
        with pytest.raises((ForbiddenError, NotFoundError)):
            await repo.get(dec_a["id"], TENANT_B)

    _run(run())


# ═══════════════════════════════════════════════════════════════════════════
# IDEMPOTENCY KEY UNIQUENESS
# ═══════════════════════════════════════════════════════════════════════════

def test_idempotency_key_returns_existing_decision():
    repo = RewardDecisionRepository()

    async def run():
        data = {"eligible": True, "decision": "eligible", "created_at": _now()}
        rec1, created1 = await repo.create_once(TENANT_A, "idem_test_unique_001", data)
        rec2, created2 = await repo.create_once(TENANT_A, "idem_test_unique_001", data)
        return rec1, rec2, created1, created2

    r1, r2, c1, c2 = _run(run())
    assert r1["id"] == r2["id"]
    assert c1 is True
    assert c2 is False


def test_idempotency_key_scoped_to_tenant():
    repo = RewardDecisionRepository()

    async def run():
        data = {"eligible": True, "decision": "eligible", "created_at": _now()}
        rec_a, created_a = await repo.create_once(TENANT_A, "shared_idem_key", data)
        rec_b, created_b = await repo.create_once(TENANT_B, "shared_idem_key", data)
        return rec_a, rec_b, created_a, created_b

    ra, rb, ca, cb = _run(run())
    # Same key for different tenants should create separate records
    assert ra["id"] != rb["id"]
    assert ca is True
    assert cb is True


def test_idempotency_none_key_always_creates():
    repo = RewardDecisionRepository()

    async def run():
        data = {"eligible": True, "decision": "eligible", "created_at": _now()}
        r1, c1 = await repo.create_once(TENANT_A, None, data)
        r2, c2 = await repo.create_once(TENANT_A, None, data)
        return r1, r2

    r1, r2 = _run(run())
    assert r1["id"] != r2["id"]


# ═══════════════════════════════════════════════════════════════════════════
# PROOF STATUS TRANSITIONS
# ═══════════════════════════════════════════════════════════════════════════

def test_proof_initial_status_is_created():
    repo = RewardProofRepository()

    async def run():
        proof = await repo.create(TENANT_A, {
            "nonce": os.urandom(16).hex(),
            "wallet_address": "0xdeadbeef",
            "expiry": int(time.time()) + 3600,
            "expires_at": "2099-01-01T00:00:00Z",
            "created_at": _now(),
        })
        return proof

    proof = _run(run())
    assert proof["status"] == "created"


def test_proof_mark_used_transition():
    repo = RewardProofRepository()

    async def run():
        proof = await repo.create(TENANT_A, {
            "nonce": os.urandom(16).hex(),
            "wallet_address": "0xdeadbeef",
            "expiry": int(time.time()) + 3600,
            "expires_at": "2099-01-01T00:00:00Z",
            "created_at": _now(),
        })
        updated = await repo.mark_used(proof["id"], TENANT_A)
        return updated

    result = _run(run())
    assert result["status"] == "used"


def test_proof_mark_revoked_transition():
    repo = RewardProofRepository()

    async def run():
        proof = await repo.create(TENANT_A, {
            "nonce": os.urandom(16).hex(),
            "wallet_address": "0xbeefdead",
            "expiry": int(time.time()) + 3600,
            "expires_at": "2099-01-01T00:00:00Z",
            "created_at": _now(),
        })
        updated = await repo.mark_revoked(proof["id"], TENANT_A, reason="fraud_detected")
        return updated

    result = _run(run())
    assert result["status"] == "revoked"
    assert "revoked_at" in result


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT LOG: Append-only
# ═══════════════════════════════════════════════════════════════════════════

def test_audit_log_append_only():
    repo = RewardAuditRepository()

    async def run():
        for action in ["campaign.created", "campaign.paused", "campaign.archived"]:
            await repo.append({
                "tenant_id": TENANT_A,
                "actor_type": "system",
                "action": action,
                "target_type": "reward_campaign",
                "target_id": "camp_test_001",
                "created_at": _now(),
            })
        return await repo.list(TENANT_A)

    records = _run(run())
    actions = [r["action"] for r in records]
    for expected_action in ["campaign.created", "campaign.paused", "campaign.archived"]:
        assert expected_action in actions


def test_audit_log_tenant_isolation():
    repo = RewardAuditRepository()

    async def run():
        await repo.append({
            "tenant_id": TENANT_A,
            "actor_type": "operator",
            "action": "audit.test.a",
            "target_type": "test",
            "created_at": _now(),
        })
        await repo.append({
            "tenant_id": TENANT_B,
            "actor_type": "operator",
            "action": "audit.test.b",
            "target_type": "test",
            "created_at": _now(),
        })
        a_logs = await repo.list(TENANT_A)
        b_logs = await repo.list(TENANT_B)
        return a_logs, b_logs

    a_logs, b_logs = _run(run())
    a_actions = {r["action"] for r in a_logs}
    b_actions = {r["action"] for r in b_logs}
    assert "audit.test.a" in a_actions
    assert "audit.test.b" not in a_actions
    assert "audit.test.b" in b_actions
    assert "audit.test.a" not in b_actions


# ═══════════════════════════════════════════════════════════════════════════
# RAIL CONFIG: create_or_update uniqueness
# ═══════════════════════════════════════════════════════════════════════════

def test_rail_config_upsert():
    repo = RewardRailConfigRepository()

    async def run():
        data1 = {
            "rail": "tenant_webhook",
            "enabled": False,
            "config": {"timeout_ms": 5000},
            "webhook_url": "https://example.com/v1",
            "status": "pending_verification",
            "created_at": _now(),
            "updated_at": _now(),
        }
        r1 = await repo.create_or_update(TENANT_A, "tenant_webhook", data1)

        data2 = {**data1, "webhook_url": "https://example.com/v2", "updated_at": _now()}
        r2 = await repo.create_or_update(TENANT_A, "tenant_webhook", data2)
        return r1, r2

    r1, r2 = _run(run())
    assert r2.get("webhook_url") == "https://example.com/v2"


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

def test_contract_registry_register_and_retrieve():
    repo = ContractRegistryRepository()

    async def run():
        entry = await repo.register(TENANT_A, {
            "chain_id": 1,
            "contract_address": "0xdeadbeef",
            "contract_name": "AetherRewardEnabler",
            "allowed_campaign_ids": ["camp_001"],
            "oracle_signer_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            "created_at": _now(),
            "updated_at": _now(),
        })
        # Must verify before find_for_proof returns the entry
        await repo.verify(entry["id"], TENANT_A)
        fetched = await repo.find_for_proof(TENANT_A, chain_id=1, contract_address="0xdeadbeef")
        return entry, fetched

    entry, fetched = _run(run())
    assert entry is not None
    assert fetched is not None
    assert fetched["contract_address"] == "0xdeadbeef"


def test_contract_registry_tenant_isolation():
    repo = ContractRegistryRepository()

    async def run():
        await repo.register(TENANT_A, {
            "chain_id": 1,
            "contract_address": "0xcafe",
            "contract_name": "AetherRewardEnabler",
            "verification_status": "verified",
            "allowed_campaign_ids": [],
            "oracle_signer_address": "0xsigner",
            "created_at": _now(),
            "updated_at": _now(),
        })
        # Tenant B should not see Tenant A's contracts
        fetched = await repo.find_for_proof(TENANT_B, chain_id=1, contract_address="0xcafe")
        return fetched

    result = _run(run())
    assert result is None
