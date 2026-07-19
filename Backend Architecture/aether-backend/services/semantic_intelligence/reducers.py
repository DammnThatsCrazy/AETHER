"""Semantic state reducers — weighted aggregation into durable Gold state.

Aggregates immutable Silver observations into Gold entity semantic state using
the documented multiplicative weighting policy, so no single low-confidence,
stale, or dominating source drives the aggregate. Stores the reducer version and
calculation provenance, handles contradictions / confidence floors / insufficient
data, and guards against mixing model & taxonomy versions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
from typing import Any, Optional
from uuid import uuid4

from .models import (
    EntitySemanticState,
    IntentLabel,
    ObservationStatus,
    SemanticObservation,
    StanceLabel,
    SubjectType,
    utc_now,
)
from .repositories.base_fact_repo import SemanticFactRepository

REDUCER_VERSION = "weighted-reducer.v1"

_GOLD_ENTITY_TABLE = "gold_entity_semantic_state"
_GOLD_SENTIMENT_TABLE = "gold_entity_sentiment_state"
_GOLD_CAMPAIGN_TABLE = "gold_campaign_semantic_impact"

# Source reliability by source_type (expressive/first-party high; inferred lower).
_SOURCE_RELIABILITY: dict[str, float] = {
    "feedback": 1.0,
    "review": 1.0,
    "survey": 0.95,
    "support": 0.95,
    "message": 0.85,
    "agent": 0.85,
    "search": 0.8,
    "event": 0.7,
    "page": 0.6,
    "screen": 0.6,
}
_HALF_LIFE_DAYS = 30.0
_MIN_EVIDENCE = 1
_CONFIDENCE_FLOOR = 0.05
_ACTIVE = (ObservationStatus.CLASSIFIED, ObservationStatus.PARTIAL)


def _source_reliability(source_type: str) -> float:
    return _SOURCE_RELIABILITY.get(source_type, 0.75)


def _recency_decay(occurred_at, newest_at) -> float:
    age_days = max(0.0, (newest_at - occurred_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / _HALF_LIFE_DAYS)


def _eligibility_weight(status: ObservationStatus) -> float:
    return {ObservationStatus.CLASSIFIED: 1.0, ObservationStatus.PARTIAL: 0.5}.get(status, 0.0)


def observation_weight(obs: SemanticObservation, newest_at, actor_counts: dict[str, int]) -> float:
    """The multiplicative confidence weight for one observation."""
    duplication_penalty = 1.0 / math.sqrt(max(1, actor_counts.get(obs.actor_ref, 1)))
    return (
        obs.classification_confidence
        * obs.subject_resolution_confidence
        * obs.identity_confidence
        * _source_reliability(obs.source_type)
        * _recency_decay(obs.occurred_at, newest_at)
        * duplication_penalty
        * _eligibility_weight(obs.status)
    )


def reduce_entity_state(
    tenant_id: str, entity_ref: str, observations: list[SemanticObservation]
) -> EntitySemanticState:
    """Weighted reduction of observations into an entity's semantic state."""
    now = utc_now()
    active = [o for o in observations if o.status in _ACTIVE]
    window_start = observations[0].occurred_at if observations else now - timedelta(days=1)

    if len(active) < _MIN_EVIDENCE:
        return EntitySemanticState(
            tenant_id=tenant_id,
            entity_ref=entity_ref,
            entity_type=SubjectType.OTHER,
            subject_ref=entity_ref,
            window_start=window_start,
            window_end=now,
            semantic_summary="insufficient_data",
            observation_count=len(observations),
            unique_source_count=len({o.source_event_id for o in observations}),
            confidence=0.0,
            freshness="insufficient_data",
            version=2,
            semantic_delta={"reducer_version": REDUCER_VERSION, "insufficient_data": True},
        )

    newest_at = max(o.occurred_at for o in active)
    actor_counts: dict[str, int] = defaultdict(int)
    for o in active:
        actor_counts[o.actor_ref] += 1

    stance_weight: dict[StanceLabel, float] = defaultdict(float)
    intent_weight: dict[IntentLabel, float] = defaultdict(float)
    weighted_confidence = 0.0
    total_weight = 0.0
    for o in active:
        w = observation_weight(o, newest_at, actor_counts)
        if w <= 0:
            continue
        stance_weight[o.stance] += w
        intent_weight[o.intent] += w
        weighted_confidence += o.classification_confidence * w
        total_weight += w

    total = total_weight or 1.0
    stance_distribution = {k: round(v / total, 4) for k, v in stance_weight.items()}
    intent_distribution = {k: round(v / total, 4) for k, v in intent_weight.items()}

    # Contradiction: two stances each holding a material share of the weight.
    top = sorted(stance_distribution.values(), reverse=True)
    contradiction = len(top) >= 2 and top[0] < 0.6 and top[1] >= 0.3

    confidence = round(max(_CONFIDENCE_FLOOR, weighted_confidence / total), 4)
    model_mix: dict[str, int] = defaultdict(int)
    taxonomy_mix: dict[str, int] = defaultdict(int)
    for o in active:
        model_mix[f"{o.model_id}@{o.model_version}"] += 1
        taxonomy_mix[o.taxonomy_version] += 1
    inferred_type = active[0].target_type or SubjectType.OTHER

    return EntitySemanticState(
        tenant_id=tenant_id,
        entity_ref=entity_ref,
        entity_type=inferred_type,
        subject_ref=entity_ref,
        window_start=window_start,
        window_end=now,
        active_topics=sorted({t for o in active for t in o.topics}),
        dominant_narratives=sorted({n for o in active for n in o.narrative_frames}),
        stance_distribution=stance_distribution,
        intent_distribution=intent_distribution,
        semantic_summary=(
            f"{len(active)} weighted observations for {entity_ref}"
            + (" (contradictory)" if contradiction else "")
        ),
        observation_count=len(observations),
        unique_source_count=len({o.source_event_id for o in observations}),
        model_mix=dict(model_mix),
        confidence=confidence,
        freshness="fresh",
        evidence_refs=[e for o in active[-5:] for e in o.evidence_refs],
        version=2,
        semantic_delta={
            "reducer_version": REDUCER_VERSION,
            "total_weight": round(total_weight, 6),
            "contradiction": contradiction,
            "taxonomy_mix": dict(taxonomy_mix),
            "half_life_days": _HALF_LIFE_DAYS,
        },
    )


async def recompute_entity_state(
    tenant_id: str, entity_ref: str, *, store: Optional[Any] = None
) -> EntitySemanticState:
    """Recompute an entity's Gold semantic state and persist it (idempotent upsert)."""
    from .engine import get_store

    active_store = store or get_store()
    observations = await active_store.list_semantic(tenant_id, entity_ref)
    state = reduce_entity_state(tenant_id, entity_ref, observations)
    await _persist_gold(state)
    return state


async def _persist_gold(state: EntitySemanticState) -> None:
    repo = SemanticFactRepository(_GOLD_ENTITY_TABLE, mode="gold")
    idem = f"gold_entity:{state.tenant_id}:{state.entity_ref}:{REDUCER_VERSION}"
    data = state.model_dump(mode="json")
    data["idempotency_key"] = idem
    await repo.upsert(
        {
            "id": state.state_id,
            "tenant_id": state.tenant_id,
            "subject_ref": state.entity_ref,
            "occurred_at": state.computed_at,
            "idempotency_key": idem,
            "data": data,
        }
    )


def reduce_entity_sentiment(
    tenant_id: str, entity_ref: str, sentiments: list[Any]
) -> dict[str, Any]:
    """Weighted (confidence × recency) reduction of sentiment into Gold state."""
    base: dict[str, Any] = {
        "tenant_id": tenant_id,
        "entity_ref": entity_ref,
        "subject_ref": entity_ref,
        "observation_count": len(sentiments),
        "reducer_version": REDUCER_VERSION,
    }
    if not sentiments:
        return {**base, "insufficient_data": True, "valence": 0.0, "confidence": 0.0}

    newest_at = max(s.occurred_at for s in sentiments)
    total_w = 0.0
    wv = wa = wi = wconf = 0.0
    emotion_w: dict[str, float] = defaultdict(float)
    for s in sentiments:
        w = max(0.0, s.confidence) * _recency_decay(s.occurred_at, newest_at)
        if w <= 0:
            continue
        wv += s.valence * w
        wa += s.arousal * w
        wi += s.intensity * w
        wconf += s.confidence * w
        for emo, prob in (s.emotion_distribution or {}).items():
            emotion_w[getattr(emo, "value", str(emo))] += prob * w
        total_w += w
    total = total_w or 1.0

    # Sentiment trend: newest-third mean valence vs oldest-third mean valence.
    ordered = sorted(sentiments, key=lambda s: s.occurred_at)
    third = max(1, len(ordered) // 3)
    old_mean = sum(s.valence for s in ordered[:third]) / third
    new_mean = sum(s.valence for s in ordered[-third:]) / third
    trend = round(new_mean - old_mean, 4)
    dominant = max(emotion_w, key=emotion_w.get) if emotion_w else "neutral"

    return {
        **base,
        "insufficient_data": False,
        "valence": round(wv / total, 4),
        "arousal": round(wa / total, 4),
        "intensity": round(wi / total, 4),
        "dominant_emotion": dominant,
        "emotion_distribution": {k: round(v / total, 4) for k, v in emotion_w.items()},
        "sentiment_trend": trend,
        "confidence": round(max(_CONFIDENCE_FLOOR, wconf / total), 4),
    }


async def recompute_entity_sentiment(
    tenant_id: str, entity_ref: str, *, store: Optional[Any] = None
) -> dict[str, Any]:
    """Recompute and durably persist an entity's Gold sentiment state."""
    from .engine import get_store

    active_store = store or get_store()
    sentiments = await active_store.list_sentiment(tenant_id, entity_ref)
    state = reduce_entity_sentiment(tenant_id, entity_ref, sentiments)
    repo = SemanticFactRepository(_GOLD_SENTIMENT_TABLE, mode="gold")
    idem = f"gold_sentiment:{tenant_id}:{entity_ref}:{REDUCER_VERSION}"
    data = {**state, "idempotency_key": idem}
    await repo.upsert(
        {
            "id": f"gess_{uuid4().hex}",
            "tenant_id": tenant_id,
            "subject_ref": entity_ref,
            "occurred_at": utc_now(),
            "idempotency_key": idem,
            "data": data,
        }
    )
    return state


def reduce_campaign_impact(
    tenant_id: str, campaign_id: str, observations: list[SemanticObservation]
) -> dict[str, Any]:
    """Weighted campaign semantic impact. Causal language stays bounded."""
    active = [o for o in observations if o.status in _ACTIVE]
    base: dict[str, Any] = {
        "campaign_id": campaign_id,
        "observation_count": len(observations),
        "reducer_version": REDUCER_VERSION,
        # Exposure/association only — a causal claim needs a separate methodology.
        "causal_confidence": "observed_sequence",
        "semantic_mediated_revenue_estimate": None,
    }
    if not active:
        return {**base, "insufficient_data": True, "stance_distribution": {}, "dominant_topics": []}

    newest_at = max(o.occurred_at for o in active)
    actor_counts: dict[str, int] = defaultdict(int)
    for o in active:
        actor_counts[o.actor_ref] += 1

    stance_weight: dict[str, float] = defaultdict(float)
    intent_weight: dict[str, float] = defaultdict(float)
    weighted_confidence = 0.0
    total_weight = 0.0
    for o in active:
        w = observation_weight(o, newest_at, actor_counts)
        if w <= 0:
            continue
        stance_weight[o.stance.value] += w
        intent_weight[o.intent.value] += w
        weighted_confidence += o.classification_confidence * w
        total_weight += w
    total = total_weight or 1.0

    return {
        **base,
        "insufficient_data": False,
        "dominant_topics": sorted({t for o in active for t in o.topics}),
        "dominant_narratives": sorted({n for o in active for n in o.narrative_frames}),
        "stance_distribution": {k: round(v / total, 4) for k, v in stance_weight.items()},
        "intent_distribution": {k: round(v / total, 4) for k, v in intent_weight.items()},
        "confidence": round(max(_CONFIDENCE_FLOOR, weighted_confidence / total), 4),
        "unique_actor_count": len(actor_counts),
        "evidence_refs": [e.model_dump(mode="json") for o in active[:5] for e in o.evidence_refs],
    }


async def recompute_campaign_impact(
    tenant_id: str, campaign_id: str, *, store: Optional[Any] = None
) -> dict[str, Any]:
    """Recompute and durably persist a campaign's semantic impact (Gold)."""
    from .engine import get_store

    active_store = store or get_store()
    observations = [
        o for o in await active_store.list_semantic(tenant_id) if o.campaign_id == campaign_id
    ]
    impact = reduce_campaign_impact(tenant_id, campaign_id, observations)
    repo = SemanticFactRepository(_GOLD_CAMPAIGN_TABLE, mode="gold")
    idem = f"gold_campaign:{tenant_id}:{campaign_id}:{REDUCER_VERSION}"
    data = {**impact, "idempotency_key": idem}
    await repo.upsert(
        {
            "id": f"gcsi_{uuid4().hex}",
            "tenant_id": tenant_id,
            "subject_ref": campaign_id,
            "campaign_id": campaign_id,
            "occurred_at": utc_now(),
            "idempotency_key": idem,
            "data": data,
        }
    )
    return impact
