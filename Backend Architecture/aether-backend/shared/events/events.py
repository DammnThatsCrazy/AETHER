"""
Aether Shared — @aether/events
Event schema definitions, producer/consumer wrappers, dead-letter handling.
Used by: Ingestion, Identity, Analytics, ML Serving, Agent.

Backend selection:
- AETHER_ENV=local → in-memory event bus (no Kafka required)
- AETHER_ENV=staging/production → Kafka via aiokafka
  Set KAFKA_BOOTSTRAP_SERVERS env var.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.events")

EventHandler = Callable[["Event"], Awaitable[None]]

# Optional aiokafka import
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    AIOKafkaProducer = None  # type: ignore[misc, assignment]
    AIOKafkaConsumer = None  # type: ignore[misc, assignment]
    KAFKA_AVAILABLE = False

# Optional boto3 import (used for SQS backend)
try:
    import boto3 as _boto3_events
    BOTO3_EVENTS_AVAILABLE = True
except ImportError:
    _boto3_events = None  # type: ignore[assignment]
    BOTO3_EVENTS_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _kafka_bootstrap() -> str:
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")


def _event_broker() -> str:
    return os.getenv("EVENT_BROKER", "kafka").lower()


def _sqs_queue_url() -> str:
    return os.getenv("SQS_QUEUE_URL", "")


def _sns_topic_arn() -> str:
    return os.getenv("SNS_TOPIC_ARN", "")


def _sqs_dlq_queue_url() -> str:
    """Dedicated dead-letter queue, when one is provisioned separately."""
    return os.getenv("SQS_DLQ_QUEUE_URL", "")


class DLQPublishError(RuntimeError):
    """A durable dead-letter publish could not be completed.

    Raised rather than swallowed so the caller leaves the source message
    unacknowledged: redelivery is recoverable, a silently dropped poison event
    is not.
    """


# ═══════════════════════════════════════════════════════════════════════════
# EVENT TOPICS
# ═══════════════════════════════════════════════════════════════════════════

class Topic(str, Enum):
    # Ingestion
    SDK_EVENTS_RAW = "aether.sdk.events.raw"
    SDK_EVENTS_VALIDATED = "aether.sdk.events.validated"
    API_FEED_RAW = "aether.api.feed.raw"

    # Identity
    IDENTITY_RESOLVED = "aether.identity.resolved"
    IDENTITY_MERGED = "aether.identity.merged"
    IDENTITY_SPLIT = "aether.identity.split"
    PROFILE_UPDATED = "aether.profile.updated"

    # Analytics
    SESSION_SCORED = "aether.analytics.session.scored"
    ANOMALY_DETECTED = "aether.analytics.anomaly"

    # ML
    PREDICTION_GENERATED = "aether.ml.prediction"
    MODEL_UPDATED = "aether.ml.model.updated"

    # Agent
    AGENT_DISCOVERY = "aether.agent.discovery"
    AGENT_ENRICHMENT = "aether.agent.enrichment"

    # Campaign
    ATTRIBUTION_CALCULATED = "aether.campaign.attribution"
    CAMPAIGN_CREATED = "aether.campaign.created"
    CAMPAIGN_UPDATED = "aether.campaign.updated"
    CAMPAIGN_DELETED = "aether.campaign.deleted"
    TOUCHPOINT_RECORDED = "aether.campaign.touchpoint.recorded"

    # Measurement (canonical measurement domain events)
    TOUCHPOINT_PROJECTED = "aether.measurement.touchpoint.projected"
    CONVERSION_CONFIRMED = "aether.measurement.conversion.confirmed"
    JOURNEY_REBUILT = "aether.measurement.journey.rebuilt"
    ATTRIBUTION_RUN_COMPLETE = "aether.measurement.attribution.run.complete"
    SPEND_RECORD_UPSERTED = "aether.measurement.spend.upserted"

    # Consent
    CONSENT_UPDATED = "aether.consent.updated"
    DATA_SUBJECT_REQUEST = "aether.consent.dsr"

    # Identity Resolution
    RESOLUTION_EVALUATED = "aether.resolution.evaluated"
    RESOLUTION_AUTO_MERGED = "aether.resolution.auto_merged"
    RESOLUTION_FLAGGED = "aether.resolution.flagged"
    RESOLUTION_APPROVED = "aether.resolution.approved"
    RESOLUTION_REJECTED = "aether.resolution.rejected"
    FINGERPRINT_OBSERVED = "aether.identity.fingerprint.observed"
    IP_OBSERVED = "aether.identity.ip.observed"

    # Semantic Intelligence — outbound emissions from the semantic worker.
    SEMANTIC_OBSERVED = "aether.semantic.observed"
    SEMANTIC_STATE_RECOMPUTED = "aether.semantic.state.recomputed"
    SEMANTIC_REVIEW_ENQUEUED = "aether.semantic.review.enqueued"

    # Intelligence Graph — Agent Behavioral (L2)
    AGENT_TASK_STARTED = "aether.agent.task.started"
    AGENT_TASK_COMPLETED = "aether.agent.task.completed"
    AGENT_DECISION_MADE = "aether.agent.decision.made"
    AGENT_STATE_SNAPSHOT = "aether.agent.state.snapshot"
    AGENT_GROUND_TRUTH = "aether.agent.ground_truth"

    # Intelligence Graph — Agent-to-Human (A2H)
    AGENT_NOTIFICATION_SENT = "aether.agent.notification.sent"
    AGENT_RECOMMENDATION_MADE = "aether.agent.recommendation.made"
    AGENT_RESULT_DELIVERED = "aether.agent.result.delivered"
    AGENT_ESCALATION_RAISED = "aether.agent.escalation.raised"

    # Intelligence Graph — Commerce (L3a)
    PAYMENT_SENT = "aether.commerce.payment.sent"
    AGENT_HIRED = "aether.commerce.agent.hired"
    SERVICE_PURCHASED = "aether.commerce.service.purchased"
    FEE_ELIMINATED = "aether.commerce.fee.eliminated"

    # Intelligence Graph — On-Chain Actions (L0)
    ACTION_RECORDED = "aether.onchain.action.recorded"
    CONTRACT_DEPLOYED = "aether.onchain.contract.deployed"
    CONTRACT_CALLED = "aether.onchain.contract.called"

    # Intelligence Graph — x402 Payments (L3b)
    X402_PAYMENT_CAPTURED = "aether.x402.payment.captured"

    # Intelligence Graph — Agentic Commerce Control Plane (L3b+)
    COMMERCE_CHALLENGE_ISSUED = "aether.commerce.challenge.issued"
    COMMERCE_REQUIREMENT_GENERATED = "aether.commerce.requirement.generated"
    COMMERCE_APPROVAL_REQUESTED = "aether.commerce.approval.requested"
    COMMERCE_APPROVAL_ASSIGNED = "aether.commerce.approval.assigned"
    COMMERCE_APPROVAL_APPROVED = "aether.commerce.approval.approved"
    COMMERCE_APPROVAL_REJECTED = "aether.commerce.approval.rejected"
    COMMERCE_APPROVAL_ESCALATED = "aether.commerce.approval.escalated"
    COMMERCE_APPROVAL_EXPIRED = "aether.commerce.approval.expired"
    COMMERCE_APPROVAL_REVOKED = "aether.commerce.approval.revoked"
    COMMERCE_PAYMENT_SUBMITTED = "aether.commerce.payment.submitted"
    COMMERCE_VERIFICATION_STARTED = "aether.commerce.verification.started"
    COMMERCE_VERIFICATION_SUCCEEDED = "aether.commerce.verification.succeeded"
    COMMERCE_VERIFICATION_FAILED = "aether.commerce.verification.failed"
    COMMERCE_SETTLEMENT_STARTED = "aether.commerce.settlement.started"
    COMMERCE_SETTLEMENT_PENDING = "aether.commerce.settlement.pending"
    COMMERCE_SETTLEMENT_COMPLETED = "aether.commerce.settlement.completed"
    COMMERCE_SETTLEMENT_FAILED = "aether.commerce.settlement.failed"
    COMMERCE_ENTITLEMENT_GRANTED = "aether.commerce.entitlement.granted"
    COMMERCE_ENTITLEMENT_REUSED = "aether.commerce.entitlement.reused"
    COMMERCE_ENTITLEMENT_REVOKED = "aether.commerce.entitlement.revoked"
    COMMERCE_ENTITLEMENT_EXPIRED = "aether.commerce.entitlement.expired"
    COMMERCE_ACCESS_GRANTED = "aether.commerce.access.granted"
    COMMERCE_ACCESS_DENIED = "aether.commerce.access.denied"
    COMMERCE_POLICY_DENIED = "aether.commerce.policy.denied"
    COMMERCE_FACILITATOR_ROUTE_SELECTED = "aether.commerce.facilitator.route_selected"
    COMMERCE_KYBER_ACTION_LOGGED = "aether.commerce.kyber.action_logged"
    COMMERCE_OPERATOR_ACTION_LOGGED = "aether.commerce.operator.action_logged"
    COMMERCE_REPLAY_EXECUTED = "aether.commerce.replay.executed"
    COMMERCE_RECONCILIATION_TASK_CREATED = "aether.commerce.reconciliation.task_created"
    COMMERCE_RECONCILIATION_TASK_RESOLVED = "aether.commerce.reconciliation.task_resolved"

    # Extraction Defense Mesh
    ML_EXTRACTION_REQUEST_SEEN = "aether.extraction.request.seen"
    ML_EXTRACTION_IDENTITY_RESOLVED = "aether.extraction.identity.resolved"
    ML_EXTRACTION_SIGNAL_COMPUTED = "aether.extraction.signal.computed"
    ML_EXTRACTION_SCORE_UPDATED = "aether.extraction.score.updated"
    ML_EXTRACTION_POLICY_APPLIED = "aether.extraction.policy.applied"
    ML_EXTRACTION_CANARY_HIT = "aether.extraction.canary.hit"
    ML_EXTRACTION_ALERT_OPENED = "aether.extraction.alert.opened"
    ML_EXTRACTION_CLUSTER_ESCALATED = "aether.extraction.cluster.escalated"

    # ── Profile 360 — Multi-Entity, Delegation, Flows, Behavior (additive) ─
    # All new topics; no existing topic is renamed or repurposed.
    ENTITY_CREATED = "aether.entity.created"
    ENTITY_UPDATED = "aether.entity.updated"
    ENTITY_IDENTIFIER_LINKED = "aether.entity.identifier.linked"
    ENTITY_IDENTIFIER_UNLINKED = "aether.entity.identifier.unlinked"
    ENTITY_MEMBERSHIP_ADDED = "aether.entity.membership.added"

    DELEGATION_CREATED = "aether.delegation.created"
    DELEGATION_REVOKED = "aether.delegation.revoked"
    DELEGATION_VALIDATED = "aether.delegation.validated"
    DELEGATION_REJECTED = "aether.delegation.rejected"

    FLOW_TRANSFER = "aether.flow.transfer"
    FLOW_WALLET_LINKED = "aether.flow.wallet.linked"

    AGENT_EXECUTION_STARTED = "aether.agent.execution.started"
    AGENT_EXECUTION_COMPLETED = "aether.agent.execution.completed"
    AGENT_EXECUTION_FAILED = "aether.agent.execution.failed"
    AGENT_EXECUTION_RECOVERED = "aether.agent.execution.recovered"

    BEHAVIOR_SESSION_STARTED = "aether.behavior.session.started"
    BEHAVIOR_SESSION_ENDED = "aether.behavior.session.ended"
    BEHAVIOR_EVENT_RECORDED = "aether.behavior.event.recorded"
    BEHAVIOR_PATTERN_DETECTED = "aether.behavior.pattern.detected"
    BEHAVIOR_PROFILE_UPDATED = "aether.behavior.profile.updated"

    JOURNEY_STARTED = "aether.journey.started"
    JOURNEY_ACTOR_JOINED = "aether.journey.actor.joined"
    JOURNEY_ACTOR_LEFT = "aether.journey.actor.left"
    JOURNEY_CONVERTED = "aether.journey.converted"
    JOURNEY_ABANDONED = "aether.journey.abandoned"

    INVESTIGATION_CASE_CREATED = "aether.investigation.case.created"
    INVESTIGATION_CASE_UPDATED = "aether.investigation.case.updated"
    INVESTIGATION_STATUS_CHANGED = "aether.investigation.status.changed"
    GOVERNANCE_DECISION_EVALUATED = "aether.governance.decision.evaluated"
    EVENT_REPLAY_SUBMITTED = "aether.event.replay.submitted"
    EVENT_REPLAY_COMPLETED = "aether.event.replay.completed"
    EVENT_REPLAY_CANCELLED = "aether.event.replay.cancelled"

    # ── Cognitive Integrity System ───────────────────────────────────────
    # Graph mutation lifecycle
    CIS_GRAPH_MUTATION_CREATED           = "aether.cis.graph.mutation.created"
    CIS_GRAPH_MUTATION_ACCEPTED          = "aether.cis.graph.mutation.accepted"
    CIS_GRAPH_MUTATION_REJECTED          = "aether.cis.graph.mutation.rejected"
    CIS_GRAPH_MUTATION_QUARANTINED       = "aether.cis.graph.mutation.quarantined"
    # Retrieval observability
    CIS_RETRIEVAL_EXECUTED               = "aether.cis.retrieval.executed"
    CIS_RETRIEVAL_CONTEXT_SELECTED       = "aether.cis.retrieval.context.selected"
    CIS_RETRIEVAL_INSTABILITY_DETECTED   = "aether.cis.retrieval.instability.detected"
    CIS_RETRIEVAL_CONTAMINATION_DETECTED = "aether.cis.retrieval.contamination.detected"
    # Generation telemetry
    CIS_GENERATION_STARTED               = "aether.cis.generation.started"
    CIS_GENERATION_COMPLETED             = "aether.cis.generation.completed"
    CIS_GENERATION_CLAIM_EXTRACTED       = "aether.cis.generation.claim.extracted"
    CIS_GENERATION_UNGROUNDED_DETECTED   = "aether.cis.generation.ungrounded.detected"
    # Semantic drift
    CIS_SEMANTIC_DRIFT_DETECTED          = "aether.cis.semantic.drift.detected"
    CIS_SEMANTIC_CLUSTER_INSTABILITY     = "aether.cis.semantic.cluster.instability.detected"
    CIS_SEMANTIC_EMBEDDING_DEFORMATION   = "aether.cis.semantic.embedding.deformation.detected"
    # Reasoning chain auditing
    CIS_REASONING_CHAIN_CREATED          = "aether.cis.reasoning.chain.created"
    CIS_REASONING_CONTRADICTION_DETECTED = "aether.cis.reasoning.contradiction.detected"
    CIS_REASONING_RECURSION_DETECTED     = "aether.cis.reasoning.recursion.detected"
    # Quarantine workflows
    CIS_QUARANTINE_INITIATED             = "aether.cis.quarantine.initiated"
    CIS_QUARANTINE_RELEASED              = "aether.cis.quarantine.released"
    CIS_QUARANTINE_ESCALATED             = "aether.cis.quarantine.escalated"

    # ── Notification Intelligence ────────────────────────────────────────────
    INTEL_NOTIFICATION_DETECTED    = "aether.notifications.intelligence.detected"
    INTEL_NOTIFICATION_VALIDATED   = "aether.notifications.intelligence.validated"
    INTEL_NOTIFICATION_QUEUED      = "aether.notifications.intelligence.queued"
    INTEL_NOTIFICATION_DELIVERED   = "aether.notifications.intelligence.delivered"
    INTEL_NOTIFICATION_FAILED      = "aether.notifications.intelligence.failed"
    OPERATOR_ACTION                = "aether.notifications.operator.action"
    INTEL_NOTIFICATION_PROPAGATED  = "aether.notifications.intelligence.propagated"
    INTEL_NOTIFICATION_EXPIRED     = "aether.notifications.intelligence.expired"
    NOTIFICATION_CHANNEL_CONNECTED    = "aether.notifications.channel.connected"
    NOTIFICATION_CHANNEL_DISCONNECTED = "aether.notifications.channel.disconnected"

    # SDK Observability
    SDK_HEALTH_HEARTBEAT     = "aether.sdk.health.heartbeat"
    SDK_HEALTH_STATE_CHANGED = "aether.sdk.health.state_changed"
    SDK_DRIFT_DETECTED       = "aether.sdk.drift.detected"
    SDK_CONFIG_UPDATED       = "aether.sdk.config.updated"

    # Decision & Outcome Intelligence (OODA loop)
    RECOMMENDATION_GENERATED = "aether.recommendation.generated"
    RECOMMENDATION_VIEWED = "aether.recommendation.viewed"
    DECISION_RECORDED = "aether.decision.recorded"
    ACTION_EXECUTED = "aether.action.executed"
    OUTCOME_OBSERVED = "aether.outcome.observed"
    RECOMMENDATION_CONFIDENCE_UPDATED = "aether.recommendation.confidence_updated"

    # Admin audit
    ADMIN_API_KEY_CREATED = "aether.admin.api_key.created"

    # Suggestion / OODA Intelligence
    SUGGESTION_DETECTED        = "aether.suggestions.detected"
    SUGGESTION_ORIENTED        = "aether.suggestions.oriented"
    SUGGESTION_CREATED         = "aether.suggestions.created"
    SUGGESTION_REVIEW_REQUIRED = "aether.suggestions.review_required"
    SUGGESTION_APPROVED        = "aether.suggestions.approved"
    SUGGESTION_REJECTED        = "aether.suggestions.rejected"
    SUGGESTION_SUPPRESSED      = "aether.suggestions.suppressed"
    SUGGESTION_EXECUTING       = "aether.suggestions.executing"
    SUGGESTION_EXECUTED        = "aether.suggestions.executed"
    SUGGESTION_DELIVERED       = "aether.suggestions.delivered"
    SUGGESTION_OUTCOME_RECORDED = "aether.suggestions.outcome_recorded"
    SUGGESTION_CLOSED          = "aether.suggestions.closed"
    SUGGESTION_FAILED          = "aether.suggestions.failed"
    SUGGESTION_EXPIRED         = "aether.suggestions.expired"

    # Fraud Network Intelligence
    FRAUD_NETWORK_CREATED    = "aether.fraud.network.created"
    FRAUD_NETWORK_UPDATED    = "aether.fraud.network.updated"
    FRAUD_NETWORK_REFRESHED  = "aether.fraud.network.refreshed"
    FRAUD_NETWORK_ESCALATED  = "aether.fraud.network.escalated"
    FRAUD_NETWORK_SUPPRESSED = "aether.fraud.network.suppressed"
    FLOW_TRACE_CREATED       = "aether.flow.trace.created"
    FLOW_TRACE_COMPLETED     = "aether.flow.trace.completed"
    RISK_OVERLAY_GENERATED   = "aether.risk.overlay.generated"

    # Fraud Decision Intelligence
    FRAUD_DECISION_CREATED    = "aether.fraud.decision.created"
    FRAUD_DECISION_SUPERSEDED = "aether.fraud.decision.superseded"
    FRAUD_DECISION_REVIEWED   = "aether.fraud.decision.reviewed"
    FRAUD_DECISION_SUPPRESSED = "aether.fraud.decision.suppressed"
    FRAUD_EVALUATION_TRIGGERED = "aether.fraud.evaluation.triggered"
    FRAUD_EVALUATION_COMPLETED = "aether.fraud.evaluation.completed"
    FRAUD_EVALUATION_FAILED    = "aether.fraud.evaluation.failed"
    RISK_ANNOTATION_UPDATED    = "aether.risk.annotation.updated"

    # Canonical Activity
    CANONICAL_ACTIVITY_INGESTED = "aether.canonical.activity.ingested"
    CANONICAL_ACTIVITY_RISK_UPDATED = "aether.canonical.activity.risk_updated"

    # Economic & Interoperability Intelligence (observation-only alerts)
    STABLECOIN_DEPEG_DETECTED         = "aether.stablecoin.depeg.detected"
    DERIVATIVES_VARIANCE_DETECTED     = "aether.derivatives.reconciliation.variance"
    DERIVATIVES_STREAM_GAP_STALLED    = "aether.derivatives.stream.gap.stalled"
    INTEROP_MESSAGE_STUCK             = "aether.interop.message.stuck"
    INTEROP_SECURITY_POLICY_CHANGED   = "aether.interop.security.policy.changed"

    # Dead letter
    DEAD_LETTER = "aether.dlq"

    # ── Platform Control Plane (jobs / exports / notifications / schedules /
    #    imports / reconciliation) — appended block, do not reorder above ────
    # Durable job lifecycle (services/jobs)
    JOB_ACCEPTED = "aether.job.accepted"
    JOB_QUEUED = "aether.job.queued"
    JOB_STARTED = "aether.job.started"
    JOB_RETRYING = "aether.job.retrying"
    JOB_SUCCEEDED = "aether.job.succeeded"
    JOB_PARTIALLY_SUCCEEDED = "aether.job.partially_succeeded"
    JOB_FAILED = "aether.job.failed"
    JOB_CANCELLED = "aether.job.cancelled"
    JOB_EXPIRED = "aether.job.expired"
    JOB_DEAD_LETTERED = "aether.job.dead_lettered"

    # Export artifacts lifecycle
    EXPORT_REQUESTED = "aether.export.requested"
    EXPORT_READY = "aether.export.ready"
    EXPORT_FAILED = "aether.export.failed"
    EXPORT_DOWNLOADED = "aether.export.downloaded"
    EXPORT_EXPIRED = "aether.export.expired"

    # Tenant notification inbox/outbox lifecycle
    NOTIFICATION_CREATED = "aether.notification.created"
    NOTIFICATION_READ = "aether.notification.read"
    NOTIFICATION_DELIVERY_QUEUED = "aether.notification.delivery_queued"
    NOTIFICATION_DELIVERED = "aether.notification.delivered"
    NOTIFICATION_DELIVERY_FAILED = "aether.notification.delivery_failed"
    NOTIFICATION_DEAD_LETTERED = "aether.notification.dead_lettered"

    # Job schedules (cron control plane)
    SCHEDULE_FIRED = "aether.schedule.fired"
    SCHEDULE_MISFIRED = "aether.schedule.misfired"
    SCHEDULE_SKIPPED = "aether.schedule.skipped"
    SCHEDULE_DISABLED = "aether.schedule.disabled"

    # Bulk import lifecycle
    IMPORT_CREATED = "aether.import.created"
    IMPORT_UPLOADED = "aether.import.uploaded"
    IMPORT_ANALYZED = "aether.import.analyzed"
    IMPORT_VALIDATED = "aether.import.validated"
    IMPORT_COMMITTED = "aether.import.committed"
    IMPORT_REPLAYED = "aether.import.replayed"
    IMPORT_ROLLED_BACK = "aether.import.rolled_back"
    IMPORT_FAILED = "aether.import.failed"

    # Measurement restatement (complements aether.measurement.* above)
    MEASUREMENT_RESTATED = "aether.measurement.restated"

    # Reconciliation runs
    RECONCILIATION_STARTED = "aether.reconciliation.started"
    RECONCILIATION_COMPLETED = "aether.reconciliation.completed"
    RECONCILIATION_DRIFT_DETECTED = "aether.reconciliation.drift_detected"

    # ── Graph plane — canonical mutation gateway (WP2.5) ────────────────────
    # Emitted once per NEW ledger row appended by the Graph Mutation Gateway
    # (shared/graph/mutation_gateway.py); deduplicated replays do not re-emit.
    GRAPH_MUTATED = "aether.graph.mutated"


# ═══════════════════════════════════════════════════════════════════════════
# EVENT SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────
# Schema v2 envelope blocks (additive, all optional)
#
# Every block is None-able. Old producers keep emitting events with
# version="1.0" and only `payload`; consumers continue to read the same
# fields. New producers may set version="2.0" and populate any subset of
# the v2 blocks below — they ride alongside the original payload.
#
# Consumers that don't know about v2 simply ignore the new top-level keys.
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class EventEnvelopeV2:
    """Profile 360 v2 envelope — every field optional, additive only."""
    actor: Optional[dict[str, Any]] = None              # {entity_id, entity_type}
    beneficiary: Optional[dict[str, Any]] = None        # {entity_id, entity_type}
    attribution: Optional[dict[str, Any]] = None        # {source, campaign, touch_model, exposure_aware}
    state_snapshot: Optional[dict[str, Any]] = None     # {user_state_hash, system_state_hash, snapshot_ref_s3}
    temporal_context: Optional[dict[str, Any]] = None   # {since_session_start_ms, since_last_event_ms, journey_chain_id}
    causality: Optional[dict[str, Any]] = None          # {triggered_by_event_id, dependency_event_ids[], causal_score}
    decision_context: Optional[dict[str, Any]] = None   # {options_shown[], chosen, ranking_model_version}
    exposure: Optional[dict[str, Any]] = None           # {impressions[], dwell_ms[], visible_pct[]}
    friction: Optional[dict[str, Any]] = None           # {errors[], retries, latency_ms}
    engagement: Optional[dict[str, Any]] = None         # {depth, scroll_pct, time_on_event_ms}
    intent: Optional[dict[str, Any]] = None             # {predicted_goal, model_version, confidence}
    environment: Optional[dict[str, Any]] = None        # {device, os, network, geo_region}
    identity_confidence: Optional[float] = None
    delegation: Optional[dict[str, Any]] = None         # {delegation_id, scope, granted_by_entity_id}
    agent_intelligence: Optional[dict[str, Any]] = None # {agent_id, reasoning, confidence, policy_log_ref}
    economic_context: Optional[dict[str, Any]] = None   # {price, currency, discounts[], total}
    system_actions: Optional[dict[str, Any]] = None     # {recommendations[], ranking[], chosen_index}
    consent: Optional[dict[str, Any]] = None            # {consent_id, purposes[], granted_at}
    data_quality: Optional[dict[str, Any]] = None       # {ingestion_lag_ms, source_reliability, schema_version}
    semantic_context: Optional[dict[str, Any]] = None   # SemanticContextEnvelope payload (additive)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for fname in self.__dataclass_fields__:
            value = getattr(self, fname)
            if value is not None:
                result[fname] = value
        return result


@dataclass
class Event:
    topic: Topic
    payload: dict[str, Any]
    tenant_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_service: str = ""
    correlation_id: str = ""
    version: str = "1.0"
    retry_count: int = 0
    envelope: Optional[EventEnvelopeV2] = None  # v2 enrichment (optional)

    def with_v2(self, envelope: EventEnvelopeV2) -> "Event":
        """Attach a v2 envelope and bump the schema version."""
        self.envelope = envelope
        self.version = "2.0"
        return self

    def serialize(self) -> str:
        out: dict[str, Any] = {
            "event_id": self.event_id,
            "topic": self.topic.value,
            "version": self.version,
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "source_service": self.source_service,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "retry_count": self.retry_count,
        }
        if self.envelope is not None:
            out["envelope"] = self.envelope.to_dict()
        return json.dumps(out)

    @classmethod
    def deserialize(cls, raw: str) -> Event:
        data = json.loads(raw)
        envelope_data = data.get("envelope")
        envelope = (
            EventEnvelopeV2(**{
                k: v for k, v in envelope_data.items()
                if k in EventEnvelopeV2.__dataclass_fields__
            })
            if envelope_data
            else None
        )
        return cls(
            event_id=data["event_id"],
            topic=Topic(data["topic"]),
            version=data.get("version", "1.0"),
            timestamp=data["timestamp"],
            tenant_id=data.get("tenant_id", ""),
            source_service=data.get("source_service", ""),
            correlation_id=data.get("correlation_id", ""),
            payload=data["payload"],
            retry_count=data.get("retry_count", 0),
            envelope=envelope,
        )


# ═══════════════════════════════════════════════════════════════════════════
# PRODUCER — auto-selects Kafka or in-memory
# ═══════════════════════════════════════════════════════════════════════════

class EventProducer:
    """
    Publishes events to the event bus with retry logic.

    Backend selection:
    - AETHER_ENV=local → in-memory list (for dev/testing)
    - AETHER_ENV=staging/production → Kafka via aiokafka
    """

    MAX_RETRIES = 3
    BASE_BACKOFF_S = 0.1

    def __init__(self) -> None:
        self._published: list[Event] = []
        self._connected = False
        self._kafka_producer: Optional[Any] = None
        self._sqs_client: Optional[Any] = None
        self._sqs_queue_url: str = ""
        self._sns_client: Optional[Any] = None
        self._sns_topic_arn: str = ""
        self._mode = "uninitialized"

    async def connect(self) -> None:
        bootstrap = _kafka_bootstrap()
        if _event_broker() == "sns_sqs" and BOTO3_EVENTS_AVAILABLE and _sqs_queue_url():
            loop = asyncio.get_event_loop()
            self._sqs_client = await loop.run_in_executor(
                None, lambda: _boto3_events.client("sqs")  # type: ignore[union-attr]
            )
            self._sqs_queue_url = _sqs_queue_url()
            if _sns_topic_arn():
                # Fanout: when SNS_TOPIC_ARN is set, publish through the SNS
                # topic so every per-role consumer queue (subscribed in
                # Terraform modules/sqs) receives the event. A direct SQS send
                # would land in this process's own queue only and starve every
                # other consumer role.
                self._sns_client = await loop.run_in_executor(
                    None, lambda: _boto3_events.client("sns")  # type: ignore[union-attr]
                )
                self._sns_topic_arn = _sns_topic_arn()
            self._mode = "sqs"
            logger.info(
                "EventProducer connected (SQS: %s%s)",
                self._sqs_queue_url,
                f", SNS fanout: {self._sns_topic_arn}" if self._sns_topic_arn else "",
            )
        elif bootstrap and KAFKA_AVAILABLE:
            try:
                self._kafka_producer = AIOKafkaProducer(
                    bootstrap_servers=bootstrap,
                    value_serializer=lambda v: v.encode("utf-8"),
                    acks="all",
                    retries=3,
                    request_timeout_ms=30000,
                )
                await self._kafka_producer.start()
                self._mode = "kafka"
                logger.info(f"EventProducer connected (Kafka: {bootstrap})")
            except Exception as e:
                if _is_local_env():
                    logger.warning(f"Kafka not reachable ({e}) — falling back to in-memory")
                    self._kafka_producer = None
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(
                        f"Kafka not reachable at {bootstrap}: {e}. "
                        "Set AETHER_ENV=local for in-memory fallback."
                    )
        elif _is_local_env():
            self._mode = "in-memory"
            logger.info("EventProducer connected (in-memory, local mode)")
        else:
            if not KAFKA_AVAILABLE:
                raise RuntimeError(
                    "aiokafka required for production: pip install aiokafka>=0.10"
                )
            raise RuntimeError(
                "KAFKA_BOOTSTRAP_SERVERS not set. Required in non-local environments."
            )
        self._connected = True

    async def close(self) -> None:
        if self._kafka_producer:
            await self._kafka_producer.stop()
            self._kafka_producer = None
        self._sqs_client = None
        self._sns_client = None
        self._connected = False
        logger.info("EventProducer closed")

    async def publish(self, event: Event) -> None:
        """Publish a single event with retry."""
        if not self._connected:
            await self.connect()

        for attempt in range(self.MAX_RETRIES):
            try:
                if self._sns_client:
                    # SNS fanout: one publish reaches every subscribed
                    # per-role consumer queue (raw message delivery keeps the
                    # body identical to a direct SQS send).
                    body = event.serialize()
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: self._sns_client.publish(  # type: ignore[union-attr]
                            TopicArn=self._sns_topic_arn,
                            Message=body,
                        ),
                    )
                elif self._sqs_client:
                    body = event.serialize()
                    loop = asyncio.get_event_loop()
                    is_fifo = self._sqs_queue_url.endswith(".fifo")
                    if is_fifo:
                        await loop.run_in_executor(
                            None,
                            lambda: self._sqs_client.send_message(  # type: ignore[union-attr]
                                QueueUrl=self._sqs_queue_url,
                                MessageBody=body,
                                MessageGroupId=event.tenant_id or "default",
                                MessageDeduplicationId=event.event_id,
                            ),
                        )
                    else:
                        await loop.run_in_executor(
                            None,
                            lambda: self._sqs_client.send_message(  # type: ignore[union-attr]
                                QueueUrl=self._sqs_queue_url,
                                MessageBody=body,
                            ),
                        )
                elif self._kafka_producer:
                    await self._kafka_producer.send_and_wait(
                        event.topic.value, event.serialize()
                    )
                else:
                    self._published.append(event)

                metrics.increment("events_published", labels={"topic": event.topic.value})
                logger.info(f"Published event {event.event_id} to {event.topic.value}")
                return
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.error(f"Failed to publish event {event.event_id} after {self.MAX_RETRIES} attempts: {e}")
                    metrics.increment("events_publish_failed", labels={"topic": event.topic.value})
                    raise
                backoff = self.BASE_BACKOFF_S * (2 ** attempt)
                logger.warning(f"Publish retry {attempt + 1} for {event.event_id}, backoff {backoff}s")
                await asyncio.sleep(backoff)

    async def publish_batch(self, events: list[Event]) -> None:
        """Publish a batch of events using Kafka batch send or individual publish."""
        if not events:
            return
        if self._kafka_producer:
            # Use Kafka's native batch API for a single round-trip.
            # Group events by topic so each topic gets one batch send.
            from collections import defaultdict
            by_topic: dict[str, list[Event]] = defaultdict(list)
            for event in events:
                by_topic[event.topic.value].append(event)

            for topic_value, topic_events in by_topic.items():
                try:
                    batch = self._kafka_producer.create_batch()
                    overflow_events: list[Event] = []
                    for event in topic_events:
                        appended = batch.append(
                            value=event.serialize().encode("utf-8"),
                            key=event.tenant_id.encode() if event.tenant_id else None,
                            timestamp=None,
                        )
                        if appended is None:
                            # Batch is full — fall back to individual publish for this event
                            overflow_events.append(event)
                    partitions = await self._kafka_producer.partitions_for(topic_value)
                    partition = next(iter(partitions))
                    await self._kafka_producer.send_batch(batch, topic_value, partition=partition)
                    batched_count = len(topic_events) - len(overflow_events)
                    metrics.increment(
                        "events_published",
                        value=batched_count,
                        labels={"topic": topic_value},
                    )
                    # Publish overflow events individually
                    for event in overflow_events:
                        await self.publish(event)
                except Exception as exc:
                    logger.error("Batch publish failed for topic %s: %s", topic_value, exc)
                    metrics.increment(
                        "events_publish_failed",
                        value=len(topic_events),
                        labels={"topic": topic_value},
                    )
                    raise
        else:
            for event in events:
                await self.publish(event)

    @property
    def published_count(self) -> int:
        return len(self._published)

    async def health_check(self) -> bool:
        if not self._connected:
            return False
        if self._kafka_producer:
            try:
                await self._kafka_producer.partitions_for("__health")
                return True
            except Exception:
                return False
        return True  # In-memory mode is always healthy

    @property
    def mode(self) -> str:
        return self._mode


# ═══════════════════════════════════════════════════════════════════════════
# CONSUMER — auto-selects Kafka or in-memory
# ═══════════════════════════════════════════════════════════════════════════

class EventConsumer:
    """
    Subscribes to topics and processes events with backpressure.

    Backend:
    - AETHER_ENV=local → processes events in-memory via process()
    - AETHER_ENV=staging/production → Kafka consumer group via aiokafka
    """

    MAX_CONCURRENT = 10
    MAX_HANDLER_RETRIES = 2

    def __init__(self, group_id: str = "", queue_url: str = "") -> None:
        # Include AETHER_ENV in the group_id so staging/production consumer groups
        # never interfere with each other.
        _env = os.getenv("AETHER_ENV", "local")
        group_id = group_id or f"aether-backend-{_env}"
        self._handlers: dict[Topic, list[EventHandler]] = {}
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._dlq: list[Event] = []
        self._kafka_consumer: Optional[Any] = None
        # Durable-DLQ producer, created lazily on the first dead-letter in Kafka
        # mode. Declared here because _send_to_dlq reads it: when the attribute
        # did not exist the read raised AttributeError inside the DLQ try block
        # and the event silently degraded to the in-memory list.
        self._kafka_producer: Optional[Any] = None
        self._sqs_client: Optional[Any] = None
        self._sqs_queue_url: str = ""
        # Explicit queue binding. A process hosting several logical roles needs
        # one consumer per role queue, which the single SQS_QUEUE_URL env var
        # cannot express; when set, this wins over the environment.
        self._explicit_queue_url: str = queue_url
        self._group_id = group_id
        self._running = False
        self._mode = "uninitialized"
        # Handlers currently executing. Drives bounded drain on shutdown: a
        # consumer that has stopped acquiring is not yet quiesced.
        self._in_flight = 0

    def subscribe(self, topic: Topic, handler: EventHandler) -> None:
        self._handlers.setdefault(topic, []).append(handler)
        logger.info(f"Subscribed handler to {topic.value}")

    def resize_concurrency(self, max_concurrent: int) -> None:
        """Resize the backpressure semaphore to ``max_concurrent``.

        ``MAX_CONCURRENT`` is read once in ``__init__`` to size the semaphore,
        so callers that tune it afterwards (per-group backpressure) must resize
        the semaphore too or the enforced limit silently stays at the class
        default. Refuses to resize once events are in flight, where swapping the
        semaphore would lose the outstanding permits.
        """
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        if self._in_flight:
            raise RuntimeError(
                f"cannot resize concurrency with {self._in_flight} event(s) in flight"
            )
        self.MAX_CONCURRENT = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def start(self) -> None:
        """Start consuming from Kafka, SQS, or stay in in-memory mode."""
        bootstrap = _kafka_bootstrap()
        topics = [t.value for t in self._handlers.keys()]
        if not topics:
            self._mode = "in-memory"
            logger.info("EventConsumer: no subscriptions, in-memory mode")
            return

        # An explicit binding always wins over the process-wide env var: it is
        # how a consolidated process gives each logical role its own queue.
        queue_url = self._explicit_queue_url or _sqs_queue_url()
        broker = _event_broker()

        if broker == "sns_sqs" and not _is_local_env() and not (
            BOTO3_EVENTS_AVAILABLE and queue_url
        ):
            # EVENT_BROKER was explicitly set to sns_sqs but the endpoint or the
            # client library is missing. Falling through to the Kafka branch
            # here would silently switch backends: the process would come up
            # "healthy" against a different bus (or in-memory) while every
            # event routed to the SQS queue went unconsumed. Fail closed and
            # say which half is missing. Local/dev keeps the permissive path.
            missing = "boto3" if not BOTO3_EVENTS_AVAILABLE else "SQS queue URL"
            raise RuntimeError(
                f"EVENT_BROKER=sns_sqs but {missing} is unavailable "
                f"(group_id={self._group_id}). Refusing to fall back to another "
                "broker in a non-local environment; set SQS_QUEUE_URL / "
                "SQS_ROLE_QUEUE_URLS or install boto3."
            )

        if broker == "sns_sqs" and BOTO3_EVENTS_AVAILABLE and queue_url:
            loop = asyncio.get_event_loop()
            self._sqs_client = await loop.run_in_executor(
                None, lambda: _boto3_events.client("sqs")  # type: ignore[union-attr]
            )
            self._sqs_queue_url = queue_url
            self._mode = "sqs"
            self._running = True
            logger.info(f"EventConsumer started (SQS: {self._sqs_queue_url})")
        elif bootstrap and KAFKA_AVAILABLE:
            try:
                self._kafka_consumer = AIOKafkaConsumer(
                    *topics,
                    bootstrap_servers=bootstrap,
                    group_id=self._group_id,
                    auto_offset_reset="earliest",
                    # Commit only after all handlers (or the durable DLQ path)
                    # complete. A crash before that point deliberately causes
                    # redelivery rather than silent loss.
                    enable_auto_commit=False,
                    value_deserializer=lambda m: m.decode("utf-8"),
                )
                await self._kafka_consumer.start()
                self._mode = "kafka"
                self._running = True
                logger.info(f"EventConsumer started (Kafka: {bootstrap}, topics: {topics})")
            except Exception as e:
                if _is_local_env():
                    logger.warning(f"Kafka consumer start failed ({e}) — in-memory mode")
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(f"Kafka consumer start failed: {e}")
        else:
            self._mode = "in-memory"
            logger.info("EventConsumer started (in-memory mode)")

    async def receive_loop(self) -> None:
        """Run the receive loop matching the mode chosen by :meth:`start`.

        Returns immediately in in-memory mode, where events arrive through
        direct :meth:`process` calls rather than a broker poll. Callers that
        supervise this coroutine should treat an early return in a broker mode
        as an abnormal exit, not as completion.
        """
        if self._mode == "kafka":
            await self.consume_loop()
        elif self._mode == "sqs":
            await self._sqs_receive_loop()

    async def consume_loop(self) -> None:
        """Main consume loop for Kafka mode. Run as asyncio task."""
        if not self._kafka_consumer:
            return
        try:
            async for msg in self._kafka_consumer:
                try:
                    event = Event.deserialize(msg.value)
                    await self.process(event)
                    await self._kafka_consumer.commit()
                except Exception as e:
                    logger.error(f"Error processing Kafka message: {e}")
        except Exception as e:
            logger.error(f"Kafka consume loop error: {e}")
        finally:
            self._running = False

    async def _sqs_receive_loop(self) -> None:
        """Long-poll SQS receive loop. Run as asyncio task."""
        if not self._sqs_client:
            return
        loop = asyncio.get_event_loop()
        try:
            while self._running:
                try:
                    response = await loop.run_in_executor(
                        None,
                        lambda: self._sqs_client.receive_message(  # type: ignore[union-attr]
                            QueueUrl=self._sqs_queue_url,
                            MaxNumberOfMessages=10,
                            WaitTimeSeconds=20,
                        ),
                    )
                    messages = response.get("Messages", [])
                    for msg in messages:
                        receipt_handle = msg["ReceiptHandle"]
                        try:
                            event = Event.deserialize(msg["Body"])
                            await self.process(event)
                            await loop.run_in_executor(
                                None,
                                lambda rh=receipt_handle: self._sqs_client.delete_message(  # type: ignore[union-attr]
                                    QueueUrl=self._sqs_queue_url,
                                    ReceiptHandle=rh,
                                ),
                            )
                        except Exception as e:
                            logger.error(f"Error processing SQS message: {e}")
                except Exception as e:
                    logger.error(f"SQS receive loop error: {e}")
        finally:
            self._running = False

    async def process(self, event: Event) -> None:
        """Process an event with concurrency limiting and retry."""
        async with self._semaphore:
            # Counted inside the semaphore so ``in_flight`` reflects handlers
            # actually executing, which is what a bounded drain must wait on.
            self._in_flight += 1
            try:
                await self._dispatch(event)
            finally:
                self._in_flight -= 1

    async def _dispatch(self, event: Event) -> None:
        """Run every subscribed handler for ``event`` with bounded retry."""
        handlers = self._handlers.get(event.topic, [])
        for handler in handlers:
            success = False
            while not success:
                try:
                    await handler(event)
                    metrics.increment("events_processed", labels={"topic": event.topic.value})
                    success = True
                except Exception as e:
                    logger.error(f"Handler failed for event {event.event_id}: {e}")
                    metrics.increment("events_handler_failed", labels={"topic": event.topic.value})
                    if event.retry_count < self.MAX_HANDLER_RETRIES:
                        event.retry_count += 1
                        logger.info(f"Retrying event {event.event_id} (attempt {event.retry_count})")
                    else:
                        await self._send_to_dlq(event, str(e))
                        break

    async def _send_to_dlq(self, event: Event, error: str) -> None:
        """Send failed events to dead-letter queue.

        In non-local environments the DLQ event is published to the durable
        DEAD_LETTER Kafka topic so it survives process restarts.  In local/dev
        mode the event is appended to the in-memory list for test introspection.
        """
        dlq_event = Event(
            topic=Topic.DEAD_LETTER,
            tenant_id=event.tenant_id,
            source_service=event.source_service,
            correlation_id=event.correlation_id,
            payload={
                "original_topic": event.topic.value,
                "original_event_id": event.event_id,
                "original_payload": event.payload,
                "error": error,
                "retry_count": event.retry_count,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        metrics.increment("events_dead_lettered", labels={"topic": event.topic.value})
        logger.warning(
            "Event %s dead-lettered (topic=%s error=%s)",
            event.event_id, event.topic.value, error,
        )

        if _is_local_env():
            # Local dev: keep in-memory for test assertions
            self._dlq.append(dlq_event)
            return

        # Production/staging: publish to the durable DLQ topic on Kafka/SQS.
        #
        # This publish either succeeds or raises. It must never degrade to the
        # in-memory list: that list dies with the process, so a "handled" DLQ
        # event would be indistinguishable from a lost one. Raising propagates
        # out of process() into the receive loop, which then does NOT commit the
        # Kafka offset / delete the SQS receipt — the event is redelivered
        # instead of being acknowledged as safely dead-lettered.
        try:
            await self._publish_dlq_event(dlq_event)
        except Exception as exc:
            metrics.increment(
                "events_dlq_publish_failed", labels={"topic": event.topic.value},
            )
            # Full payload in the log is the last-resort recovery channel; it is
            # in addition to the raise below, never instead of it.
            logger.error(
                "Durable DLQ publish FAILED for event %s (%s: %s) — "
                "event will be redelivered, not acknowledged. Payload: %s",
                event.event_id, type(exc).__name__, exc, dlq_event.serialize(),
            )
            self._dlq.append(dlq_event)
            raise DLQPublishError(
                f"durable DLQ publish failed for event {event.event_id}: {exc}"
            ) from exc

    async def _publish_dlq_event(self, dlq_event: Event) -> None:
        """Publish ``dlq_event`` to the durable dead-letter destination.

        Raises on any failure — see :meth:`_send_to_dlq` for why degrading is
        not an option here.
        """
        if self._mode == "kafka":
            producer = await self._ensure_dlq_producer()
            await producer.send_and_wait(Topic.DEAD_LETTER.value, dlq_event.serialize())
            return
        if self._mode == "sqs" and self._sqs_client:
            # NOTE: with no dedicated DLQ queue configured this re-enqueues onto
            # the source queue, which re-poisons this consumer. SQS_DLQ_QUEUE_URL
            # is the escape hatch; the redrive policy on the queue itself is the
            # intended long-term owner of this path.
            target = _sqs_dlq_queue_url() or self._sqs_queue_url
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._sqs_client.send_message(  # type: ignore[union-attr]
                    QueueUrl=target,
                    MessageBody=dlq_event.serialize(),
                ),
            )
            return
        raise RuntimeError(
            f"no durable DLQ transport available (mode={self._mode})"
        )

    async def _ensure_dlq_producer(self) -> Any:
        """Lazily create the Kafka producer used for durable dead-lettering.

        ``EventConsumer`` has no producer of its own — the original code read a
        ``self._kafka_producer`` that ``__init__`` never assigned, so in Kafka
        mode every durable DLQ publish raised AttributeError, got swallowed by
        the enclosing except, and quietly fell back to the in-memory list. The
        consumer now owns a real producer bound to the same bootstrap servers.
        """
        if self._kafka_producer is not None:
            return self._kafka_producer
        if not KAFKA_AVAILABLE:
            raise RuntimeError("aiokafka unavailable — cannot publish durable DLQ events")
        bootstrap = _kafka_bootstrap()
        if not bootstrap:
            raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS unset — cannot publish durable DLQ events")
        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap,
            value_serializer=lambda v: v.encode("utf-8"),
            # acks=all: a dead-letter that is not durably replicated is worse
            # than useless, because it reads as successfully quarantined.
            acks="all",
            retries=3,
            request_timeout_ms=30000,
        )
        await producer.start()
        self._kafka_producer = producer
        logger.info("EventConsumer DLQ producer started (Kafka: %s)", bootstrap)
        return producer

    async def stop(self) -> None:
        self._running = False
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
            self._kafka_consumer = None
        if self._kafka_producer:
            # Flushes buffered dead-letters before the process exits.
            await self._kafka_producer.stop()
            self._kafka_producer = None
        self._sqs_client = None
        logger.info("EventConsumer stopped")

    @property
    def dlq_depth(self) -> int:
        return len(self._dlq)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_running(self) -> bool:
        """True while a broker receive loop is expected to be pulling."""
        return self._running

    @property
    def in_flight(self) -> int:
        """Handlers currently executing; 0 means fully quiesced."""
        return self._in_flight

    @property
    def group_id(self) -> str:
        """The consumer group this instance is bound to."""
        return self._group_id

    @property
    def queue_url(self) -> str:
        """The bound SQS queue URL ('' outside SQS mode)."""
        return self._sqs_queue_url
