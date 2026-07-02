"""Deterministic semantic/sentiment classifier and in-memory repository.

Production model providers can plug in behind this interface; this local engine
is intentionally deterministic so CI, replay and security tests do not depend on
external credentials.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from typing import Any

from .models import (
    EmotionLabel,
    EntitySemanticState,
    EvidenceRef,
    IntentLabel,
    ObservationStatus,
    SemanticObservation,
    SentimentObservation,
    SpeechAct,
    StanceLabel,
    SubjectRef,
    SubjectType,
    utc_now,
)

POSITIVE = {"love", "great", "excellent", "happy", "trust", "recommend", "approve", "support"}
NEGATIVE = {
    "hate",
    "bad",
    "angry",
    "broken",
    "expensive",
    "reject",
    "oppose",
    "churn",
    "cancel",
    "terrible",
}
AGENT_WORDS = {"recommend", "policy", "confidence", "uncertain", "delegate", "tool", "plan"}


class SemanticSentimentStore:
    def __init__(self) -> None:
        self.semantic: dict[str, SemanticObservation] = {}
        self.sentiment: dict[str, SentimentObservation] = {}

    def put_semantic(self, obs: SemanticObservation) -> SemanticObservation:
        for existing in self.semantic.values():
            if (
                existing.tenant_id == obs.tenant_id
                and existing.idempotency_key == obs.idempotency_key
            ):
                return existing
        self.semantic[obs.observation_id] = obs
        return obs

    def put_sentiment(self, obs: SentimentObservation) -> SentimentObservation:
        self.sentiment[obs.sentiment_observation_id] = obs
        return obs

    def list_semantic(
        self, tenant_id: str, subject: str | None = None
    ) -> list[SemanticObservation]:
        rows = [o for o in self.semantic.values() if o.tenant_id == tenant_id]
        if subject:
            rows = [o for o in rows if o.primary_subject_ref == subject]
        return sorted(rows, key=lambda o: o.occurred_at)

    def list_sentiment(
        self, tenant_id: str, subject: str | None = None
    ) -> list[SentimentObservation]:
        rows = [o for o in self.sentiment.values() if o.tenant_id == tenant_id]
        if subject:
            rows = [o for o in rows if o.target_subject_ref == subject]
        return sorted(rows, key=lambda o: o.occurred_at)


store = SemanticSentimentStore()


def classify_event(
    payload: dict[str, Any], tenant_id: str
) -> tuple[SemanticObservation, list[SentimentObservation]]:
    text = str(payload.get("content") or payload.get("text") or "")[:5000]
    source_event_id = str(
        payload.get("source_event_id") or payload.get("event_id") or "event_unknown"
    )
    actor_ref = str(payload.get("actor_ref") or payload.get("user_id") or "anonymous")
    actor_type = (
        SubjectType(payload.get("actor_type", "profile"))
        if payload.get("actor_type", "profile") in SubjectType._value2member_map_
        else SubjectType.OTHER
    )
    subject = str(
        payload.get("primary_subject_ref")
        or payload.get("subject_ref")
        or payload.get("target_ref")
        or "unknown_subject"
    )
    target_type = (
        SubjectType(payload.get("target_type", "other"))
        if payload.get("target_type", "other") in SubjectType._value2member_map_
        else SubjectType.OTHER
    )
    words = set(re.findall(r"[a-zA-Z_]+", text.lower()))
    pos = len(words & POSITIVE)
    neg = len(words & NEGATIVE)
    stance = StanceLabel.NEUTRAL
    if "support" in words or "approve" in words:
        stance = StanceLabel.SUPPORTIVE
    if "oppose" in words or "reject" in words:
        stance = StanceLabel.OPPOSED
    intent = IntentLabel.UNKNOWN
    for candidate in IntentLabel:
        if candidate.value in words:
            intent = candidate
            break
    speech = SpeechAct.QUESTION if "?" in text else SpeechAct.STATEMENT
    if "complain" in words or "broken" in words:
        speech = SpeechAct.COMPLAINT
    if "recommend" in words:
        speech = SpeechAct.RECOMMENDATION
    evidence = EvidenceRef(
        evidence_id=f"ev_{source_event_id}",
        source_type=str(payload.get("source_type", "event")),
        source_ref=source_event_id,
        confidence=0.9,
    )
    obs = SemanticObservation(
        tenant_id=tenant_id,
        project_id=payload.get("project_id"),
        source_event_id=source_event_id,
        source_activity_id=payload.get("source_activity_id"),
        source_type=str(payload.get("source_type", "event")),
        source_platform=payload.get("source_platform"),
        source_channel=payload.get("source_channel"),
        actor_ref=actor_ref,
        actor_type=actor_type,
        target_ref=payload.get("target_ref"),
        target_type=target_type,
        subject_refs=[SubjectRef(ref=subject, type=target_type)],
        primary_subject_ref=subject,
        campaign_id=payload.get("campaign_id"),
        creative_id=payload.get("creative_id"),
        agent_id=payload.get("agent_id"),
        wallet_id=payload.get("wallet_id"),
        language=str(payload.get("language", "en")),
        topics=sorted(
            (
                words
                & {
                    "price",
                    "pricing",
                    "quality",
                    "governance",
                    "wallet",
                    "agent",
                    "campaign",
                    "product",
                }
            )
            or {"general"}
        ),
        entity_mentions=payload.get("entity_mentions", []),
        claims=payload.get("claims", []),
        narrative_frames=payload.get("narrative_frames", []),
        stance=stance,
        intent=intent,
        speech_act=speech,
        interaction_function=speech,
        agent_semantics=[a for a in []],
        evidence_refs=[evidence],
        classification_confidence=0.85 if text else 0.2,
        consent_snapshot_id=payload.get("consent_snapshot_id"),
        purposes=payload.get("purposes", ["analytics"]),
        status=ObservationStatus.CLASSIFIED if text else ObservationStatus.ABSTAINED,
        abstention_reason=None if text else "insufficient_content",
    )
    sentiments: list[SentimentObservation] = []
    if text and subject != "unknown_subject" and (pos or neg):
        total = pos + neg
        valence = (pos - neg) / total
        emotion = EmotionLabel.JOY if valence > 0 else EmotionLabel.ANGER
        sentiments.append(
            SentimentObservation(
                semantic_observation_id=obs.observation_id,
                tenant_id=tenant_id,
                actor_ref=actor_ref,
                target_subject_ref=subject,
                source_event_id=source_event_id,
                valence=valence,
                arousal=min(1.0, total / 4),
                emotion_distribution={emotion: 0.75, EmotionLabel.NEUTRAL: 0.25},
                intensity=min(1.0, total / 3),
                stance_label=stance,
                uncertainty=0.15,
                confidence=0.82,
                consent_snapshot_id=payload.get("consent_snapshot_id"),
            )
        )
    return store.put_semantic(obs), [store.put_sentiment(s) for s in sentiments]


def entity_state(tenant_id: str, entity_ref: str) -> EntitySemanticState:
    rows = store.list_semantic(tenant_id, entity_ref)
    now = utc_now()
    topics = sorted({t for row in rows for t in row.topics})
    stance_counts: dict[StanceLabel, float] = defaultdict(float)
    intent_counts: dict[IntentLabel, float] = defaultdict(float)
    for row in rows:
        stance_counts[row.stance] += row.classification_confidence
        intent_counts[row.intent] += row.classification_confidence
    total = sum(stance_counts.values()) or 1
    return EntitySemanticState(
        tenant_id=tenant_id,
        entity_ref=entity_ref,
        entity_type=SubjectType.OTHER,
        subject_ref=entity_ref,
        window_start=(rows[0].occurred_at if rows else now - timedelta(days=1)),
        window_end=now,
        active_topics=topics,
        dominant_narratives=sorted({n for row in rows for n in row.narrative_frames}),
        stance_distribution={k: round(v / total, 4) for k, v in stance_counts.items()},
        intent_distribution={k: round(v / total, 4) for k, v in intent_counts.items()},
        semantic_summary=(
            f"{len(rows)} semantic observations for {entity_ref}" if rows else "insufficient_data"
        ),
        observation_count=len(rows),
        unique_source_count=len({r.source_event_id for r in rows}),
        model_mix={"deterministic-semantic-classifier@1.0.0": len(rows)},
        confidence=round(sum(r.classification_confidence for r in rows) / len(rows), 4)
        if rows
        else 0,
        freshness="fresh" if rows else "insufficient_data",
        evidence_refs=[e for r in rows[-5:] for e in r.evidence_refs],
    )
