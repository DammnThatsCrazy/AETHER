"""Phase C — durable Gold cascade persistence.

``engine.cascades_for_tenant`` stays the single live computation;
``recompute_cascades`` makes its result durable in gold_semantic_cascades with
content-derived ids (idempotent refresh, never duplication) and is wired into
the service-level entity recompute path.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.reducers import REDUCER_VERSION, recompute_cascades
from services.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_cascade_gold"
SUBJECT = "prod_cascade"


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


async def _seed(actor: str):
    # Shared (subject, topic, stance) across ≥2 actors → one live cascade.
    obs, _ = await classify_event(
        {
            "source_event_id": f"e_{actor}",
            "source_type": "social_post",
            "actor_ref": actor,
            "primary_subject_ref": SUBJECT,
            "content": "I support this product",
        },
        TENANT,
    )
    await get_store().put_semantic(obs)


async def test_empty_tenant_persists_no_rows():
    cascades = await recompute_cascades(TENANT)
    assert cascades == []
    assert await SemanticFactRepository("gold_semantic_cascades").list_by_tenant(TENANT) == []


async def test_recompute_persists_live_cascades_to_gold():
    await _seed("profile_a")
    await _seed("profile_b")
    cascades = await recompute_cascades(TENANT)
    assert cascades and cascades[0].breadth == 2

    gold = await SemanticFactRepository("gold_semantic_cascades").list_by_tenant(TENANT, SUBJECT)
    assert len(gold) == len(cascades)
    assert gold[0]["reducer_version"] == REDUCER_VERSION
    assert gold[0]["cascade_id"] == cascades[0].cascade_id
    assert gold[0]["causal_confidence"] == "observed_sequence"


async def test_recompute_is_idempotent_refresh():
    await _seed("profile_a")
    await _seed("profile_b")
    first = await recompute_cascades(TENANT)
    second = await recompute_cascades(TENANT)
    assert {c.cascade_id for c in first} == {c.cascade_id for c in second}
    gold = await SemanticFactRepository("gold_semantic_cascades").list_by_tenant(TENANT, SUBJECT)
    assert len(gold) == len(first)  # refreshed in place, not duplicated


async def test_service_entity_recompute_refreshes_cascade_gold():
    await _seed("profile_a")
    await _seed("profile_b")
    await service_mod.get_semantic_service().recompute_entity_state(TENANT, SUBJECT)
    gold = await SemanticFactRepository("gold_semantic_cascades").list_by_tenant(TENANT, SUBJECT)
    assert gold and gold[0]["subject_ref"] == SUBJECT
