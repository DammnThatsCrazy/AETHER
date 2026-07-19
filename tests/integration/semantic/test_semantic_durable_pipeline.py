"""Integration: the semantic pipeline runs on a durable store, not a singleton.

Root-suite coverage (runs under ``pytest tests/``, the CI core gate) proving the
Phase A1 spine end-to-end: classify → durably persist → read back via a fresh
store instance (restart-survival), idempotent replay, and computed operator
health. This is the behavioural anti-pattern check the mono-prompt requires.
"""

from __future__ import annotations

TENANT = "tenant_integration_semantic"

_FEEDBACK = {
    "source_event_id": "evt_integration_1",
    "source_type": "feedback",
    "actor_ref": "user_int_1",
    "actor_type": "profile",
    "primary_subject_ref": "product_int_1",
    "target_type": "product",
    "content": "excellent support and great quality, I recommend it",
    "language": "en",
}


async def test_pipeline_persists_and_survives_restart():
    from services.semantic_intelligence.engine import set_store
    from services.semantic_intelligence.service import SemanticIntelligenceService
    from services.semantic_intelligence.store import DurableSemanticSentimentStore

    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(_FEEDBACK, TENANT)
    assert obs.observation_id
    assert sentiments and sentiments[0].valence > 0

    # Simulate a process restart: a fresh store + service must still see the row.
    set_store(DurableSemanticSentimentStore())
    rows, _ = await SemanticIntelligenceService().list_observations(TENANT, "product_int_1")
    assert len(rows) == 1
    assert rows[0].observation_id == obs.observation_id


async def test_pipeline_is_idempotent_and_health_is_computed():
    from services.semantic_intelligence.service import SemanticIntelligenceService

    svc = SemanticIntelligenceService()
    await svc.classify_and_persist(_FEEDBACK, TENANT)
    await svc.classify_and_persist(_FEEDBACK, TENANT)  # replay
    rows, _ = await svc.list_observations(TENANT, "product_int_1", limit=100)
    assert len(rows) == 1

    health = await svc.fleet_health()
    assert health["classified_observations"] == 1
    assert health["enabled_tenants"] == 1


async def test_cross_tenant_reads_are_isolated():
    from services.semantic_intelligence.service import SemanticIntelligenceService

    svc = SemanticIntelligenceService()
    await svc.classify_and_persist(_FEEDBACK, TENANT)
    other, _ = await svc.list_observations("some_other_tenant", "product_int_1")
    assert other == []
