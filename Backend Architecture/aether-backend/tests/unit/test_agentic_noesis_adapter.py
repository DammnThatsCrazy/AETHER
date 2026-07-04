from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")

import pytest
from repositories.repos import reset_in_memory_stores


def setup_function() -> None:
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_agent_inventory_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("agent_inventory_lookup", "tenant-a")
    assert result.intent == "agent_inventory_lookup"
    assert any(c["classification"] == "observed_fact" for c in result.claims)
    assert "obs_agent_activities" in result.sources


@pytest.mark.asyncio
async def test_agent_activity_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("agent_activity_lookup", "tenant-a", target="agent-1")
    assert result.intent == "agent_activity_lookup"
    assert any(c["classification"] == "observed_fact" for c in result.claims)


@pytest.mark.asyncio
async def test_agent_path_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("agent_path_lookup", "tenant-a", target="agent-1")
    assert result.intent == "agent_path_lookup"


@pytest.mark.asyncio
async def test_mcp_topology_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("mcp_topology_lookup", "tenant-a")
    assert result.intent == "mcp_topology_lookup"
    assert "obs_agent_connections" in result.sources


@pytest.mark.asyncio
async def test_authorization_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("authorization_lookup", "tenant-a")
    assert result.intent == "authorization_lookup"


@pytest.mark.asyncio
async def test_provider_verification_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("provider_verification_lookup", "tenant-a")
    assert result.intent == "provider_verification_lookup"
    assert any(c["classification"] == "provider_confirmed_fact" for c in result.claims)


@pytest.mark.asyncio
async def test_verification_mismatch_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("verification_mismatch_lookup", "tenant-a")
    assert result.intent == "verification_mismatch_lookup"


@pytest.mark.asyncio
async def test_permission_risk_lookup():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("permission_risk_lookup", "tenant-a")
    assert result.intent == "permission_risk_lookup"
    assert "obs_agent_risk_signals" in result.sources


@pytest.mark.asyncio
async def test_agent_profile360_lookup_no_target():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("agent_profile360_lookup", "tenant-a", target=None)
    assert any(c["classification"] == "insufficient_evidence" for c in result.claims)
    assert any(not c["sufficient"] for c in result.claims)


@pytest.mark.asyncio
async def test_agent_profile360_lookup_with_target():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("agent_profile360_lookup", "tenant-a", target="agent-1")
    assert result.intent == "agent_profile360_lookup"
    assert any(c["classification"] == "observed_fact" for c in result.claims)


@pytest.mark.asyncio
async def test_journey_agentic_steps_no_target():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("journey_agentic_steps_lookup", "tenant-a", target=None)
    assert any(c["classification"] == "insufficient_evidence" for c in result.claims)


@pytest.mark.asyncio
async def test_campaign_agentic_influence_no_target():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("campaign_agentic_influence_lookup", "tenant-a", target=None)
    assert any(c["classification"] == "insufficient_evidence" for c in result.claims)


@pytest.mark.asyncio
async def test_unknown_intent_returns_insufficient_evidence():
    from services.noesis.adapters.agentic_intelligence_adapter import AgenticIntelligenceAdapter
    adapter = AgenticIntelligenceAdapter()
    result = await adapter.answer("make_up_intent_xyz", "tenant-a")
    assert any(c["classification"] == "insufficient_evidence" for c in result.claims)
    assert len(result.warnings) > 0


@pytest.mark.asyncio
async def test_all_11_intents_use_valid_classifications():
    from services.noesis.adapters.agentic_intelligence_adapter import (
        AgenticIntelligenceAdapter,
        AGENTIC_EVIDENCE_CLASSIFICATIONS,
    )
    adapter = AgenticIntelligenceAdapter()
    intents = [
        "agent_inventory_lookup",
        "agent_activity_lookup",
        "agent_path_lookup",
        "mcp_topology_lookup",
        "authorization_lookup",
        "provider_verification_lookup",
        "verification_mismatch_lookup",
        "permission_risk_lookup",
        "agent_profile360_lookup",
        "journey_agentic_steps_lookup",
        "campaign_agentic_influence_lookup",
    ]
    for intent in intents:
        result = await adapter.answer(intent, "tenant-a", target="agent-1")
        assert result.intent == intent, f"Intent mismatch for {intent}"
        for claim in result.claims:
            assert claim["classification"] in AGENTIC_EVIDENCE_CLASSIFICATIONS, (
                f"Invalid classification {claim['classification']!r} for intent {intent}"
            )
