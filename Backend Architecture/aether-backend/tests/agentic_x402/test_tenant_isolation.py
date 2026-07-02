"""Tenant isolation tests for agentic x402 repositories.

Verifies that same agent_id / intent_id / settlement_id in two different
tenants does not leak rows across tenants.
"""

from __future__ import annotations

import pytest

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


@pytest.fixture(autouse=True)
def isolate_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


AGENT_ID = "agent-shared-id"
TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"


# ─────────────────────────────────────────────────────────────────────────────
# PaymentIntentRepository
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_intent_list_for_agent_is_tenant_scoped():
    repo = PaymentIntentRepository()
    await repo.record_intent(
        intent_id="intent-a1",
        tenant_id=TENANT_A,
        agent_id=AGENT_ID,
        amount="10.00",
        currency="USDC",
        provider="test",
    )
    await repo.record_intent(
        intent_id="intent-b1",
        tenant_id=TENANT_B,
        agent_id=AGENT_ID,
        amount="20.00",
        currency="USDC",
        provider="test",
    )

    rows_a = await repo.list_for_agent(AGENT_ID, TENANT_A)
    rows_b = await repo.list_for_agent(AGENT_ID, TENANT_B)

    assert all(r["tenant_id"] == TENANT_A for r in rows_a)
    assert all(r["tenant_id"] == TENANT_B for r in rows_b)
    assert len(rows_a) == 1 and rows_a[0]["intent_id"] == "intent-a1"
    assert len(rows_b) == 1 and rows_b[0]["intent_id"] == "intent-b1"


# ─────────────────────────────────────────────────────────────────────────────
# SettlementEventRepository
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_settlement_list_for_agent_is_tenant_scoped():
    repo = SettlementEventRepository()
    await repo.record_event(
        settlement_event_id="se-a1",
        tenant_id=TENANT_A,
        intent_id="intent-a1",
        agent_id=AGENT_ID,
        status="settled",
        amount="10.00",
        currency="USDC",
    )
    await repo.record_event(
        settlement_event_id="se-b1",
        tenant_id=TENANT_B,
        intent_id="intent-b1",
        agent_id=AGENT_ID,
        status="failed",
        amount="20.00",
        currency="USDC",
    )

    rows_a = await repo.list_for_agent(AGENT_ID, TENANT_A)
    rows_b = await repo.list_for_agent(AGENT_ID, TENANT_B)

    assert all(r["tenant_id"] == TENANT_A for r in rows_a)
    assert all(r["tenant_id"] == TENANT_B for r in rows_b)
    assert rows_a[0]["settlement_event_id"] == "se-a1"
    assert rows_b[0]["settlement_event_id"] == "se-b1"


@pytest.mark.asyncio
async def test_settlement_list_for_intent_is_tenant_scoped():
    INTENT_ID = "shared-intent-id"
    repo = SettlementEventRepository()
    await repo.record_event(
        settlement_event_id="se-a2",
        tenant_id=TENANT_A,
        intent_id=INTENT_ID,
        agent_id=AGENT_ID,
        status="settled",
        amount="5.00",
        currency="USDC",
    )
    await repo.record_event(
        settlement_event_id="se-b2",
        tenant_id=TENANT_B,
        intent_id=INTENT_ID,
        agent_id=AGENT_ID,
        status="failed",
        amount="5.00",
        currency="USDC",
    )

    rows_a = await repo.list_for_intent(INTENT_ID, TENANT_A)
    rows_b = await repo.list_for_intent(INTENT_ID, TENANT_B)

    assert all(r["tenant_id"] == TENANT_A for r in rows_a)
    assert all(r["tenant_id"] == TENANT_B for r in rows_b)
    assert rows_a[0]["settlement_event_id"] == "se-a2"
    assert rows_b[0]["settlement_event_id"] == "se-b2"


# ─────────────────────────────────────────────────────────────────────────────
# AgentEconomicIdentityRepository
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_economic_identity_is_tenant_scoped():
    repo = AgentEconomicIdentityRepository()
    await repo.upsert_identity(
        agent_id=AGENT_ID,
        tenant_id=TENANT_A,
        recurring_spend={"usdc": "100"},
    )
    await repo.upsert_identity(
        agent_id=AGENT_ID,
        tenant_id=TENANT_B,
        recurring_spend={"usdc": "999"},
    )

    rec_a = await repo.find_for_agent(AGENT_ID, TENANT_A)
    rec_b = await repo.find_for_agent(AGENT_ID, TENANT_B)

    assert rec_a is not None and rec_a["tenant_id"] == TENANT_A
    assert rec_b is not None and rec_b["tenant_id"] == TENANT_B
    assert rec_a["recurring_spend"]["usdc"] == "100"
    assert rec_b["recurring_spend"]["usdc"] == "999"


# ─────────────────────────────────────────────────────────────────────────────
# DelegationRepository
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delegation_active_for_is_tenant_scoped():
    repo = DelegationRepository()
    await repo.grant(
        delegation_id="del-a1",
        tenant_id=TENANT_A,
        grantor_entity_id="owner-a",
        grantee_entity_id=AGENT_ID,
        scope={"actions": ["*"]},
    )
    await repo.grant(
        delegation_id="del-b1",
        tenant_id=TENANT_B,
        grantor_entity_id="owner-b",
        grantee_entity_id=AGENT_ID,
        scope={"actions": ["read"]},
    )

    active_a = await repo.active_for(AGENT_ID, TENANT_A)
    active_b = await repo.active_for(AGENT_ID, TENANT_B)

    assert all(d["tenant_id"] == TENANT_A for d in active_a)
    assert all(d["tenant_id"] == TENANT_B for d in active_b)
    assert active_a[0]["delegation_id"] == "del-a1"
    assert active_b[0]["delegation_id"] == "del-b1"


# ─────────────────────────────────────────────────────────────────────────────
# AgentProfile360EconomicComposer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_profile360_composer_only_returns_tenant_local_records():
    pi_repo = PaymentIntentRepository()
    se_repo = SettlementEventRepository()
    ei_repo = AgentEconomicIdentityRepository()
    ex_repo = AgentExecutionRepository()
    del_repo = DelegationRepository()
    beh_repo = BehaviorProfileRepository()

    # Insert data for both tenants
    await pi_repo.record_intent(
        intent_id="composer-a1",
        tenant_id=TENANT_A,
        agent_id=AGENT_ID,
        amount="15.00",
        currency="USDC",
        provider="provA",
    )
    await pi_repo.record_intent(
        intent_id="composer-b1",
        tenant_id=TENANT_B,
        agent_id=AGENT_ID,
        amount="99.00",
        currency="USDC",
        provider="provB",
    )

    composer = AgentProfile360EconomicComposer(
        payment_intents=pi_repo,
        settlements=se_repo,
        economic_identities=ei_repo,
        executions=ex_repo,
        delegations=del_repo,
        behavior_profiles=beh_repo,
    )

    result_a = await composer.compose(AGENT_ID, TENANT_A)
    result_b = await composer.compose(AGENT_ID, TENANT_B)

    intent_ids_a = {e["id"] for e in result_a["temporal"]["timeline"] if e.get("type") == "payment_intent"}
    intent_ids_b = {e["id"] for e in result_b["temporal"]["timeline"] if e.get("type") == "payment_intent"}

    assert "composer-a1" in intent_ids_a
    assert "composer-b1" not in intent_ids_a
    assert "composer-b1" in intent_ids_b
    assert "composer-a1" not in intent_ids_b
