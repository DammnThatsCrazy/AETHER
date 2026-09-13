"""Phase C·1 — weighted semantic reducers + durable Gold entity state.

Proves aggregation uses the multiplicative weighting policy (not a single-factor
sum), records reducer version + provenance, handles duplication dominance,
contradiction and insufficient data, and durably persists Gold state — produced
automatically as events flow through the worker.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.consumer import SemanticEventConsumer
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import (
    EvidenceRef,
    IntentLabel,
    ObservationStatus,
    SemanticObservation,
    StanceLabel,
    SubjectType,
    utc_now,
)
from services.semantic_intelligence.reducers import (
    REDUCER_VERSION,
    observation_weight,
    reduce_entity_state,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_reduce"
SUBJECT = "prod_reduce"


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


def _obs(actor: str, stance: StanceLabel, *, conf: float = 0.9, age_days: float = 0.0) -> SemanticObservation:
    return SemanticObservation(
        tenant_id=TENANT,
        source_event_id=f"e_{actor}_{stance.value}_{age_days}",
        source_type="feedback",
        actor_ref=actor,
        actor_type=SubjectType.PROFILE,
        primary_subject_ref=SUBJECT,
        target_type=SubjectType.PRODUCT,
        stance=stance,
        intent=IntentLabel.EVALUATE,
        classification_confidence=conf,
        occurred_at=utc_now() - timedelta(days=age_days),
        evidence_refs=[EvidenceRef(evidence_id="e", source_type="event", source_ref="e")],
    )


def test_insufficient_data():
    state = reduce_entity_state(TENANT, SUBJECT, [])
    assert state.semantic_summary == "insufficient_data"
    assert state.freshness == "insufficient_data"
    assert state.semantic_delta["reducer_version"] == REDUCER_VERSION


def test_weighting_is_multiplicative_not_single_factor():
    # Low subject-resolution confidence must down-weight an observation.
    strong = _obs("a1", StanceLabel.SUPPORTIVE, conf=0.9)
    weak = _obs("a2", StanceLabel.OPPOSED, conf=0.9)
    weak.subject_resolution_confidence = 0.1  # low → down-weighted
    newest = utc_now()
    counts = {"a1": 1, "a2": 1}
    assert observation_weight(strong, newest, counts) > observation_weight(weak, newest, counts) * 3


def test_recency_decay_downweights_old_observations():
    fresh = _obs("a1", StanceLabel.SUPPORTIVE, age_days=0)
    old = _obs("a2", StanceLabel.SUPPORTIVE, age_days=90)
    newest = utc_now()
    counts = {"a1": 1, "a2": 1}
    assert observation_weight(fresh, newest, counts) > observation_weight(old, newest, counts)


def test_duplication_penalty_prevents_one_actor_dominating():
    # One actor posts 4 opposed; four distinct actors post supportive once each.
    obs = [_obs("spammer", StanceLabel.OPPOSED) for _ in range(4)]
    obs += [_obs(f"user{i}", StanceLabel.SUPPORTIVE) for i in range(4)]
    state = reduce_entity_state(TENANT, SUBJECT, obs)
    supportive = state.stance_distribution.get(StanceLabel.SUPPORTIVE, 0)
    opposed = state.stance_distribution.get(StanceLabel.OPPOSED, 0)
    assert supportive > opposed  # dedup penalty keeps the spammer from dominating


def test_contradiction_flagged():
    obs = [_obs(f"u{i}", StanceLabel.SUPPORTIVE) for i in range(3)]
    obs += [_obs(f"o{i}", StanceLabel.OPPOSED) for i in range(3)]
    state = reduce_entity_state(TENANT, SUBJECT, obs)
    assert state.semantic_delta["contradiction"] is True


async def test_gold_state_persisted_and_read():
    svc = service_mod.get_semantic_service()
    store = get_store()
    await store.put_semantic(_obs("a1", StanceLabel.SUPPORTIVE))
    state = await svc.recompute_entity_state(TENANT, SUBJECT)
    assert state.version == 2

    gold = await svc.gold_entity_state(TENANT, SUBJECT)
    assert gold is not None
    assert gold["subject_ref"] == SUBJECT
    assert gold["semantic_delta"]["reducer_version"] == REDUCER_VERSION


async def test_worker_produces_gold_state():
    ev = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_id": "e_gold",
            "event_type": "feedback_submitted",
            "user_id": "u1",
            "properties": {"content": "great product, I recommend it", "product_id": SUBJECT},
        },
    )
    await SemanticEventConsumer().on_validated_event(ev)
    gold = await service_mod.get_semantic_service().gold_entity_state(TENANT, SUBJECT)
    assert gold is not None and gold["subject_ref"] == SUBJECT
