"""Phase — identity merge/split → semantic Gold recompute.

On merge the survivor's Gold folds in the consumed entity's observations; on split
each resulting entity is re-derived. Immutable Silver observations are never
mutated — only Gold projections are recomputed.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.identity_consumer import SemanticIdentityConsumer
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_identity"
SURVIVOR = "entity_survivor"
CONSUMED = "entity_consumed"


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


async def _seed(subject: str, content: str):
    obs, _ = await classify_event(
        {"source_event_id": f"e_{subject}_{content[:3]}", "source_type": "feedback",
         "actor_ref": "u1", "primary_subject_ref": subject, "content": content},
        TENANT,
    )
    await get_store().put_semantic(obs)


async def test_merge_folds_consumed_into_survivor_gold():
    await _seed(SURVIVOR, "great, recommend")
    await _seed(CONSUMED, "excellent, love it")
    svc = service_mod.get_semantic_service()

    await SemanticIdentityConsumer().on_identity_merged(
        Event(
            topic=Topic.IDENTITY_MERGED,
            tenant_id=TENANT,
            payload={"primary_entity_id": SURVIVOR, "secondary_entity_id": CONSUMED},
        )
    )
    gold = await svc.gold_entity_state(TENANT, SURVIVOR)
    assert gold is not None
    # Survivor Gold now reflects BOTH entities' observations.
    assert gold["observation_count"] == 2


async def test_merge_preserves_immutable_silver():
    await _seed(SURVIVOR, "great, recommend")
    await _seed(CONSUMED, "excellent")
    before = len(await get_store().list_semantic(TENANT, CONSUMED))
    await SemanticIdentityConsumer().on_identity_merged(
        Event(topic=Topic.IDENTITY_MERGED, tenant_id=TENANT,
              payload={"primary_entity_id": SURVIVOR, "secondary_entity_id": CONSUMED})
    )
    after = len(await get_store().list_semantic(TENANT, CONSUMED))
    assert before == after == 1  # source observations untouched


async def test_split_recomputes_each_entity():
    await _seed("orig_entity", "great, recommend")
    await SemanticIdentityConsumer().on_identity_split(
        Event(topic=Topic.IDENTITY_SPLIT, tenant_id=TENANT,
              payload={"original_entity_id": "orig_entity", "resulting_entity_id": "frag_entity"})
    )
    svc = service_mod.get_semantic_service()
    # Both original and fragment have Gold state recomputed from their observations.
    assert await svc.gold_entity_state(TENANT, "orig_entity") is not None
    assert await svc.gold_entity_state(TENANT, "frag_entity") is not None


async def test_merge_missing_fields_is_noop():
    await SemanticIdentityConsumer().on_identity_merged(
        Event(topic=Topic.IDENTITY_MERGED, tenant_id=TENANT, payload={})
    )
    assert await service_mod.get_semantic_service().gold_entity_state(TENANT, SURVIVOR) is None
