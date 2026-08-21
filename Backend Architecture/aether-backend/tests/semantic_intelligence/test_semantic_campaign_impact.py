"""Phase C·2 — durable weighted campaign semantic impact (Gold).

Proves campaign impact is weighted, durably persisted, produced by the worker,
and served from Gold — with causal language kept bounded.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.consumer import SemanticEventConsumer
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.reducers import REDUCER_VERSION, reduce_campaign_impact
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_campaign"
CAMPAIGN = "camp_c2"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


async def _obs(actor: str, content: str):
    obs, _ = await classify_event(
        {
            "source_event_id": f"e_{actor}",
            "source_type": "feedback",
            "actor_ref": actor,
            "primary_subject_ref": "prod_1",
            "campaign_id": CAMPAIGN,
            "content": content,
        },
        TENANT,
    )
    return obs


async def test_reduce_campaign_impact_bounds_causal_language():
    impact = reduce_campaign_impact(TENANT, CAMPAIGN, [await _obs("a1", "great, recommend")])
    assert impact["causal_confidence"] == "observed_sequence"
    assert impact["semantic_mediated_revenue_estimate"] is None
    assert impact["reducer_version"] == REDUCER_VERSION
    assert impact["insufficient_data"] is False


async def test_reduce_is_weighted():
    impact = reduce_campaign_impact(
        TENANT, CAMPAIGN, [await _obs("a1", "great, recommend"), await _obs("a2", "bad, oppose")]
    )
    # Weighted floats summing to ~1 across stances (not raw counts).
    assert abs(sum(impact["stance_distribution"].values()) - 1.0) < 0.05


async def test_recompute_persists_and_service_reads_gold():
    svc = service_mod.get_semantic_service()
    store = get_store()
    await store.put_semantic(await _obs("a1", "great, recommend"))
    impact = await svc.recompute_campaign_impact(TENANT, CAMPAIGN)
    assert impact["observation_count"] == 1

    gold = await svc.campaign_impact(TENANT, CAMPAIGN)
    assert gold["campaign_id"] == CAMPAIGN
    assert gold["reducer_version"] == REDUCER_VERSION


async def test_worker_produces_campaign_gold():
    ev = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_id": "e_cg",
            "event_type": "feedback_submitted",
            "user_id": "u1",
            "campaign_id": CAMPAIGN,
            "properties": {"content": "great product, I recommend it", "product_id": "prod_1"},
        },
    )
    await SemanticEventConsumer().on_validated_event(ev)
    from services.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository

    gold = await SemanticFactRepository("gold_campaign_semantic_impact").list_by_tenant(
        TENANT, CAMPAIGN, limit=1
    )
    assert gold and gold[0]["campaign_id"] == CAMPAIGN
