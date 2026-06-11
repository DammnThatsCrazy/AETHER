"""Tests for X402LifecycleMapper — canonical event → repository routing."""

from __future__ import annotations

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


TENANT = "test-tenant"
AGENT = "agent-xyz"


@pytest.mark.asyncio
async def test_x402_payment_intent_created_writes_intent(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import (
            AgentEconomicIdentityRepository,
            EconomicResourceRepository,
            FacilitatorRepository,
            PaymentIntentRepository,
            SettlementEventRepository,
            reset_in_memory_stores,
        )
        from services.x402.lifecycle_mapper import X402LifecycleMapper
        reset_in_memory_stores()
        pi_repo = PaymentIntentRepository()
        mapper = X402LifecycleMapper(
            payment_intents=pi_repo,
            settlements=SettlementEventRepository(),
            resources=EconomicResourceRepository(),
            facilitators=FacilitatorRepository(),
            identities=AgentEconomicIdentityRepository(),
        )
        result = await mapper.handle_event(
            "x402_payment_intent_created",
            {"payment_intent_id": "pi-001", "agent_id": AGENT,
             "amount": "5.00", "currency": "USDC", "provider": "coinbase"},
            TENANT,
        )
        assert result is not None
        rows = await pi_repo.list_for_agent(AGENT, TENANT)
        assert any(r["intent_id"] == "pi-001" for r in rows)
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_x402_payment_settled_writes_settlement(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import (
            AgentEconomicIdentityRepository,
            EconomicResourceRepository,
            FacilitatorRepository,
            PaymentIntentRepository,
            SettlementEventRepository,
            reset_in_memory_stores,
        )
        from services.x402.lifecycle_mapper import X402LifecycleMapper
        reset_in_memory_stores()
        pi_repo = PaymentIntentRepository()
        se_repo = SettlementEventRepository()
        mapper = X402LifecycleMapper(
            payment_intents=pi_repo, settlements=se_repo,
            resources=EconomicResourceRepository(),
            facilitators=FacilitatorRepository(),
            identities=AgentEconomicIdentityRepository(),
        )
        await mapper.handle_event(
            "x402_payment_intent_created",
            {"payment_intent_id": "pi-002", "agent_id": AGENT,
             "amount": "3.00", "currency": "USDC", "provider": "stripe"},
            TENANT,
        )
        await mapper.handle_event(
            "x402_payment_settled",
            {"settlement_event_id": "se-002", "payment_intent_id": "pi-002",
             "agent_id": AGENT, "amount": "3.00", "currency": "USDC"},
            TENANT,
        )
        rows = await se_repo.list_for_intent("pi-002", TENANT)
        assert any(r["settlement_event_id"] == "se-002" and r["status"] == "settled" for r in rows)
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_x402_payment_failed_writes_failure(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import (
            AgentEconomicIdentityRepository,
            EconomicResourceRepository,
            FacilitatorRepository,
            PaymentIntentRepository,
            SettlementEventRepository,
            reset_in_memory_stores,
        )
        from services.x402.lifecycle_mapper import X402LifecycleMapper
        reset_in_memory_stores()
        pi_repo = PaymentIntentRepository()
        se_repo = SettlementEventRepository()
        mapper = X402LifecycleMapper(
            payment_intents=pi_repo, settlements=se_repo,
            resources=EconomicResourceRepository(),
            facilitators=FacilitatorRepository(),
            identities=AgentEconomicIdentityRepository(),
        )
        await mapper.handle_event(
            "x402_payment_intent_created",
            {"payment_intent_id": "pi-003", "agent_id": AGENT,
             "amount": "1.00", "currency": "USDC", "provider": "test"},
            TENANT,
        )
        await mapper.handle_event(
            "x402_payment_failed",
            {"settlement_event_id": "se-003", "payment_intent_id": "pi-003",
             "agent_id": AGENT, "amount": "1.00", "currency": "USDC",
             "failure_reason": "insufficient_funds"},
            TENANT,
        )
        rows = await se_repo.list_for_intent("pi-003", TENANT)
        failed = [r for r in rows if r["settlement_event_id"] == "se-003"]
        assert failed and failed[0]["status"] == "failed"
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_x402_payment_legacy_normalizes(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import (
            AgentEconomicIdentityRepository,
            EconomicResourceRepository,
            FacilitatorRepository,
            PaymentIntentRepository,
            SettlementEventRepository,
            reset_in_memory_stores,
        )
        from services.x402.lifecycle_mapper import X402LifecycleMapper
        reset_in_memory_stores()
        se_repo = SettlementEventRepository()
        mapper = X402LifecycleMapper(
            payment_intents=PaymentIntentRepository(), settlements=se_repo,
            resources=EconomicResourceRepository(),
            facilitators=FacilitatorRepository(),
            identities=AgentEconomicIdentityRepository(),
        )
        result = await mapper.handle_event(
            "x402_payment",
            {"payment_intent_id": "pi-legacy", "settlement_event_id": "se-legacy",
             "agent_id": AGENT, "amount": "1.50", "currency": "USDC", "provider": "old"},
            TENANT,
        )
        assert result is not None
        rows = await se_repo.list_for_agent(AGENT, TENANT)
        assert len(rows) >= 1
        reset_in_memory_stores()


@pytest.mark.asyncio
async def test_mapper_tenant_isolation(monkeypatch):
    with backend_path(monkeypatch):
        from repositories.repos import (
            AgentEconomicIdentityRepository,
            EconomicResourceRepository,
            FacilitatorRepository,
            PaymentIntentRepository,
            SettlementEventRepository,
            reset_in_memory_stores,
        )
        from services.x402.lifecycle_mapper import X402LifecycleMapper
        reset_in_memory_stores()
        pi_repo = PaymentIntentRepository()
        mapper = X402LifecycleMapper(
            payment_intents=pi_repo, settlements=SettlementEventRepository(),
            resources=EconomicResourceRepository(),
            facilitators=FacilitatorRepository(),
            identities=AgentEconomicIdentityRepository(),
        )
        await mapper.handle_event(
            "x402_payment_intent_created",
            {"payment_intent_id": "pi-iso-a", "agent_id": AGENT,
             "amount": "4.00", "currency": "USDC", "provider": "iso"},
            "tenant-iso-a",
        )
        await mapper.handle_event(
            "x402_payment_intent_created",
            {"payment_intent_id": "pi-iso-b", "agent_id": AGENT,
             "amount": "5.00", "currency": "USDC", "provider": "iso"},
            "tenant-iso-b",
        )
        rows_a = await pi_repo.list_for_agent(AGENT, "tenant-iso-a")
        rows_b = await pi_repo.list_for_agent(AGENT, "tenant-iso-b")
        assert all(r["tenant_id"] == "tenant-iso-a" for r in rows_a)
        assert all(r["tenant_id"] == "tenant-iso-b" for r in rows_b)
        reset_in_memory_stores()
