"""Canonical semantic-sentiment intelligence contracts.

These Pydantic contracts intentionally live in the backend canonical domain and
are consumed by API routes, tests, release gates, and generated documentation.
They extend the compact SemanticContextEnvelope instead of replacing it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

TAXONOMY_VERSION = "semantic-sentiment-taxonomy.v1"
SCHEMA_VERSION = "semantic-sentiment.v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SubjectType(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    ACCOUNT = "account"
    PROFILE = "profile"
    AGENT = "agent"
    WALLET = "wallet"
    CAMPAIGN = "campaign"
    CREATIVE = "creative"
    PRODUCT = "product"
    SERVICE = "service"
    OFFER = "offer"
    FEATURE = "feature"
    BRAND = "brand"
    PROTOCOL = "protocol"
    TOKEN = "token"
    CONTRACT = "contract"
    GOVERNANCE_PROPOSAL = "governance_proposal"
    TRANSACTION = "transaction"
    TOPIC = "topic"
    NARRATIVE = "narrative"
    CLAIM = "claim"
    LOCATION = "location"
    CHANNEL = "channel"
    PLATFORM = "platform"
    WORKFLOW = "workflow"
    JOURNEY = "journey"
    EPISODE = "episode"
    OTHER = "other"


class StanceLabel(str, Enum):
    STRONGLY_SUPPORTIVE = "strongly_supportive"
    SUPPORTIVE = "supportive"
    WEAKLY_SUPPORTIVE = "weakly_supportive"
    NEUTRAL = "neutral"
    UNCERTAIN = "uncertain"
    MIXED = "mixed"
    WEAKLY_OPPOSED = "weakly_opposed"
    OPPOSED = "opposed"
    STRONGLY_OPPOSED = "strongly_opposed"
    NOT_APPLICABLE = "not_applicable"
    ABSTAINED = "abstained"


class IntentLabel(str, Enum):
    DISCOVER = "discover"
    INVESTIGATE = "investigate"
    COMPARE = "compare"
    EVALUATE = "evaluate"
    PURCHASE = "purchase"
    SUBSCRIBE = "subscribe"
    RENEW = "renew"
    CANCEL = "cancel"
    CHURN = "churn"
    RETURN = "return"
    REFER = "refer"
    RECOMMEND = "recommend"
    SHARE = "share"
    COMPLAIN = "complain"
    REQUEST_HELP = "request_help"
    ESCALATE = "escalate"
    APPROVE = "approve"
    REJECT = "reject"
    DELEGATE = "delegate"
    CORRECT = "correct"
    NEGOTIATE = "negotiate"
    VOTE = "vote"
    TRANSACT = "transact"
    BRIDGE = "bridge"
    STAKE = "stake"
    SWAP = "swap"
    TRANSFER = "transfer"
    GOVERN = "govern"
    CLAIM_REWARD = "claim_reward"
    AVOID = "avoid"
    MONITOR = "monitor"
    LEARN = "learn"
    UNKNOWN = "unknown"


class SpeechAct(str, Enum):
    STATEMENT = "statement"
    QUESTION = "question"
    COMMAND = "command"
    REQUEST = "request"
    RECOMMENDATION = "recommendation"
    COMPLAINT = "complaint"
    PRAISE = "praise"
    CRITICISM = "criticism"
    APPROVAL = "approval"
    REJECTION = "rejection"
    CORRECTION = "correction"
    WARNING = "warning"
    REFERRAL = "referral"
    COMPARISON = "comparison"
    NEGOTIATION = "negotiation"
    AGREEMENT = "agreement"
    DISAGREEMENT = "disagreement"
    ESCALATION = "escalation"
    CONFIRMATION = "confirmation"
    EXPLANATION = "explanation"
    DELEGATION = "delegation"
    REPORT = "report"
    UNKNOWN = "unknown"


class EmotionLabel(str, Enum):
    JOY = "joy"
    TRUST = "trust"
    ANTICIPATION = "anticipation"
    SURPRISE = "surprise"
    SADNESS = "sadness"
    FEAR = "fear"
    ANGER = "anger"
    DISGUST = "disgust"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class AgentSemanticLabel(str, Enum):
    GOAL = "goal"
    CONSTRAINT = "constraint"
    TASK = "task"
    PLAN = "plan"
    DECISION = "decision"
    RECOMMENDATION = "recommendation"
    TOOL_SELECTION = "tool_selection"
    CONFIDENCE = "confidence"
    UNCERTAINTY = "uncertainty"
    POLICY_RESULT = "policy_result"
    DELEGATION = "delegation"
    CORRECTION = "correction"
    FEEDBACK = "feedback"
    OUTCOME = "outcome"
    ALIGNMENT = "alignment"
    DISAGREEMENT = "disagreement"
    ESCALATION = "escalation"


class PropagationRole(str, Enum):
    DIRECT_TRANSMISSION = "direct_transmission"
    EXPOSURE_CHANNEL = "exposure_channel"
    BEHAVIORAL_OUTCOME = "behavioral_outcome"
    FACILITATIVE_CONTEXT = "facilitative_context"
    STRUCTURAL_CONTEXT = "structural_context"
    EXCLUDED = "excluded"


class CausalConfidence(str, Enum):
    OBSERVED_SEQUENCE = "observed_sequence"
    CORRELATED_ASSOCIATION = "correlated_association"
    PROBABLE_PROPAGATION = "probable_propagation"
    HIGH_CONFIDENCE_PROPAGATION = "high_confidence_propagation"
    EXPERIMENTALLY_SUPPORTED = "experimentally_supported"


class ObservationStatus(str, Enum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    CONSENT_RESTRICTED = "consent_restricted"
    QUARANTINED = "quarantined"


class SubjectRef(BaseModel):
    ref: str
    type: SubjectType = SubjectType.OTHER
    label: str | None = None


class EvidenceRef(BaseModel):
    evidence_id: str
    source_type: str
    source_ref: str
    observed_at: datetime = Field(default_factory=utc_now)
    confidence: float = Field(default=1.0, ge=0, le=1)


class SemanticObservation(BaseModel):
    observation_id: str = Field(default_factory=lambda: f"sem_{uuid4().hex}")
    tenant_id: str
    project_id: str | None = None
    source_event_id: str
    source_activity_id: str | None = None
    source_type: str
    source_platform: str | None = None
    source_channel: str | None = None
    actor_ref: str
    actor_type: SubjectType
    target_ref: str | None = None
    target_type: SubjectType | None = None
    subject_refs: list[SubjectRef] = Field(default_factory=list)
    primary_subject_ref: str
    relationship_ref: str | None = None
    relationship_layer: str | None = None
    interaction_mode: str | None = None
    session_id: str | None = None
    journey_id: str | None = None
    journey_version_id: str | None = None
    journey_step_id: str | None = None
    campaign_id: str | None = None
    creative_id: str | None = None
    agent_id: str | None = None
    wallet_id: str | None = None
    location_ref: str | None = None
    language: str = "en"
    occurred_at: datetime = Field(default_factory=utc_now)
    received_at: datetime = Field(default_factory=utc_now)
    processed_at: datetime = Field(default_factory=utc_now)
    topics: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    entity_mentions: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    narrative_frames: list[str] = Field(default_factory=list)
    stance: StanceLabel = StanceLabel.NOT_APPLICABLE
    intent: IntentLabel = IntentLabel.UNKNOWN
    speech_act: SpeechAct = SpeechAct.UNKNOWN
    interaction_function: SpeechAct = SpeechAct.UNKNOWN
    agent_semantics: list[AgentSemanticLabel] = Field(default_factory=list)
    semantic_layers: list[str] = Field(default_factory=lambda: ["semantic"])
    semantic_deltas: list[dict[str, Any]] = Field(default_factory=list)
    workflow_refs: list[str] = Field(default_factory=list)
    episode_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    identity_confidence: float = Field(default=1, ge=0, le=1)
    subject_resolution_confidence: float = Field(default=1, ge=0, le=1)
    campaign_resolution_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_confidence: float = Field(default=0.5, ge=0, le=1)
    model_id: str = "deterministic-semantic-classifier"
    model_version: str = "1.0.0"
    taxonomy_version: str = TAXONOMY_VERSION
    schema_version: str = SCHEMA_VERSION
    consent_snapshot_id: str | None = None
    purposes: list[str] = Field(default_factory=lambda: ["analytics"])
    privacy_class: str = "behavioral"
    retention_class: str = "standard_90d"
    data_quality: dict[str, Any] = Field(default_factory=dict)
    stable_hash: str | None = None
    idempotency_key: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    status: ObservationStatus = ObservationStatus.CLASSIFIED
    abstention_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def finalize(self) -> "SemanticObservation":
        if not self.subject_refs:
            self.subject_refs = [
                SubjectRef(ref=self.primary_subject_ref, type=self.target_type or SubjectType.OTHER)
            ]
        if self.campaign_id and not (
            self.campaign_id.startswith("camp_") or _UUID_RE.match(self.campaign_id)
        ):
            raise ValueError(
                "campaign_id must be a canonical campaign id (camp_*) or a UUID"
            )
        # model_version participates in the identity hash INTENTIONALLY: an
        # observation produced by a new provider version (engine.classify_event
        # stamps the resolved provider's 'id@version') is a NEW observation
        # identity, so reprocessing under a new model is never deduped away.
        base = "|".join(
            [
                self.tenant_id,
                self.source_event_id,
                self.source_type,
                self.primary_subject_ref,
                self.taxonomy_version,
                self.model_version,
            ]
        )
        digest = hashlib.sha256(base.encode()).hexdigest()[:24]
        self.stable_hash = self.stable_hash or digest
        self.idempotency_key = self.idempotency_key or f"semantic:{digest}"
        return self


class SentimentObservation(BaseModel):
    sentiment_observation_id: str = Field(default_factory=lambda: f"sent_{uuid4().hex}")
    semantic_observation_id: str
    tenant_id: str
    actor_ref: str
    target_subject_ref: str
    source_event_id: str
    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=0, le=1)
    dominance: float | None = Field(default=None, ge=0, le=1)
    emotion_distribution: dict[EmotionLabel, float] = Field(default_factory=dict)
    intensity: float = Field(default=0.0, ge=0, le=1)
    stance_label: StanceLabel = StanceLabel.NOT_APPLICABLE
    uncertainty: float = Field(default=0.0, ge=0, le=1)
    sarcasm_probability: float = Field(default=0.0, ge=0, le=1)
    contradiction_probability: float = Field(default=0.0, ge=0, le=1)
    explicit_or_inferred: Literal["explicit", "inferred", "abstained"] = "explicit"
    evidence_type: str = "expressive_content"
    model_id: str = "deterministic-sentiment-classifier"
    model_version: str = "1.0.0"
    confidence: float = Field(default=0.5, ge=0, le=1)
    baseline_ref: str | None = None
    consent_snapshot_id: str | None = None
    privacy_class: str = "behavioral"
    # Consent state — a consent restriction/erasure marks a subject's (or actor's)
    # rows so the Gold sentiment reducer drops them, mirroring
    # SemanticObservation.status. Defaults CLASSIFIED so existing/new rows are
    # active; only a retraction moves a row out of the active set.
    status: ObservationStatus = ObservationStatus.CLASSIFIED
    occurred_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("target_subject_ref")
    @classmethod
    def target_required(cls, value: str) -> str:
        if not value:
            raise ValueError("target-specific sentiment requires target_subject_ref")
        return value


class EntitySemanticState(BaseModel):
    state_id: str = Field(default_factory=lambda: f"ess_{uuid4().hex}")
    tenant_id: str
    entity_ref: str
    entity_type: SubjectType
    subject_ref: str
    window_start: datetime
    window_end: datetime
    active_topics: list[str] = Field(default_factory=list)
    dominant_narratives: list[str] = Field(default_factory=list)
    stance_distribution: dict[StanceLabel, float] = Field(default_factory=dict)
    intent_distribution: dict[IntentLabel, float] = Field(default_factory=dict)
    semantic_summary: str = "insufficient_data"
    semantic_baseline: dict[str, Any] = Field(default_factory=dict)
    semantic_delta: dict[str, Any] = Field(default_factory=dict)
    persistence: str = "medium_ttl"
    volatility: float = 0
    observation_count: int = 0
    unique_source_count: int = 0
    model_mix: dict[str, int] = Field(default_factory=dict)
    confidence: float = 0
    freshness: str = "unknown"
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    version: int = 1
    computed_at: datetime = Field(default_factory=utc_now)


class RelationshipSemanticState(BaseModel):
    state_id: str = Field(default_factory=lambda: f"rss_{uuid4().hex}")
    tenant_id: str
    relationship_ref: str
    source_ref: str
    target_ref: str
    relationship_layer: str
    subject_ref: str
    dominant_topics: list[str] = Field(default_factory=list)
    shared_narratives: list[str] = Field(default_factory=list)
    stance_alignment: float = Field(default=0, ge=-1, le=1)
    semantic_alignment: float = Field(default=0, ge=0, le=1)
    disagreement_score: float = Field(default=0, ge=0, le=1)
    trust_signal: float = Field(default=0, ge=0, le=1)
    responsiveness: float = Field(default=0, ge=0, le=1)
    reciprocity: float = Field(default=0, ge=0, le=1)
    influence_direction: str = "unknown"
    interaction_quality: str = "insufficient_data"
    propagation_role: PropagationRole = PropagationRole.STRUCTURAL_CONTEXT
    support_count: int = 0
    confidence: float = Field(default=0, ge=0, le=1)
    valid_from: datetime
    valid_to: datetime | None = None
    computed_at: datetime = Field(default_factory=utc_now)


class RelationshipSentimentState(BaseModel):
    relationship_ref: str
    subject_ref: str
    source_sentiment: float = Field(default=0, ge=-1, le=1)
    target_sentiment: float = Field(default=0, ge=-1, le=1)
    sentiment_alignment: float = Field(default=0, ge=-1, le=1)
    sentiment_delta: float = 0
    source_to_target_shift: float = 0
    target_to_source_shift: float = 0
    adoption_probability: float = Field(default=0, ge=0, le=1)
    transmission_probability: float = Field(default=0, ge=0, le=1)
    retransmission_probability: float = Field(default=0, ge=0, le=1)
    behavioral_followthrough: float = Field(default=0, ge=0, le=1)
    confidence: float = Field(default=0, ge=0, le=1)
    support_count: int = 0
    valid_from: datetime
    valid_to: datetime | None = None
    computed_at: datetime = Field(default_factory=utc_now)


class SemanticEpisode(BaseModel):
    episode_id: str = Field(default_factory=lambda: f"sepi_{uuid4().hex}")
    tenant_id: str
    episode_type: str
    subject_refs: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    relationship_refs: list[str] = Field(default_factory=list)
    workflow_refs: list[str] = Field(default_factory=list)
    journey_refs: list[str] = Field(default_factory=list)
    campaign_refs: list[str] = Field(default_factory=list)
    narrative_refs: list[str] = Field(default_factory=list)
    observation_refs: list[str] = Field(default_factory=list)
    start_at: datetime
    end_at: datetime | None = None
    status: str = "active"
    sequence_summary: str = "insufficient_data"
    semantic_summary: str = "insufficient_data"
    sentiment_start_state: dict[str, Any] = Field(default_factory=dict)
    sentiment_end_state: dict[str, Any] = Field(default_factory=dict)
    behavioral_outcomes: dict[str, Any] = Field(default_factory=dict)
    economic_outcomes: dict[str, Any] = Field(default_factory=dict)
    graph_outcomes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    model_version: str = "1.0.0"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SemanticCascade(BaseModel):
    cascade_id: str = Field(default_factory=lambda: f"scas_{uuid4().hex}")
    tenant_id: str
    cascade_type: str = "narrative_propagation"
    subject_ref: str
    topic_ref: str | None = None
    narrative_ref: str | None = None
    stance: StanceLabel = StanceLabel.NEUTRAL
    sentiment_signature: dict[str, Any] = Field(default_factory=dict)
    origin_type: str = "observation"
    origin_ref: str | None = None
    campaign_id: str | None = None
    creative_id: str | None = None
    seed_entities: list[str] = Field(default_factory=list)
    seed_observations: list[str] = Field(default_factory=list)
    first_observed_at: datetime
    last_observed_at: datetime
    active_status: str = "active"
    exposed_entities: list[str] = Field(default_factory=list)
    adopting_entities: list[str] = Field(default_factory=list)
    rejecting_entities: list[str] = Field(default_factory=list)
    resistant_entities: list[str] = Field(default_factory=list)
    transmitting_entities: list[str] = Field(default_factory=list)
    retransmitting_entities: list[str] = Field(default_factory=list)
    affected_clusters: list[str] = Field(default_factory=list)
    affected_locations: list[str] = Field(default_factory=list)
    affected_relationship_layers: list[str] = Field(default_factory=list)
    path_refs: list[str] = Field(default_factory=list)
    traversal_snapshot_refs: list[str] = Field(default_factory=list)
    depth: int = 0
    breadth: int = 0
    velocity: float = 0
    adoption_lag: float = 0
    behavioral_lag: float = 0
    persistence: float = 0
    half_life: float = 0
    reproduction_rate: float = 0
    causal_confidence: CausalConfidence = CausalConfidence.OBSERVED_SEQUENCE
    behavior_outcomes: dict[str, Any] = Field(default_factory=dict)
    economic_outcomes: dict[str, Any] = Field(default_factory=dict)
    graph_outcomes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    model_version: str = "1.0.0"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
