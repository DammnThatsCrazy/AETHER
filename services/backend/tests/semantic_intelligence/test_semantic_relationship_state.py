"""Phase C — durable weighted Gold relationship state (semantic + sentiment).

The (source, target) pair is derived from actor_ref → primary_subject_ref: an
actor expressing stance about a subject IS the relationship. Proves the reducer
aggregates with the multiplicative weighting policy, persists to the two gold
relationship tables with reducer version + provenance, and never fabricates a
row for an unobserved pair.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.models import (
    EvidenceRef,
    IntentLabel,
    PropagationRole,
    SemanticObservation,
    StanceLabel,
    SubjectType,
    utc_now,
)
from services.semantic_intelligence.reducers import (
    REDUCER_VERSION,
    recompute_relationship_sentiment,
    recompute_relationship_state,
    reduce_relationship_sentiment,
    reduce_relationship_state,
    relationship_ref,
)
from services.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_relationship"
SOURCE = "profile_alice"
TARGET = "prod_rel"


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


def _obs(stance: StanceLabel, *, conf: float = 0.9, age_days: float = 0.0) -> SemanticObservation:
    return SemanticObservation(
        tenant_id=TENANT,
        source_event_id=f"e_{SOURCE}_{stance.value}_{age_days}",
        source_type="feedback",
        actor_ref=SOURCE,
        actor_type=SubjectType.PROFILE,
        primary_subject_ref=TARGET,
        target_type=SubjectType.PRODUCT,
        stance=stance,
        intent=IntentLabel.EVALUATE,
        classification_confidence=conf,
        occurred_at=utc_now() - timedelta(days=age_days),
        evidence_refs=[EvidenceRef(evidence_id="e", source_type="event", source_ref="e")],
    )


async def _seed(content: str, *, event_id: str = "e_rel"):
    obs, sentiments = await classify_event(
        {
            "source_event_id": event_id,
            "source_type": "feedback",
            "actor_ref": SOURCE,
            "primary_subject_ref": TARGET,
            "content": content,
        },
        TENANT,
    )
    store = get_store()
    await store.put_semantic(obs)
    for s in sentiments:
        await store.put_sentiment(s)


def test_insufficient_relationship():
    state = reduce_relationship_state(TENANT, SOURCE, TARGET, [])
    assert state.interaction_quality == "insufficient_data"
    assert state.support_count == 0
    assert state.confidence == 0.0
    assert state.relationship_ref == relationship_ref(SOURCE, TARGET)


def test_reduce_aggregates_directed_pair():
    state = reduce_relationship_state(
        TENANT, SOURCE, TARGET, [_obs(StanceLabel.SUPPORTIVE), _obs(StanceLabel.SUPPORTIVE, age_days=1)]
    )
    assert state.source_ref == SOURCE and state.target_ref == TARGET
    assert state.subject_ref == TARGET
    assert state.stance_alignment > 0
    assert state.trust_signal > 0
    assert state.interaction_quality == "positive"
    assert state.propagation_role is PropagationRole.DIRECT_TRANSMISSION
    assert state.support_count == 2


def test_weighting_higher_confidence_dominates():
    # Opposed observation is down-weighted by low subject resolution confidence.
    supportive = _obs(StanceLabel.SUPPORTIVE, conf=0.9)
    opposed = _obs(StanceLabel.OPPOSED, conf=0.9)
    opposed.subject_resolution_confidence = 0.1
    state = reduce_relationship_state(TENANT, SOURCE, TARGET, [supportive, opposed])
    assert state.stance_alignment > 0  # supportive dominates despite equal counts


async def test_gold_relationship_persisted_and_read():
    await _seed("I support this, great product")
    state = await recompute_relationship_state(TENANT, SOURCE, TARGET)
    assert state.support_count == 1

    rel = relationship_ref(SOURCE, TARGET)
    gold = await SemanticFactRepository("gold_relationship_semantic_state").list_by_tenant(
        TENANT, rel, limit=1
    )
    assert gold and gold[0]["reducer_version"] == REDUCER_VERSION
    assert gold[0]["source_ref"] == SOURCE and gold[0]["target_ref"] == TARGET

    served = await service_mod.get_semantic_service().relationship_state(TENANT, SOURCE, TARGET)
    assert served["insufficient_data"] is False
    assert served["relationship_state"]["relationship_ref"] == rel


async def test_gold_relationship_sentiment_persisted():
    await _seed("love this, great, excellent")
    state = await recompute_relationship_sentiment(TENANT, SOURCE, TARGET)
    assert state.support_count == 1
    assert state.source_sentiment > 0

    gold = await SemanticFactRepository("gold_relationship_sentiment_state").list_by_tenant(
        TENANT, relationship_ref(SOURCE, TARGET), limit=1
    )
    assert gold and gold[0]["reducer_version"] == REDUCER_VERSION
    assert gold[0]["source_sentiment"] > 0


def test_sentiment_reduce_insufficient():
    state = reduce_relationship_sentiment(TENANT, SOURCE, TARGET, [])
    assert state.support_count == 0
    assert state.confidence == 0.0


async def test_unobserved_pair_persists_no_row():
    state = await recompute_relationship_state(TENANT, "ghost_a", "ghost_b")
    assert state.support_count == 0
    gold = await SemanticFactRepository("gold_relationship_semantic_state").list_by_tenant(
        TENANT, relationship_ref("ghost_a", "ghost_b"), limit=1
    )
    assert gold == []

    served = await service_mod.get_semantic_service().relationship_state(TENANT, "ghost_a", "ghost_b")
    assert served["insufficient_data"] is True
    assert served["relationship_state"] is None
