"""Semantic/sentiment classification engine and in-memory repository.

Two explicitly-separated classification paths:

- The DETERMINISTIC keyword path (no provider, or the deterministic provider):
  tool-less and network-free so CI, replay and security tests never depend on
  external credentials. Its output is always stamped with the deterministic
  identity.
- The MODEL path (any other provider): ``provider.classify()`` performs real
  inference (or abstains, first-class). Keyword output is NEVER emitted under a
  model provider's identity — a model-backed observation's labels come from the
  provider's own result, and provenance stamps the actual model id/version.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from .models import (
    EmotionLabel,
    EntitySemanticState,
    EvidenceRef,
    IntentLabel,
    ObservationStatus,
    SemanticCascade,
    SemanticObservation,
    SentimentObservation,
    SpeechAct,
    StanceLabel,
    SubjectRef,
    SubjectType,
    utc_now,
)
from .providers import (
    DeterministicClassifierProvider,
    ProviderResponseError,
    SemanticClassificationRequest,
    SemanticClassificationResult,
    SemanticClassifierProvider,
    provider_identity,
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
    """Deterministic in-memory store — the local/CI default.

    The interface is async so it is drop-in interchangeable with
    :class:`services.semantic_intelligence.store.DurableSemanticSentimentStore`,
    which the startup hook injects for non-local deployment profiles.
    """

    def __init__(self) -> None:
        self.semantic: dict[str, SemanticObservation] = {}
        self.sentiment: dict[str, SentimentObservation] = {}

    async def put_semantic(self, obs: SemanticObservation) -> SemanticObservation:
        for existing in self.semantic.values():
            if (
                existing.tenant_id == obs.tenant_id
                and existing.idempotency_key == obs.idempotency_key
            ):
                return existing
        self.semantic[obs.observation_id] = obs
        return obs

    async def put_sentiment(self, obs: SentimentObservation) -> SentimentObservation:
        for existing in self.sentiment.values():
            if (
                existing.semantic_observation_id == obs.semantic_observation_id
                and existing.tenant_id == obs.tenant_id
                and existing.target_subject_ref == obs.target_subject_ref
            ):
                return existing
        self.sentiment[obs.sentiment_observation_id] = obs
        return obs

    async def list_semantic(
        self, tenant_id: str, subject: str | None = None
    ) -> list[SemanticObservation]:
        rows = [o for o in self.semantic.values() if o.tenant_id == tenant_id]
        if subject:
            rows = [o for o in rows if o.primary_subject_ref == subject]
        return sorted(rows, key=lambda o: o.occurred_at)

    async def list_sentiment(
        self, tenant_id: str, subject: str | None = None
    ) -> list[SentimentObservation]:
        rows = [o for o in self.sentiment.values() if o.tenant_id == tenant_id]
        if subject:
            rows = [o for o in rows if o.target_subject_ref == subject]
        return sorted(rows, key=lambda o: o.occurred_at)

    async def supersede(
        self, tenant_id: str, idempotency_key: str, superseded_by: str
    ) -> bool:
        changed = False
        for obs in self.semantic.values():
            if (
                obs.tenant_id == tenant_id
                and obs.idempotency_key == idempotency_key
                and obs.status != ObservationStatus.SUPERSEDED
            ):
                obs.status = ObservationStatus.SUPERSEDED
                obs.superseded_by = superseded_by
                changed = True
        return changed

    async def aggregate_counts(self, tenant_id: str | None = None) -> dict[str, Any]:
        def _counts(rows: list[Any]) -> dict[str, Any]:
            by_status: dict[str, int] = {}
            for row in rows:
                key = getattr(row.status, "value", "unknown") if hasattr(row, "status") else "unknown"
                by_status[key] = by_status.get(key, 0) + 1
            return {
                "total": len(rows),
                "tenants": len({r.tenant_id for r in rows}),
                "by_status": by_status,
            }

        sem = [o for o in self.semantic.values() if tenant_id is None or o.tenant_id == tenant_id]
        sent = [o for o in self.sentiment.values() if tenant_id is None or o.tenant_id == tenant_id]
        return {"semantic": _counts(sem), "sentiment": {"total": len(sent), "tenants": len({r.tenant_id for r in sent})}}


_store = SemanticSentimentStore()


def get_store() -> SemanticSentimentStore:
    return _store


def set_store(new_store: SemanticSentimentStore) -> None:
    """Replace the active store. Used by startup hooks and tests to inject a persistent backend."""
    global _store
    _store = new_store


SUPPORTED_LANGUAGES: frozenset[str] = frozenset({
    "en", "es", "fr", "de", "pt", "it", "nl", "pl", "sv", "da", "fi", "no",
})


class KeywordLabels(NamedTuple):
    """Deterministic keyword-derived labels (the explicit deterministic mode)."""

    words: frozenset[str]
    pos: int
    neg: int
    stance: StanceLabel
    intent: IntentLabel
    speech: SpeechAct
    topics: list[str]


def keyword_labels(text: str) -> KeywordLabels:
    """Derive the deterministic keyword classification signals for ``text``.

    Shared by the engine's deterministic path and
    :meth:`providers.DeterministicClassifierProvider.classify` so the keyword
    logic exists in exactly one place. It is only ever stamped with the
    deterministic identity — never a model provider's.
    """
    words = frozenset(re.findall(r"[a-zA-Z_]+", text.lower()))
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
    topics = sorted(
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
    )
    return KeywordLabels(words, pos, neg, stance, intent, speech, topics)


async def classify_event(
    payload: dict[str, Any],
    tenant_id: str,
    provider: SemanticClassifierProvider | None = None,
) -> tuple[SemanticObservation, list[SentimentObservation]]:
    text = str(payload.get("content") or payload.get("text") or "")[:5000]
    text_stripped = text.strip()
    language = str(payload.get("language", "en"))
    should_abstain = not text_stripped or language not in SUPPORTED_LANGUAGES
    abstention_reason: str | None = None
    if not text_stripped:
        abstention_reason = "insufficient_content"
    elif language not in SUPPORTED_LANGUAGES:
        abstention_reason = f"unsupported_language:{language}"

    occurred_at_raw: str | None = payload.get("occurred_at")
    occurred_at: datetime | None = None
    if occurred_at_raw:
        try:
            occurred_at = datetime.fromisoformat(occurred_at_raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            occurred_at = None

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
    # ── classification dispatch ──────────────────────────────────────────────
    # Deterministic path (no provider, or the deterministic provider): keyword
    # labels, deterministic provenance. Model path (any other provider): real
    # provider.classify() or a first-class abstention — keyword labels are
    # never derived under a model provider's identity.
    model_backed = provider is not None and not isinstance(
        provider, DeterministicClassifierProvider
    )
    model_result: SemanticClassificationResult | None = None
    provider_abstained = False
    if model_backed:
        pos = neg = 0
        if not should_abstain:
            # Eligible text only — ineligible text abstains before any network.
            result = await provider.classify(
                SemanticClassificationRequest(
                    tenant_id=tenant_id,
                    source_event_id=source_event_id,
                    text=text_stripped,
                    language=language,
                )
            )
            if result.abstained:
                should_abstain = True
                provider_abstained = True
                abstention_reason = result.abstention_reason or "provider_abstained"
            else:
                model_result = result
        if model_result is not None:
            # Fail closed on any contract violation a custom provider lets
            # through — a partially-valid result is never partially ingested.
            try:
                stance = StanceLabel(model_result.stance)
                intent = IntentLabel(model_result.intent)
                speech = SpeechAct(model_result.speech_act)
            except ValueError as exc:
                raise ProviderResponseError(f"invalid_label: {exc}") from None
            if not 0.0 <= model_result.confidence <= 1.0:
                raise ProviderResponseError(
                    f"schema_violation: confidence out of range: {model_result.confidence!r}"
                )
            topics = sorted(set(model_result.topics)) or ["general"]
            confidence = model_result.confidence
        else:
            # Abstained (eligibility or provider): neutral scaffolding only —
            # never keyword-derived labels under a model provider's identity.
            stance = StanceLabel.NEUTRAL
            intent = IntentLabel.UNKNOWN
            speech = SpeechAct.STATEMENT
            topics = ["general"]
            confidence = 0.0 if provider_abstained else 0.2
    else:
        labels = keyword_labels(text_stripped)
        pos, neg = labels.pos, labels.neg
        stance, intent, speech = labels.stance, labels.intent, labels.speech
        topics = labels.topics
        confidence = 0.85 if not should_abstain else 0.2
    evidence = EvidenceRef(
        evidence_id=f"ev_{source_event_id}",
        source_type=str(payload.get("source_type", "event")),
        source_ref=source_event_id,
        confidence=0.9,
    )
    rights = payload.get("rights") if isinstance(payload.get("rights"), dict) else {}
    rights_envelopes = [str(ref) for ref in rights.get("envelope_refs") or [] if ref]
    rights_decisions = [str(ref) for ref in rights.get("rights_decision_refs") or [] if ref]
    rights_grants = [str(ref) for ref in rights.get("source_grant_refs") or [] if ref]
    rights_evidence = [str(ref) for ref in rights.get("evidence_manifest_refs") or [] if ref]
    rights_lineage = [str(ref) for ref in rights.get("lineage_root_refs") or [] if ref]
    obs_kwargs: dict[str, Any] = dict(
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
        language=language,
        topics=topics,
        entity_mentions=payload.get("entity_mentions", []),
        claims=payload.get("claims", []),
        narrative_frames=payload.get("narrative_frames", []),
        stance=stance,
        intent=intent,
        speech_act=speech,
        interaction_function=speech,
        agent_semantics=[],
        evidence_refs=[evidence],
        classification_confidence=confidence,
        subject_resolution_confidence=float(payload.get("subject_resolution_confidence", 1.0)),
        consent_snapshot_id=payload.get("consent_snapshot_id"),
        purposes=payload.get("purposes", ["analytics"]),
        rights_envelope_refs=rights_envelopes,
        rights_decision_refs=rights_decisions,
        rights_source_grant_refs=rights_grants,
        rights_evidence_manifest_refs=rights_evidence,
        rights_lineage_root_refs=rights_lineage,
        rights_policy_set_ref=rights.get("policy_set_ref"),
        status=ObservationStatus.ABSTAINED if should_abstain else ObservationStatus.CLASSIFIED,
        abstention_reason=abstention_reason,
    )
    if occurred_at is not None:
        obs_kwargs["occurred_at"] = occurred_at
    sentiment_kwargs: dict[str, Any] = {}
    if provider is not None:
        # Provenance is ALWAYS truthful. Deterministic provider: its explicit
        # deterministic 'id@version'. Model provider with a real result: the
        # ACTUAL model id/version the provider inferred with. Model provider
        # abstaining (or ineligible text): the resolved provider's identity with
        # status=abstained + reason — never a classified production stamp on
        # keyword output. model_version participates in stable_hash /
        # idempotency_key (models.SemanticObservation.finalize): INTENDED — a
        # new provider version yields a new observation identity, so
        # reclassification under a new model is never deduplicated away.
        if model_result is not None:
            model_id, model_version = model_result.model_id, model_result.model_version
        else:
            model_id, model_version = provider_identity(provider.name)
        obs_kwargs["model_id"] = model_id
        obs_kwargs["model_version"] = model_version
        sentiment_kwargs = {"model_id": model_id, "model_version": model_version}
    obs = SemanticObservation(**obs_kwargs)

    sentiments: list[SentimentObservation] = []
    if not should_abstain and subject != "unknown_subject":
        if model_result is not None and model_result.valence is not None:
            # Model path: sentiment comes from the provider's own valence.
            valence = model_result.valence
            magnitude = abs(valence)
            if valence == 0:
                emotion = EmotionLabel.NEUTRAL
            elif valence > 0:
                emotion = EmotionLabel.JOY
            else:
                emotion = EmotionLabel.ANGER
            sentiments = [
                SentimentObservation(
                    semantic_observation_id=obs.observation_id,
                    tenant_id=tenant_id,
                    actor_ref=actor_ref,
                    target_subject_ref=subject,
                    source_event_id=source_event_id,
                    valence=valence,
                    arousal=min(1.0, magnitude),
                    emotion_distribution={emotion: 0.75, EmotionLabel.NEUTRAL: 0.25},
                    intensity=min(1.0, magnitude),
                    stance_label=stance,
                    uncertainty=round(1.0 - model_result.confidence, 4),
                    confidence=model_result.confidence,
                    consent_snapshot_id=payload.get("consent_snapshot_id"),
                    rights_envelope_refs=rights_envelopes,
                    rights_decision_refs=rights_decisions,
                    rights_source_grant_refs=rights_grants,
                    rights_evidence_manifest_refs=rights_evidence,
                    rights_lineage_root_refs=rights_lineage,
                    rights_policy_set_ref=rights.get("policy_set_ref"),
                    **sentiment_kwargs,
                )
            ]
        elif model_result is None and not model_backed and (pos or neg):
            # Deterministic keyword path (unchanged).
            total = pos + neg
            valence = (pos - neg) / total
            if valence == 0:
                emotion = EmotionLabel.NEUTRAL
            elif valence > 0:
                emotion = EmotionLabel.JOY
            else:
                emotion = EmotionLabel.ANGER
            sentiments = [
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
                    rights_envelope_refs=rights_envelopes,
                    rights_decision_refs=rights_decisions,
                    rights_source_grant_refs=rights_grants,
                    rights_evidence_manifest_refs=rights_evidence,
                    rights_lineage_root_refs=rights_lineage,
                    rights_policy_set_ref=rights.get("policy_set_ref"),
                    **sentiment_kwargs,
                )
            ]
    return obs, sentiments


async def entity_state(tenant_id: str, entity_ref: str) -> EntitySemanticState:
    """Weighted reduction of an entity's observations into semantic state.

    Delegates to the versioned weighted reducer (multiplicative confidence policy
    with recency decay, duplication penalty and contradiction handling).
    """
    from .reducers import reduce_entity_state

    rows = await get_store().list_semantic(tenant_id, entity_ref)
    return reduce_entity_state(tenant_id, entity_ref, rows)


async def cascades_for_tenant(tenant_id: str) -> list[SemanticCascade]:
    rows = await get_store().list_semantic(tenant_id)
    grouped: dict[tuple[str, str, StanceLabel], list[SemanticObservation]] = defaultdict(list)
    for row in rows:
        for topic in row.topics or ["general"]:
            if row.status == ObservationStatus.CLASSIFIED:
                grouped[(row.primary_subject_ref, topic, row.stance)].append(row)
    cascades: list[SemanticCascade] = []
    for (subject, topic, stance), observations in grouped.items():
        if len(observations) < 2:
            continue
        actors = sorted({o.actor_ref for o in observations})
        first = observations[0]
        last = observations[-1]
        duration = max((last.occurred_at - first.occurred_at).total_seconds(), 1)
        confidence = sum(o.classification_confidence for o in observations) / len(observations)
        cascade_key = "|".join([tenant_id, subject, topic, stance.value])
        cascade_id = "scas_" + hashlib.sha256(cascade_key.encode()).hexdigest()[:24]
        cascades.append(
            SemanticCascade(
                cascade_id=cascade_id,
                tenant_id=tenant_id,
                subject_ref=subject,
                topic_ref=topic,
                stance=stance,
                origin_ref=first.observation_id,
                campaign_id=first.campaign_id,
                creative_id=first.creative_id,
                seed_entities=actors[:3],
                seed_observations=[o.observation_id for o in observations[:3]],
                first_observed_at=first.occurred_at,
                last_observed_at=last.occurred_at,
                exposed_entities=actors,
                adopting_entities=actors
                if stance
                in {
                    StanceLabel.SUPPORTIVE,
                    StanceLabel.STRONGLY_SUPPORTIVE,
                    StanceLabel.WEAKLY_SUPPORTIVE,
                }
                else [],
                rejecting_entities=actors
                if stance
                in {StanceLabel.OPPOSED, StanceLabel.STRONGLY_OPPOSED, StanceLabel.WEAKLY_OPPOSED}
                else [],
                transmitting_entities=actors[: max(1, len(actors) // 2)],
                affected_relationship_layers=sorted(
                    {o.relationship_layer for o in observations if o.relationship_layer}
                ),
                depth=min(3, max(1, len(actors) - 1)),
                breadth=len(actors),
                velocity=round(len(observations) / duration, 6),
                reproduction_rate=round(max(len(actors) - 1, 0) / max(len(actors), 1), 4),
                confidence=round(confidence, 4),
                evidence_refs=[e for o in observations[:5] for e in o.evidence_refs],
            )
        )
    return cascades
