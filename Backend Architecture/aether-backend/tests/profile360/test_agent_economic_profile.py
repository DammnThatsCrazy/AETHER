"""Profile360 economic telemetry and repository smoke tests."""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from repositories.repos import (  # noqa: E402
    AgentEconomicIdentityRepository,
    EconomicResourceRepository,
    FacilitatorRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
)
from services.profile.economic import AgentProfile360EconomicComposer  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_economic_repositories_capture_agent_payment_flow():
    intents = PaymentIntentRepository()
    settlements = SettlementEventRepository()
    resources = EconomicResourceRepository()
    facilitators = FacilitatorRepository()
    identities = AgentEconomicIdentityRepository()

    _run(resources.upsert_resource(
        resource_id="res_gpu",
        tenant_id="t1",
        resource_type="gpu_compute",
        provider="compute-co",
        capability="batch_inference",
        protocol="x402",
        endpoint="https://compute.example/x402",
    ))
    _run(facilitators.upsert_facilitator(
        facilitator_id="fac_x402",
        tenant_id="t1",
        name="x402 Facilitator",
        facilitator_type="x402",
        protocols=["x402"],
        trust_score=0.99,
    ))
    _run(intents.record_intent(
        intent_id="pi_1",
        tenant_id="t1",
        agent_id="agent_1",
        amount="2.50",
        currency="USDC",
        provider="compute-co",
        protocol="x402",
        endpoint="https://compute.example/x402",
        capability_requested="batch_inference",
        settlement_status="settled",
        resource_id="res_gpu",
        facilitator_id="fac_x402",
    ))
    _run(settlements.record_event(
        settlement_event_id="se_1",
        tenant_id="t1",
        intent_id="pi_1",
        agent_id="agent_1",
        status="settled",
        amount="2.50",
        currency="USDC",
        provider="compute-co",
        protocol="x402",
        facilitator_id="fac_x402",
    ))
    _run(identities.upsert_identity(
        agent_id="agent_1",
        tenant_id="t1",
        recurring_spend={"USDC": {"total_spend": 2.5, "total_revenue": 0}},
        provider_preferences=[{"id": "compute-co", "count": 1}],
        capability_preferences=[{"id": "batch_inference", "count": 1}],
        protocol_affinity=[{"id": "x402", "count": 1}],
        specialization_patterns=["batch_inference"],
    ))

    assert _run(resources.find_by_id("res_gpu"))["resource_type"] == "gpu_compute"
    assert _run(facilitators.find_by_id("fac_x402"))["protocols"] == ["x402"]
    assert len(_run(intents.list_for_agent("agent_1"))) == 1
    assert len(_run(settlements.list_for_agent("agent_1"))) == 1
    assert _run(identities.find_for_agent("agent_1", "t1"))["provider_preferences"][0]["id"] == "compute-co"


def test_agent_profile360_economic_composer_returns_frontend_ready_sections():
    intents = PaymentIntentRepository()
    settlements = SettlementEventRepository()
    identities = AgentEconomicIdentityRepository()

    _run(intents.record_intent(
        intent_id="pi_2",
        tenant_id="t1",
        agent_id="agent_2",
        amount="1.25",
        currency="USD",
        provider="api-co",
        protocol="https",
        endpoint="https://api.example/v1/search",
        capability_requested="api_access",
        settlement_status="abandoned",
        abandoned_reason="price_above_threshold",
    ))
    _run(settlements.record_event(
        settlement_event_id="se_2",
        tenant_id="t1",
        intent_id="pi_2",
        agent_id="agent_2",
        status="failed",
        amount="1.25",
        currency="USD",
        provider="api-co",
        protocol="https",
        failure_reason="timeout",
    ))
    _run(identities.upsert_identity(
        agent_id="agent_2",
        tenant_id="t1",
        provider_preferences=[{"id": "api-co", "count": 1}],
        capability_preferences=[{"id": "api_access", "count": 1}],
        protocol_affinity=[{"id": "https", "count": 1}],
        failure_rates={"api-co": 1.0},
    ))

    composer = AgentProfile360EconomicComposer(
        payment_intents=intents,
        settlements=settlements,
        economic_identities=identities,
    )
    profile = _run(composer.compose("agent_2", "t1"))

    assert profile["economic"]["payment_intent_count"] == 1
    assert profile["economic"]["abandoned_value_by_currency"] == {"USD": "1.25"}
    assert profile["trust"]["failed_settlements"] == 1
    assert profile["communication"]["endpoints"][0]["id"] == "https://api.example/v1/search"
    assert {"from": "agent_2", "to": "pi_2", "type": "PAYS_FOR"} in profile["graph"]["edges"]
