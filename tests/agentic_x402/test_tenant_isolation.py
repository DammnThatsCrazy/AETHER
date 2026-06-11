"""Tenant isolation tests for agentic x402 repositories.

Verifies that same agent_id / intent_id / settlement_id in two different
tenants does not leak rows across tenants.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    original = list(sys.path)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original


AGENT_ID = "agent-shared-id"
TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"


@pytest.mark.asyncio
async def test_payment_intent_list_for_agent_is_tenant_scoped(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import PaymentIntentRepository, reset_in_memory_stores
        reset_in_memory_stores()
        repo = PaymentIntentRepository()
        await repo.record_intent("intent-a1", TENANT_A, AGENT_ID, "10.00", "USDC", "prov")
        await repo.record_intent("intent-b1", TENANT_B, AGENT_ID, "20.00", "USDC", "prov")

        rows_a = await repo.list_for_agent(AGENT_ID, TENANT_A)
        rows_b = await repo.list_for_agent(AGENT_ID, TENANT_B)

        assert all(r["tenant_id"] == TENANT_A for r in rows_a)
        assert all(r["tenant_id"] == TENANT_B for r in rows_b)
        assert rows_a[0]["intent_id"] == "intent-a1"
        assert rows_b[0]["intent_id"] == "intent-b1"
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_settlement_list_for_agent_is_tenant_scoped(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import SettlementEventRepository, reset_in_memory_stores
        reset_in_memory_stores()
        repo = SettlementEventRepository()
        await repo.record_event("se-a1", TENANT_A, "int-a", AGENT_ID, "settled", "10.00", "USDC")
        await repo.record_event("se-b1", TENANT_B, "int-b", AGENT_ID, "failed", "20.00", "USDC")

        rows_a = await repo.list_for_agent(AGENT_ID, TENANT_A)
        rows_b = await repo.list_for_agent(AGENT_ID, TENANT_B)

        assert all(r["tenant_id"] == TENANT_A for r in rows_a)
        assert all(r["tenant_id"] == TENANT_B for r in rows_b)
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_settlement_list_for_intent_is_tenant_scoped(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import SettlementEventRepository, reset_in_memory_stores
        reset_in_memory_stores()
        INTENT = "shared-intent"
        repo = SettlementEventRepository()
        await repo.record_event("se-ia", TENANT_A, INTENT, AGENT_ID, "settled", "5.00", "USDC")
        await repo.record_event("se-ib", TENANT_B, INTENT, AGENT_ID, "failed", "5.00", "USDC")

        rows_a = await repo.list_for_intent(INTENT, TENANT_A)
        rows_b = await repo.list_for_intent(INTENT, TENANT_B)

        assert rows_a[0]["settlement_event_id"] == "se-ia"
        assert rows_b[0]["settlement_event_id"] == "se-ib"
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_agent_economic_identity_is_tenant_scoped(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import AgentEconomicIdentityRepository, reset_in_memory_stores
        reset_in_memory_stores()
        repo = AgentEconomicIdentityRepository()
        await repo.upsert_identity(AGENT_ID, TENANT_A, recurring_spend={"usdc": "100"})
        await repo.upsert_identity(AGENT_ID, TENANT_B, recurring_spend={"usdc": "999"})

        rec_a = await repo.find_for_agent(AGENT_ID, TENANT_A)
        rec_b = await repo.find_for_agent(AGENT_ID, TENANT_B)

        assert rec_a is not None and rec_a["tenant_id"] == TENANT_A
        assert rec_b is not None and rec_b["tenant_id"] == TENANT_B
        assert rec_a["recurring_spend"]["usdc"] == "100"
        assert rec_b["recurring_spend"]["usdc"] == "999"
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_delegation_active_for_is_tenant_scoped(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import DelegationRepository, reset_in_memory_stores
        reset_in_memory_stores()
        repo = DelegationRepository()
        await repo.grant("del-a1", TENANT_A, "owner-a", AGENT_ID, {"actions": ["*"]})
        await repo.grant("del-b1", TENANT_B, "owner-b", AGENT_ID, {"actions": ["read"]})

        active_a = await repo.active_for(AGENT_ID, TENANT_A)
        active_b = await repo.active_for(AGENT_ID, TENANT_B)

        assert all(d["tenant_id"] == TENANT_A for d in active_a)
        assert all(d["tenant_id"] == TENANT_B for d in active_b)
        assert active_a[0]["delegation_id"] == "del-a1"
        assert active_b[0]["delegation_id"] == "del-b1"
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_profile360_composer_tenant_isolation(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import (
            AgentEconomicIdentityRepository,
            AgentExecutionRepository,
            BehaviorProfileRepository,
            DelegationRepository,
            PaymentIntentRepository,
            SettlementEventRepository,
            reset_in_memory_stores,
        )
        from services.profile.economic import AgentProfile360EconomicComposer
        reset_in_memory_stores()

        pi_repo = PaymentIntentRepository()
        await pi_repo.record_intent("ci-a1", TENANT_A, AGENT_ID, "15.00", "USDC", "provA")
        await pi_repo.record_intent("ci-b1", TENANT_B, AGENT_ID, "99.00", "USDC", "provB")

        composer = AgentProfile360EconomicComposer(
            payment_intents=pi_repo,
            settlements=SettlementEventRepository(),
            economic_identities=AgentEconomicIdentityRepository(),
            executions=AgentExecutionRepository(),
            delegations=DelegationRepository(),
            behavior_profiles=BehaviorProfileRepository(),
        )

        result_a = await composer.compose(AGENT_ID, TENANT_A)
        result_b = await composer.compose(AGENT_ID, TENANT_B)

        ids_a = {e["id"] for e in result_a["temporal"]["timeline"] if e.get("type") == "payment_intent"}
        ids_b = {e["id"] for e in result_b["temporal"]["timeline"] if e.get("type") == "payment_intent"}

        assert "ci-a1" in ids_a and "ci-b1" not in ids_a
        assert "ci-b1" in ids_b and "ci-a1" not in ids_b
        reset_in_memory_stores()
