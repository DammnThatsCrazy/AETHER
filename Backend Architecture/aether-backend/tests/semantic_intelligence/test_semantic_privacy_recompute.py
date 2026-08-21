"""Consent retraction / actor-erasure must recompute affected Gold aggregates.

Tombstoning/deleting a revoked actor's Silver rows is not enough: the durable
Gold state (``gold_entity_semantic_state``) keeps reflecting the retracted data
until it is recomputed. A revoked actor's contribution must also drop out of the
aggregates of the OTHER subjects it acted on.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.privacy import SemanticPrivacyHandler
from services.semantic_intelligence.reducers import (
    recompute_entity_sentiment,
    recompute_entity_state,
)
from services.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore


async def _gold_sentiment(ref: str) -> dict | None:
    """Read an entity's durable Gold sentiment state (if any)."""
    rows = await SemanticFactRepository("gold_entity_sentiment_state").list_by_tenant(
        TENANT, ref, limit=1
    )
    return rows[0] if rows else None

TENANT = "tenant_retract"
ACTOR_A = "user_A"
SUBJECT_B = "prod_B"
ACTOR_C = "user_C"


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


async def _seed(actor: str, subject: str, event: str) -> None:
    obs, sentiments = await classify_event(
        {
            "source_event_id": event,
            "source_type": "feedback",
            "actor_ref": actor,
            "primary_subject_ref": subject,
            "content": "great excellent recommend",
        },
        TENANT,
    )
    store = get_store()
    await store.put_semantic(obs)
    for s in sentiments:
        await store.put_sentiment(s)


async def _seed_world() -> None:
    """A acts on itself and on B; C also acts on B (an independent contribution)."""
    await _seed(ACTOR_A, ACTOR_A, "e_a_self")
    await _seed(ACTOR_A, SUBJECT_B, "e_a_on_b")
    await _seed(ACTOR_C, SUBJECT_B, "e_c_on_b")
    # Persist Gold (state + sentiment) for both entities from the full evidence set.
    await recompute_entity_state(TENANT, ACTOR_A)
    await recompute_entity_state(TENANT, SUBJECT_B)
    await recompute_entity_sentiment(TENANT, ACTOR_A)
    await recompute_entity_sentiment(TENANT, SUBJECT_B)


async def test_restriction_recomputes_gold_for_actor_and_touched_subjects():
    await _seed_world()
    svc = service_mod.get_semantic_service()

    # Baseline: B's Gold reflects BOTH A's and C's contributions.
    gold_b = await svc.gold_entity_state(TENANT, SUBJECT_B)
    assert gold_b is not None
    assert "2 weighted observations" in gold_b["semantic_summary"]

    result = await SemanticPrivacyHandler().handle_restriction(TENANT, ACTOR_A)
    assert result["completed"] is True
    assert result["recomputed"] >= 1

    # A's own aggregate collapses to insufficient_data (its rows are restricted).
    gold_a = await svc.gold_entity_state(TENANT, ACTOR_A)
    assert gold_a is not None
    assert gold_a["semantic_summary"] == "insufficient_data"

    # B's aggregate is recomputed WITHOUT A's contribution (only C remains active).
    gold_b_after = await svc.gold_entity_state(TENANT, SUBJECT_B)
    assert gold_b_after is not None
    assert "1 weighted observations" in gold_b_after["semantic_summary"]

    # Sentiment Gold must drop the retracted contribution too (the reducer now
    # honors consent_restricted status). A collapses to insufficient_data; B keeps
    # only C's active sentiment.
    sent_a = await _gold_sentiment(ACTOR_A)
    assert sent_a is not None and sent_a["insufficient_data"] is True
    sent_b = await _gold_sentiment(SUBJECT_B)
    assert sent_b is not None and sent_b["insufficient_data"] is False


async def test_erasure_recomputes_others_and_leaves_actor_gold_deleted():
    await _seed_world()
    svc = service_mod.get_semantic_service()
    assert await svc.gold_entity_state(TENANT, ACTOR_A) is not None

    result = await SemanticPrivacyHandler().handle_erasure(TENANT, ACTOR_A)
    assert result["completed"] is True
    assert result["recomputed"] >= 1

    # B is recomputed without A's (now deleted) contribution.
    gold_b_after = await svc.gold_entity_state(TENANT, SUBJECT_B)
    assert gold_b_after is not None
    assert "1 weighted observations" in gold_b_after["semantic_summary"]

    # A's Gold row is GONE — erasure deleted it and recompute must NOT recreate it.
    assert await svc.gold_entity_state(TENANT, ACTOR_A) is None
