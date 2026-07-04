from __future__ import annotations

import importlib
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) in sys.path:
    sys.path.remove(str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def local_repositories(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    settings_mod = sys.modules.get("config.settings")
    if settings_mod is not None and not hasattr(settings_mod, "settings"):
        sys.modules.pop("config.settings", None)
        sys.modules.pop("config", None)
    repos = importlib.import_module("repositories.repos")
    repos.reset_in_memory_stores()
    activity_repo_mod = importlib.import_module("services.measurement.repositories.activity_repo")
    activity_repo_mod._local_store.clear()
    yield
    repos.reset_in_memory_stores()
    activity_repo_mod._local_store.clear()


def test_agentic_noesis_inventory_uses_observed_facts():
    repos = importlib.import_module("repositories.agentic_observability_repos")
    adapter_mod = importlib.import_module("services.noesis.adapters.agentic_intelligence_adapter")

    asyncio.run(repos.AgentActivityRepository().insert("act-1", {"tenant_id": "tenant-a", "agent_id": "agent-1", "event_type": "agent_registered"}))
    asyncio.run(repos.AgentActivityRepository().insert("act-2", {"tenant_id": "tenant-b", "agent_id": "agent-2", "event_type": "agent_registered"}))

    answer = asyncio.run(adapter_mod.AgenticIntelligenceAdapter().answer(intent="agent_inventory_lookup", tenant_id="tenant-a"))

    assert answer.answer == "Found 1 observed agents in tenant scope."
    assert answer.results[0]["agent_id"] == "agent-1"
    assert answer.results[0]["evidence_classification"] == "observed_fact"
    assert answer.claims[0]["classification"] == "deterministic_computation"


def test_agentic_noesis_provider_verification_labels_provider_truth():
    repos = importlib.import_module("repositories.agentic_observability_repos")
    adapter_mod = importlib.import_module("services.noesis.adapters.agentic_intelligence_adapter")

    asyncio.run(repos.AgentToolRepository().insert(
        "tool-1",
        {"tenant_id": "tenant-a", "agent_id": "agent-1", "verification_status": "provider_confirmed", "external_object_id": "post-1"},
    ))

    answer = asyncio.run(adapter_mod.AgenticIntelligenceAdapter().answer(intent="provider_verification_lookup", tenant_id="tenant-a"))

    assert answer.results[0]["evidence_classification"] == "provider_confirmed_fact"
    assert answer.claims[0]["classification"] == "provider_confirmed_fact"


def test_agentic_noesis_mismatch_filters_contradictions():
    repos = importlib.import_module("repositories.agentic_observability_repos")
    adapter_mod = importlib.import_module("services.noesis.adapters.agentic_intelligence_adapter")

    asyncio.run(repos.AgentToolRepository().insert("ok", {"tenant_id": "tenant-a", "verification_status": "provider_confirmed"}))
    asyncio.run(repos.AgentToolRepository().insert("bad", {"tenant_id": "tenant-a", "verification_status": "contradicted", "contradiction_reason": "provider_snapshot_mismatch"}))

    answer = asyncio.run(adapter_mod.AgenticIntelligenceAdapter().answer(intent="verification_mismatch_lookup", tenant_id="tenant-a"))

    assert len(answer.results) == 1
    assert answer.results[0]["id"] == "bad"
    assert answer.results[0]["evidence_classification"] == "provider_confirmed_fact"


def test_noesis_classifier_routes_agentic_intents():
    models = importlib.import_module("services.noesis.models")
    service_mod = importlib.import_module("services.noesis.service")

    service = service_mod.NoesisService(graph=object(), analytics=object())
    scope = service_mod.Scope(surface="aether", effective_tenant_id="tenant-a", cross_tenant=False, debug_allowed=False)

    plan = service._classify(models.NoesisQueryRequest(message="Which agents can post to X?", surface="aether"), scope)
    assert plan.intent in {"authorization_lookup", "agent_inventory_lookup"}

    plan = service._classify(models.NoesisQueryRequest(message="Which actions are not provider-confirmed?", surface="aether"), scope)
    assert plan.intent == "verification_mismatch_lookup"

    assert "provider_verification_lookup" in models.SUPPORTED_INTENTS


def test_agentic_noesis_product_surface_intents_use_read_models():
    repos = importlib.import_module("repositories.agentic_observability_repos")
    activity_repo_mod = importlib.import_module("services.measurement.repositories.activity_repo")
    adapter_mod = importlib.import_module("services.noesis.adapters.agentic_intelligence_adapter")

    asyncio.run(repos.AgentToolRepository().insert(
        "tool-1",
        {
            "tenant_id": "tenant-a",
            "agent_id": "agent-1",
            "verification_status": "provider_confirmed",
            "external_object_id": "post-1",
        },
    ))
    activity_repo_mod._local_store["tenant-a:agentic-idem-1"] = {
        "tenant_id": "tenant-a",
        "idempotency_key": "agentic-idem-1",
        "activity_id": "activity-1",
        "source_system": "agentic_observability",
        "source_event_id": "event-1",
        "agent_id": "agent-1",
        "campaign_id": "camp-1",
        "activity_type": "tool_invocation_observed",
        "activity_status": "observed",
        "occurred_at": "2026-07-04T00:00:00+00:00",
    }

    profile = asyncio.run(adapter_mod.AgenticIntelligenceAdapter().answer(
        intent="agent_profile360_lookup",
        tenant_id="tenant-a",
        target="agent-1",
    ))
    assert profile.results[0]["profile_type"] == "agent_profile_360"
    assert profile.claims[0]["classification"] == "deterministic_computation"

    journey = asyncio.run(adapter_mod.AgenticIntelligenceAdapter().answer(
        intent="journey_agentic_steps_lookup",
        tenant_id="tenant-a",
        target="agent-1",
    ))
    assert journey.results[0]["step_id"] == "activity-1"
    assert journey.claims[0]["classification"] == "observed_fact"

    campaign = asyncio.run(adapter_mod.AgenticIntelligenceAdapter().answer(
        intent="campaign_agentic_influence_lookup",
        tenant_id="tenant-a",
        target="camp-1",
    ))
    assert campaign.results[0]["agentic_touchpoint_count"] == 1
    assert campaign.results[0]["attribution_status"] == "eligible_for_modeling"
