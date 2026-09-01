"""Semantic state reducers — weighted aggregation into durable Gold state.

Aggregates immutable Silver observations into Gold entity, relationship,
narrative, episode and cascade state using the documented multiplicative
weighting policy, so no single low-confidence, stale, or dominating source
drives the aggregate. Stores the reducer version and calculation provenance,
handles contradictions / confidence floors / insufficient data, and guards
against mixing model & taxonomy versions.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import timedelta
from typing import Any, Optional
from uuid import uuid4

from .models import (
    EntitySemanticState,
    IntentLabel,
    ObservationStatus,
    PropagationRole,
    RelationshipSemanticState,
    RelationshipSentimentState,
    SemanticCascade,
    SemanticEpisode,
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
_GOLD_RELATIONSHIP_TABLE = "gold_relationship_semantic_state"
_GOLD_RELATIONSHIP_SENTIMENT_TABLE = "gold_relationship_sentiment_state"
_GOLD_NARRATIVE_TABLE = "gold_narrative_state"
_GOLD_EPISODE_TABLE = "gold_semantic_episodes"
_GOLD_CASCADE_TABLE = "gold_semantic_cascades"

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

# Episodization: a new episode starts after this quiet gap (or a stance-sign flip).
EPISODE_GAP = timedelta(days=7)
# Narrative momentum window: weighted count in the latest window vs the prior one.
_NARRATIVE_WINDOW_DAYS = 7.0


def _rights_fields(rows: list[Any]) -> dict[str, Any]:
    """Union reference-only rights provenance from derived input rows."""
    envelope_refs = sorted({
        str(ref) for row in rows for ref in getattr(row, "rights_envelope_refs", []) if ref
    })
    decision_refs = sorted({
        str(ref) for row in rows for ref in getattr(row, "rights_decision_refs", []) if ref
    })
    policies = sorted({
        str(ref) for row in rows
        if (ref := getattr(row, "rights_policy_set_ref", None))
    })
    return {
        "rights_envelope_refs": envelope_refs,
        "rights_decision_refs": decision_refs,
        "rights_policy_set_ref": policies[0] if len(policies) == 1 else None,
    }

# Signed stance scores for alignment/momentum math (supportive > 0, opposed < 0;
# neutral / uncertain / mixed / not_applicable / abstained carry no sign).
_STANCE_SCORE: dict[StanceLabel, float] = {
    StanceLabel.STRONGLY_SUPPORTIVE: 1.0,
    StanceLabel.SUPPORTIVE: 0.66,
    StanceLabel.WEAKLY_SUPPORTIVE: 0.33,
    StanceLabel.WEAKLY_OPPOSED: -0.33,
    StanceLabel.OPPOSED: -0.66,
    StanceLabel.STRONGLY_OPPOSED: -1.0,
}


def _stance_sign(stance: StanceLabel) -> int:
    score = _STANCE_SCORE.get(stance, 0.0)
    return (score > 0) - (score < 0)


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
            **_rights_fields(observations),
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
        **_rights_fields(active),
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
    tenant_id: str,
    entity_ref: str,
    *,
    store: Optional[Any] = None,
    aggregate_refs: Optional[list[str]] = None,
) -> EntitySemanticState:
    """Recompute an entity's Gold semantic state and persist it (idempotent upsert).

    ``aggregate_refs`` folds several source refs into ``entity_ref``'s state — used
    on identity merge to re-aggregate the consumed entity's observations under the
    survivor without mutating the immutable Silver rows.
    """
    from .engine import get_store

    active_store = store or get_store()
    refs = aggregate_refs or [entity_ref]
    observations: list[SemanticObservation] = []
    for ref in refs:
        observations.extend(await active_store.list_semantic(tenant_id, ref))
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
    # Only active (non-retracted) rows contribute — mirrors reduce_entity_state.
    # A consent restriction/erasure moves a subject's/actor's rows out of _ACTIVE,
    # so recomputing after a retraction drops the retracted sentiment from Gold.
    active = [
        s for s in sentiments if getattr(s, "status", ObservationStatus.CLASSIFIED) in _ACTIVE
    ]
    if not active:
        return {**base, "insufficient_data": True, "valence": 0.0, "confidence": 0.0}

    newest_at = max(s.occurred_at for s in active)
    total_w = 0.0
    wv = wa = wi = wconf = 0.0
    emotion_w: dict[str, float] = defaultdict(float)
    for s in active:
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
    tenant_id: str,
    entity_ref: str,
    *,
    store: Optional[Any] = None,
    aggregate_refs: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Recompute and durably persist an entity's Gold sentiment state."""
    from .engine import get_store

    active_store = store or get_store()
    refs = aggregate_refs or [entity_ref]
    sentiments: list[Any] = []
    for ref in refs:
        sentiments.extend(await active_store.list_sentiment(tenant_id, ref))
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
        "rights": _rights_fields(observations),
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


def relationship_ref(source_ref: str, target_ref: str) -> str:
    """Deterministic directed relationship reference for a (source, target) pair."""
    return f"rel:{source_ref}->{target_ref}"


def reduce_relationship_state(
    tenant_id: str,
    source_ref: str,
    target_ref: str,
    observations: list[SemanticObservation],
    reverse_observations: Optional[list[SemanticObservation]] = None,
) -> RelationshipSemanticState:
    """Weighted reduction of a directed (source → target) relationship.

    The pair is derived from actor_ref → primary_subject_ref: an actor repeatedly
    expressing stance about a subject IS the semantic relationship between them.
    ``observations`` are therefore the source's observations about the target;
    ``reverse_observations`` (if any exist) are the target's about the source and
    only inform reciprocity/direction — they never mix into the forward weights.
    """
    now = utc_now()
    active = [o for o in observations if o.status in _ACTIVE]
    reverse_active = [o for o in (reverse_observations or []) if o.status in _ACTIVE]
    rel_ref = relationship_ref(source_ref, target_ref)
    layer = next((o.relationship_layer for o in active if o.relationship_layer), "semantic")
    valid_from = min((o.occurred_at for o in observations), default=now)

    if len(active) < _MIN_EVIDENCE:
        return RelationshipSemanticState(
            tenant_id=tenant_id,
            relationship_ref=rel_ref,
            source_ref=source_ref,
            target_ref=target_ref,
            relationship_layer=layer,
            subject_ref=target_ref,
            interaction_quality="insufficient_data",
            support_count=0,
            confidence=0.0,
            valid_from=valid_from,
            **_rights_fields(observations),
        )

    newest_at = max(o.occurred_at for o in active)
    actor_counts: dict[str, int] = defaultdict(int)
    for o in active:
        actor_counts[o.actor_ref] += 1

    stance_weight: dict[StanceLabel, float] = defaultdict(float)
    weighted_confidence = 0.0
    weighted_stance_score = 0.0
    recent_weight = 0.0
    total_weight = 0.0
    for o in active:
        w = observation_weight(o, newest_at, actor_counts)
        if w <= 0:
            continue
        stance_weight[o.stance] += w
        weighted_stance_score += _STANCE_SCORE.get(o.stance, 0.0) * w
        weighted_confidence += o.classification_confidence * w
        if (newest_at - o.occurred_at) <= timedelta(days=_HALF_LIFE_DAYS):
            recent_weight += w
        total_weight += w
    total = total_weight or 1.0

    stance_alignment = round(max(-1.0, min(1.0, weighted_stance_score / total)), 4)
    dominant_share = max(stance_weight.values(), default=0.0) / total
    if stance_alignment >= 0.2:
        interaction_quality = "positive"
    elif stance_alignment <= -0.2:
        interaction_quality = "negative"
    elif (1.0 - dominant_share) >= 0.4:
        interaction_quality = "contested"
    else:
        interaction_quality = "neutral"

    # Reciprocity: balance of forward vs reverse evidence (0 when one-directional).
    forward_n, reverse_n = len(active), len(reverse_active)
    reciprocity = round(min(forward_n, reverse_n) / max(forward_n, reverse_n), 4) if reverse_n else 0.0
    # An expressed stance is a direct transmission channel; sign-free stances
    # (neutral / not_applicable / …) only establish structural context.
    opinionated = any(_stance_sign(s) for s in stance_weight)

    return RelationshipSemanticState(
        tenant_id=tenant_id,
        relationship_ref=rel_ref,
        source_ref=source_ref,
        target_ref=target_ref,
        relationship_layer=layer,
        subject_ref=target_ref,
        dominant_topics=sorted({t for o in active for t in o.topics}),
        shared_narratives=sorted({n for o in active for n in o.narrative_frames}),
        stance_alignment=stance_alignment,
        semantic_alignment=round(dominant_share, 4),
        disagreement_score=round(1.0 - dominant_share, 4),
        trust_signal=round(max(0.0, stance_alignment), 4),
        responsiveness=round(recent_weight / total, 4),
        reciprocity=reciprocity,
        influence_direction="bidirectional" if reverse_n else "source_to_target",
        interaction_quality=interaction_quality,
        propagation_role=(
            PropagationRole.DIRECT_TRANSMISSION if opinionated else PropagationRole.STRUCTURAL_CONTEXT
        ),
        support_count=len(active),
        confidence=round(max(_CONFIDENCE_FLOOR, weighted_confidence / total), 4),
        valid_from=valid_from,
        **_rights_fields(active),
    )


async def recompute_relationship_state(
    tenant_id: str, source_ref: str, target_ref: str, *, store: Optional[Any] = None
) -> RelationshipSemanticState:
    """Recompute a (source → target) relationship's Gold semantic state.

    Persists only when supporting observations exist — an unobserved pair never
    yields a durable row (no fake relationships).
    """
    from .engine import get_store

    active_store = store or get_store()
    forward = [
        o for o in await active_store.list_semantic(tenant_id, target_ref) if o.actor_ref == source_ref
    ]
    reverse = [
        o for o in await active_store.list_semantic(tenant_id, source_ref) if o.actor_ref == target_ref
    ]
    state = reduce_relationship_state(tenant_id, source_ref, target_ref, forward, reverse)
    if state.support_count > 0:
        repo = SemanticFactRepository(_GOLD_RELATIONSHIP_TABLE, mode="gold")
        idem = f"gold_relationship:{tenant_id}:{state.relationship_ref}:{REDUCER_VERSION}"
        data = state.model_dump(mode="json")
        data["reducer_version"] = REDUCER_VERSION
        data["idempotency_key"] = idem
        await repo.upsert(
            {
                "id": state.state_id,
                "tenant_id": tenant_id,
                "subject_ref": state.relationship_ref,
                "occurred_at": state.computed_at,
                "idempotency_key": idem,
                "data": data,
            }
        )
    return state


def reduce_relationship_sentiment(
    tenant_id: str,
    source_ref: str,
    target_ref: str,
    sentiments: list[Any],
    reverse_sentiments: Optional[list[Any]] = None,
) -> RelationshipSentimentState:
    """Weighted (confidence × recency) sentiment reduction for a directed pair.

    ``sentiments`` are the source's sentiment observations about the target;
    ``reverse_sentiments`` the target's about the source (empty when unobserved).
    Adoption / transmission / retransmission probabilities need cascade-level
    propagation evidence, so they stay 0 here rather than being fabricated from
    stance alone (same discipline as the campaign reducer's causal bounds).
    """
    now = utc_now()
    rel_ref = relationship_ref(source_ref, target_ref)
    valid_from = min((s.occurred_at for s in sentiments), default=now)
    if not sentiments:
        return RelationshipSentimentState(
            relationship_ref=rel_ref,
            subject_ref=target_ref,
            valid_from=valid_from,
            **_rights_fields(sentiments),
        )

    def _weighted(rows: list[Any]) -> tuple[float, float]:
        """(weighted valence, weighted confidence) for one direction."""
        newest = max(r.occurred_at for r in rows)
        total = wv = wc = 0.0
        for r in rows:
            w = max(0.0, r.confidence) * _recency_decay(r.occurred_at, newest)
            if w <= 0:
                continue
            wv += r.valence * w
            wc += r.confidence * w
            total += w
        denom = total or 1.0
        return wv / denom, wc / denom

    def _trend(rows: list[Any]) -> float:
        """Newest-third mean valence vs oldest-third (mirrors the entity reducer)."""
        ordered = sorted(rows, key=lambda r: r.occurred_at)
        third = max(1, len(ordered) // 3)
        old_mean = sum(r.valence for r in ordered[:third]) / third
        new_mean = sum(r.valence for r in ordered[-third:]) / third
        return round(new_mean - old_mean, 4)

    reverse = list(reverse_sentiments or [])
    source_valence, source_conf = _weighted(sentiments)
    target_valence = _weighted(reverse)[0] if reverse else 0.0
    # Alignment only means something with both directions observed; valences live
    # in [-1, 1] so 1 - |gap| lands in [-1, 1] (identical → 1, antipodal → -1).
    alignment = round(1.0 - abs(source_valence - target_valence), 4) if reverse else 0.0

    return RelationshipSentimentState(
        relationship_ref=rel_ref,
        subject_ref=target_ref,
        source_sentiment=round(max(-1.0, min(1.0, source_valence)), 4),
        target_sentiment=round(max(-1.0, min(1.0, target_valence)), 4),
        sentiment_alignment=alignment,
        sentiment_delta=round(source_valence - target_valence, 4),
        source_to_target_shift=_trend(sentiments),
        target_to_source_shift=_trend(reverse) if reverse else 0.0,
        confidence=round(max(_CONFIDENCE_FLOOR, source_conf), 4),
        support_count=len(sentiments) + len(reverse),
        valid_from=valid_from,
        **_rights_fields(sentiments + reverse),
    )


async def recompute_relationship_sentiment(
    tenant_id: str, source_ref: str, target_ref: str, *, store: Optional[Any] = None
) -> RelationshipSentimentState:
    """Recompute a (source → target) relationship's Gold sentiment state.

    Persists only when the pair has sentiment evidence (no fake rows).
    """
    from .engine import get_store

    active_store = store or get_store()
    forward = [
        s for s in await active_store.list_sentiment(tenant_id, target_ref) if s.actor_ref == source_ref
    ]
    reverse = [
        s for s in await active_store.list_sentiment(tenant_id, source_ref) if s.actor_ref == target_ref
    ]
    state = reduce_relationship_sentiment(tenant_id, source_ref, target_ref, forward, reverse)
    if state.support_count > 0:
        repo = SemanticFactRepository(_GOLD_RELATIONSHIP_SENTIMENT_TABLE, mode="gold")
        idem = f"gold_relationship_sentiment:{tenant_id}:{state.relationship_ref}:{REDUCER_VERSION}"
        data = state.model_dump(mode="json")
        data.update(
            {
                "tenant_id": tenant_id,
                "source_ref": source_ref,
                "target_ref": target_ref,
                "reducer_version": REDUCER_VERSION,
                "idempotency_key": idem,
            }
        )
        await repo.upsert(
            {
                "id": f"grss_{uuid4().hex}",
                "tenant_id": tenant_id,
                "subject_ref": state.relationship_ref,
                "occurred_at": state.computed_at,
                "idempotency_key": idem,
                "data": data,
            }
        )
    return state


def reduce_narrative_state(
    tenant_id: str, observations: list[SemanticObservation]
) -> list[dict[str, Any]]:
    """Weighted per-narrative aggregates from a tenant's observations.

    Each narrative_frame becomes one aggregate: supporting observation count,
    weighted stance distribution, first/last observed, and momentum — the total
    observation weight in the latest window minus the prior window's, so a frame
    gaining weighted support shows positive momentum and a fading one negative.
    """
    active = [o for o in observations if o.status in _ACTIVE and o.narrative_frames]
    if not active:
        return []

    by_frame: dict[str, list[SemanticObservation]] = defaultdict(list)
    for o in active:
        for frame in o.narrative_frames:
            by_frame[frame].append(o)

    states: list[dict[str, Any]] = []
    window = timedelta(days=_NARRATIVE_WINDOW_DAYS)
    for frame in sorted(by_frame):
        rows = sorted(by_frame[frame], key=lambda o: o.occurred_at)
        newest_at = rows[-1].occurred_at
        actor_counts: dict[str, int] = defaultdict(int)
        for o in rows:
            actor_counts[o.actor_ref] += 1
        stance_weight: dict[str, float] = defaultdict(float)
        weighted_confidence = recent_weight = prior_weight = total_weight = 0.0
        for o in rows:
            w = observation_weight(o, newest_at, actor_counts)
            if w <= 0:
                continue
            stance_weight[o.stance.value] += w
            weighted_confidence += o.classification_confidence * w
            age = newest_at - o.occurred_at
            if age <= window:
                recent_weight += w
            elif age <= 2 * window:
                prior_weight += w
            total_weight += w
        total = total_weight or 1.0
        states.append(
            {
                "tenant_id": tenant_id,
                "narrative_ref": frame,
                "subject_ref": frame,
                "observation_count": len(rows),
                "unique_actor_count": len(actor_counts),
                "stance_distribution": {k: round(v / total, 4) for k, v in stance_weight.items()},
                "dominant_topics": sorted({t for o in rows for t in o.topics}),
                "first_observed_at": rows[0].occurred_at.isoformat(),
                "last_observed_at": newest_at.isoformat(),
                "recent_weight": round(recent_weight, 6),
                "prior_weight": round(prior_weight, 6),
                "momentum": round(recent_weight - prior_weight, 6),
                "window_days": _NARRATIVE_WINDOW_DAYS,
                "confidence": round(max(_CONFIDENCE_FLOOR, weighted_confidence / total), 4),
                "reducer_version": REDUCER_VERSION,
                "rights": _rights_fields(rows),
            }
        )
    return states


async def recompute_narrative_states(
    tenant_id: str, *, store: Optional[Any] = None
) -> list[dict[str, Any]]:
    """Recompute and durably persist all of a tenant's narrative Gold states.

    A tenant with no framed observations persists nothing (no fake narratives).
    """
    from .engine import get_store

    active_store = store or get_store()
    observations = await active_store.list_semantic(tenant_id)
    states = reduce_narrative_state(tenant_id, observations)
    repo = SemanticFactRepository(_GOLD_NARRATIVE_TABLE, mode="gold")
    for state in states:
        idem = f"gold_narrative:{tenant_id}:{state['narrative_ref']}:{REDUCER_VERSION}"
        data = {**state, "idempotency_key": idem}
        await repo.upsert(
            {
                "id": f"gns_{uuid4().hex}",
                "tenant_id": tenant_id,
                "subject_ref": state["narrative_ref"],
                "occurred_at": utc_now(),
                "idempotency_key": idem,
                "data": data,
            }
        )
    return states


async def recompute_cascades(tenant_id: str) -> list[SemanticCascade]:
    """Persist the tenant's live cascade projections to Gold (idempotent upsert).

    ``engine.cascades_for_tenant`` stays the single computation; this pass makes
    its result durable. Cascade ids are content-derived (tenant|subject|topic|
    stance), so recomputation refreshes rows instead of duplicating them.
    """
    from .engine import cascades_for_tenant

    cascades = await cascades_for_tenant(tenant_id)
    observations = await get_store().list_semantic(tenant_id)
    by_observation = {o.observation_id: o for o in observations}
    cascades = [
        cascade.model_copy(update=_rights_fields([
            by_observation[ref]
            for ref in cascade.seed_observations
            if ref in by_observation
        ]))
        for cascade in cascades
    ]
    repo = SemanticFactRepository(_GOLD_CASCADE_TABLE, mode="gold")
    for cascade in cascades:
        idem = f"gold_cascade:{tenant_id}:{cascade.cascade_id}:{REDUCER_VERSION}"
        data = cascade.model_dump(mode="json")
        data["reducer_version"] = REDUCER_VERSION
        data["idempotency_key"] = idem
        await repo.upsert(
            {
                "id": cascade.cascade_id,
                "tenant_id": tenant_id,
                "subject_ref": cascade.subject_ref,
                "campaign_id": cascade.campaign_id,
                "occurred_at": cascade.last_observed_at,
                "idempotency_key": idem,
                "data": data,
            }
        )
    return cascades


def reduce_episodes(
    tenant_id: str,
    subject_ref: str,
    observations: list[SemanticObservation],
    sentiments: Optional[list[Any]] = None,
) -> list[SemanticEpisode]:
    """Episodize a subject's time-ordered observations.

    A new episode starts when the quiet gap exceeds ``EPISODE_GAP`` or the
    dominant stance flips sign (supportive ↔ opposed) — a subject moving from
    advocacy to grievance is a new arc, not a continuation. Entry/exit sentiment
    is the weighted valence of the episode's first/last boundary day. Episode
    ids are content-derived (tenant|subject|start) so recomputation refreshes
    rows instead of duplicating them.
    """
    active = sorted((o for o in observations if o.status in _ACTIVE), key=lambda o: o.occurred_at)
    if not active:
        return []

    segments: list[list[SemanticObservation]] = [[active[0]]]
    current_sign = _stance_sign(active[0].stance)
    for prev, obs in zip(active, active[1:]):
        sign = _stance_sign(obs.stance)
        gap_split = (obs.occurred_at - prev.occurred_at) > EPISODE_GAP
        stance_split = sign != 0 and current_sign != 0 and sign != current_sign
        if gap_split or stance_split:
            segments.append([obs])
            current_sign = sign
        else:
            segments[-1].append(obs)
            current_sign = current_sign or sign

    now = utc_now()
    ordered_sentiments = sorted(sentiments or [], key=lambda s: s.occurred_at)

    def _boundary_snapshot(rows: list[Any]) -> dict[str, Any]:
        """Confidence-weighted valence snapshot for an episode boundary cluster."""
        if not rows:
            return {}
        total = sum(max(0.0, r.confidence) for r in rows) or 1.0
        return {
            "valence": round(sum(r.valence * max(0.0, r.confidence) for r in rows) / total, 4),
            "confidence": round(sum(r.confidence for r in rows) / len(rows), 4),
            "observation_count": len(rows),
        }

    episodes: list[SemanticEpisode] = []
    for segment in segments:
        start_at = segment[0].occurred_at
        end_at = segment[-1].occurred_at
        actor_counts: dict[str, int] = defaultdict(int)
        for o in segment:
            actor_counts[o.actor_ref] += 1
        weighted_confidence = weighted_score = total_weight = 0.0
        for o in segment:
            w = observation_weight(o, end_at, actor_counts)
            if w <= 0:
                continue
            weighted_score += _STANCE_SCORE.get(o.stance, 0.0) * w
            weighted_confidence += o.classification_confidence * w
            total_weight += w
        total = total_weight or 1.0
        mean_score = weighted_score / total
        if mean_score >= 0.15:
            episode_type = "advocacy"
        elif mean_score <= -0.15:
            episode_type = "grievance"
        else:
            episode_type = "neutral_engagement"

        # A sentiment row rides on its linked observation's timeline — the engine
        # stamps sentiment occurred_at at processing time, not source-event time.
        obs_times = {o.observation_id: o.occurred_at for o in segment}

        def _effective_at(s: Any):
            return obs_times.get(s.semantic_observation_id, s.occurred_at)

        in_window = sorted(
            (s for s in ordered_sentiments if start_at <= _effective_at(s) <= end_at),
            key=_effective_at,
        )
        entry_rows = (
            [s for s in in_window if _effective_at(s) <= _effective_at(in_window[0]) + timedelta(days=1)]
            if in_window
            else []
        )
        exit_rows = (
            [s for s in in_window if _effective_at(s) >= _effective_at(in_window[-1]) - timedelta(days=1)]
            if in_window
            else []
        )

        episode_key = "|".join([tenant_id, subject_ref, start_at.isoformat()])
        episode_id = "sepi_" + hashlib.sha256(episode_key.encode()).hexdigest()[:24]
        duration_days = max(1, round((end_at - start_at).total_seconds() / 86400.0) or 1)
        episodes.append(
            SemanticEpisode(
                episode_id=episode_id,
                tenant_id=tenant_id,
                episode_type=episode_type,
                subject_refs=[subject_ref],
                entity_refs=sorted(actor_counts),
                workflow_refs=sorted({r for o in segment for r in o.workflow_refs}),
                journey_refs=sorted({o.journey_id for o in segment if o.journey_id}),
                campaign_refs=sorted({o.campaign_id for o in segment if o.campaign_id}),
                narrative_refs=sorted({n for o in segment for n in o.narrative_frames}),
                observation_refs=[o.observation_id for o in segment],
                start_at=start_at,
                end_at=end_at,
                status="active" if (now - end_at) <= EPISODE_GAP else "closed",
                sequence_summary=f"{len(segment)} observations over {duration_days} day(s)",
                semantic_summary=f"{episode_type}: {len(segment)} observations for {subject_ref}",
                sentiment_start_state=_boundary_snapshot(entry_rows),
                sentiment_end_state=_boundary_snapshot(exit_rows),
                confidence=round(max(_CONFIDENCE_FLOOR, weighted_confidence / total), 4),
                evidence_refs=[e for o in segment[:5] for e in o.evidence_refs],
                **_rights_fields(segment),
            )
        )
    return episodes


async def recompute_episodes(
    tenant_id: str, subject_ref: str, *, store: Optional[Any] = None
) -> list[SemanticEpisode]:
    """Recompute and durably persist a subject's Gold episodes.

    A subject with no active observations persists nothing (no fake episodes).
    """
    from .engine import get_store

    active_store = store or get_store()
    observations = await active_store.list_semantic(tenant_id, subject_ref)
    sentiments = await active_store.list_sentiment(tenant_id, subject_ref)
    episodes = reduce_episodes(tenant_id, subject_ref, observations, sentiments)
    repo = SemanticFactRepository(_GOLD_EPISODE_TABLE, mode="gold")
    for episode in episodes:
        idem = f"gold_episode:{tenant_id}:{episode.episode_id}:{REDUCER_VERSION}"
        data = episode.model_dump(mode="json")
        data["reducer_version"] = REDUCER_VERSION
        data["idempotency_key"] = idem
        await repo.upsert(
            {
                "id": episode.episode_id,
                "tenant_id": tenant_id,
                "subject_ref": subject_ref,
                "occurred_at": episode.start_at,
                "idempotency_key": idem,
                "data": data,
            }
        )
    return episodes
