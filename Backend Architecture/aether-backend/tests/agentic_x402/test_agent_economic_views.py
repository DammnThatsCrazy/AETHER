"""Tests for AgentEconomicViews — budget, delegation policy, and full profile."""

from __future__ import annotations

import asyncio

import pytest

from repositories.repos import (
    AgentEconomicIdentityRepository,
    DelegationRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
    reset_in_memory_stores,
)
from services.agent.economic import AgentEconomicViews


@pytest.fixture(autouse=True)
def isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


TENANT = "t1"
AGENT = "agent-eco-1"
CHILD = "agent-eco-child"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _views():
    return AgentEconomicViews(
        payment_intents=PaymentIntentRepository(),
        settlements=SettlementEventRepository(),
        delegations=DelegationRepository(),
        identities=AgentEconomicIdentityRepository(),
    )


@pytest.mark.asyncio
async def test_budget_view_aggregates_settled_spend():
    intents = PaymentIntentRepository()
    settlements = SettlementEventRepository()

    await intents.record_intent(
        intent_id="pi-1", tenant_id=TENANT, agent_id=AGENT,
        amount="5.00", currency="USDC", provider="prov-a",
        endpoint="https://prov.io/x402",
        capability_requested="inference",
        settlement_status="settled",
    )
    await settlements.record_event(
        settlement_event_id="se-1", tenant_id=TENANT, intent_id="pi-1",
        agent_id=AGENT, status="settled", amount="5.00", currency="USDC",
        provider="prov-a", protocol="x402",
    )
    # access_granted also counts as settled spend
    await settlements.record_event(
        settlement_event_id="se-2", tenant_id=TENANT, intent_id="pi-2",
        agent_id=AGENT, status="access_granted", amount="2.50", currency="USDC",
        provider="prov-b", protocol="x402",
    )

    views = AgentEconomicViews(
        payment_intents=intents,
        settlements=settlements,
        delegations=DelegationRepository(),
        identities=AgentEconomicIdentityRepository(),
    )
    budget = await views.budget_view(AGENT, TENANT)

    assert budget["agent_id"] == AGENT
    assert budget["tenant_id"] == TENANT
    assert budget["settled_count"] == 2
    from decimal import Decimal
    assert Decimal(budget["spend_by_currency"]["USDC"]) == Decimal("7.50")


@pytest.mark.asyncio
async def test_budget_view_excludes_failed():
    settlements = SettlementEventRepository()
    await settlements.record_event(
        settlement_event_id="se-fail", tenant_id=TENANT, intent_id="pi-x",
        agent_id=AGENT, status="failed", amount="10.00", currency="USDC",
        provider="prov", protocol="x402",
    )

    views = AgentEconomicViews(
        payment_intents=PaymentIntentRepository(),
        settlements=settlements,
        delegations=DelegationRepository(),
        identities=AgentEconomicIdentityRepository(),
    )
    budget = await views.budget_view(AGENT, TENANT)
    assert budget["settled_count"] == 0
    assert "USDC" not in budget["spend_by_currency"]


@pytest.mark.asyncio
async def test_delegation_policy_view_includes_subagents():
    delegations = DelegationRepository()
    # Simulate what lifecycle mapper creates for a spawned subagent
    await delegations.grant(
        delegation_id="del-spawn-1",
        tenant_id=TENANT,
        grantor_entity_id=AGENT,
        grantee_entity_id=CHILD,
        scope={"type": "subagent", "task_id": "task-1"},
        metadata={"source": "agent_subagent_spawned"},
    )

    views = AgentEconomicViews(
        payment_intents=PaymentIntentRepository(),
        settlements=SettlementEventRepository(),
        delegations=delegations,
        identities=AgentEconomicIdentityRepository(),
    )
    policy = await views.delegation_policy_view(AGENT, TENANT)

    assert policy["subagent_count"] == 1
    assert policy["subagents"][0]["agent_id"] == CHILD
    assert policy["granted_delegation_count"] == 1


@pytest.mark.asyncio
async def test_full_economic_profile_merges_budget_and_delegations():
    intents = PaymentIntentRepository()
    settlements = SettlementEventRepository()
    delegations = DelegationRepository()
    identities = AgentEconomicIdentityRepository()

    await settlements.record_event(
        settlement_event_id="se-full", tenant_id=TENANT, intent_id="pi-full",
        agent_id=AGENT, status="settled", amount="3.00", currency="USDC",
        provider="prov", protocol="x402",
    )
    await delegations.grant(
        delegation_id="del-full",
        tenant_id=TENANT,
        grantor_entity_id=AGENT,
        grantee_entity_id=CHILD,
        scope={"type": "subagent"},
        metadata={"source": "agent_subagent_spawned"},
    )

    views = AgentEconomicViews(
        payment_intents=intents,
        settlements=settlements,
        delegations=delegations,
        identities=identities,
    )
    profile = await views.full_economic_profile(AGENT, TENANT)

    assert profile["agent_id"] == AGENT
    assert profile["budget"]["settled_count"] == 1
    assert profile["delegation_policy"]["subagent_count"] == 1
    assert "computed_at" in profile
