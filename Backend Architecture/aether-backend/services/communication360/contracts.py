"""Canonical Communication360 contract surface (Phase 3, ratified Phase 2).

These are the genuinely-new canonical communication objects the read-only
``communication360`` projection consumes (registry row ``communication360``,
``ownsCanonicalTruth: false``, ``graphMutationPolicy: read_only``). The program's
central modeling obligations (ratified in Phase 2, R1–R5, recorded in
``docs/blueprints/communication360.md``):

- **R2 — message is not information.** A delivered message is never collapsed
  into "the content was known". The information layer (:class:`Information`,
  :class:`MessageClaimBinding`, :class:`InformationTransformation`) is separate
  canonical objects, never fields bolted onto ``silver_comms_facts``.
- **R3 — sender is not author/principal.** Roles render through
  :class:`ParticipantBinding` with temporal validity
  (``valid_from``/``valid_to``) over the :class:`CommunicationParticipantRole`
  vocabulary, referencing ``services/identity`` ``EntityType`` and
  ``services/delegation`` grants — never a single ``from`` attribute.
- **R4 — delivery is not knowledge.** Message lifecycle/delivery state
  (``services.comms`` :class:`CommunicationState`) and agent-side
  knowledge/interpretation/context state (:class:`AgentConsumptionState`,
  :class:`KnowledgeStateRecord`, :class:`InterpretationRecord`,
  :class:`ContextInclusionRecord`) are two typed state families with no
  cross-ladder inference. A recipient-knowledge or author-intent fact is a
  structurally different object backed by its own observation — never granted
  by a delivery/action state.

Epistemic discipline (R1): every fact carries ``claim_state`` from the
consolidated :class:`EpistemicStatus` and is capped at ``observed`` unless a
stronger observation supports it; ``claim_state``/``confidence`` default to
"unclassified / absent" rather than asserting truth. Honest-absence invariant:
a missing value is typed missing/unavailable, never a fabricated zero.

Convention: snake_case fields, matching the canonical service peers
(``services/comms`` ``CommunicationEventPayload``, ``services/agentic_observability``
``AgenticObservationRecord``). Contracts fail closed (``extra="forbid"``) so a
misspelled field raises instead of silently drifting. These contracts import
canonical primitives (``EntityRef``/``EvidenceRef``/``ContractModel``,
``EntityType``, ``CommunicationState``, ``EpistemicStatus``); they never
re-declare them. Phase-3 parity/alignment tests enforce the no-redefinition rule.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import ConfigDict, Field

from shared.contracts_models.epistemic import EpistemicStatus
from services.comms.contracts import CommunicationState
from services.identity.models import EntityType
from services.operational_intelligence.models import (
    ContractModel,
    EntityRef,
    EvidenceRef,
)

# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────


class CommunicationContract(ContractModel):
    """Canonical Communication360 fact — fails closed on unknown fields.

    ``ContractModel`` stays tolerant for legacy API surfaces; the new canonical
    communication objects fail closed so schema drift is loud, mirroring the
    projection-plane discipline (``ProjectionContract``).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ─────────────────────────────────────────────────────────────────────────────
# Phase-2 ratified vocabularies (dimension seeds — registry alignment tests in
# Phase 3; do not re-declare EpistemicStatus / CommunicationState / EntityType)
# ─────────────────────────────────────────────────────────────────────────────


class CommunicationParticipantRole(str, Enum):
    """Temporally-valid roles a participant may hold over one communication (R3)."""

    ACTOR = "actor"
    AUTHOR = "author"
    GENERATOR = "generator"
    EDITOR = "editor"
    APPROVER = "approver"
    SENDER = "sender"
    PRESENTED_SENDER = "presented_sender"
    PRINCIPAL = "principal"
    DELEGATOR = "delegator"
    BENEFICIARY = "beneficiary"
    ACCOUNTABLE_PARTY = "accountable_party"


class CommunicationActType(str, Enum):
    """Declared semantic communication acts (extraction target — Phase 5)."""

    INFORM = "inform"
    REQUEST = "request"
    COMMIT = "commit"
    OFFER = "offer"
    DECIDE = "decide"
    APPROVE = "approve"
    REJECT = "reject"
    DELEGATE = "delegate"
    ACKNOWLEDGE = "acknowledge"
    ESCALATE = "escalate"


class ConversationState(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    PAUSED = "paused"
    ARCHIVED = "archived"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class AgentConsumptionState(str, Enum):
    """Agent-side knowledge/interpretation ladder (R4) — observed facts only.

    ``included_in_context`` / ``used`` are observations about an agent runtime
    (context was actually present), never inferences from message delivery.
    """

    UNOBSERVED = "unobserved"
    INGESTED = "ingested"
    PARSED = "parsed"
    INCLUDED_IN_CONTEXT = "included_in_context"
    USED = "used"
    UNKNOWN = "unknown"


class AuthorityState(str, Enum):
    """Delegation-authority outcome for an agent-mediated communication (Phase 5)."""

    GRANTED = "granted"
    DENIED = "denied"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class CapabilityState(str, Enum):
    """Per-communication provider capability truth-telling (§33).

    "unavailable"/limitation is never rendered as a fabricated zero.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PARTIAL = "partial"
    PERMISSION_DEPENDENT = "permission_dependent"
    PROVIDER_DEPENDENT = "provider_dependent"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Information layer (R2) — message is not information
# ─────────────────────────────────────────────────────────────────────────────


class InformationRef(CommunicationContract):
    """An addressable unit of semantic content (R2)."""

    information_id: str
    kind: str  # e.g. "message_content", "summary", "constraint", "decision"
    tenant_id: str


class Information(CommunicationContract):
    """Canonical information object — independently addressable content (R2)."""

    information_id: str
    tenant_id: str
    kind: str
    content_ref: Optional[str] = None  # address of the raw content (content-addressed)
    content_hash: Optional[str] = None
    source_refs: list[EvidenceRef] = Field(default_factory=list)
    topic_refs: list[str] = Field(default_factory=list)
    observed_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None  # at most observed for extracted content
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    schema_version: int = 1


class MessageClaimBinding(CommunicationContract):
    """A claim carried by a specific message, bound to information (R2)."""

    binding_id: str
    tenant_id: str
    message_id: str  # canonical comms message id (typed CommunicationMessage)
    information_ref: InformationRef
    claim_text: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None  # never granted by delivery
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class InformationTransformation(CommunicationContract):
    """Declared lineage from one information object to another (R2).

    Retention / semantic-drift / omission measurements (Phase 5) run over these.
    """

    transformation_id: str
    tenant_id: str
    source_information_ref: InformationRef
    derived_information_ref: InformationRef
    kind: str  # summarization | paraphrase | extraction | reformat | translation
    agent_entity_id: Optional[str] = None
    occurred_at: str
    claim_state: Optional[EpistemicStatus] = None  # observed-capped
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    drift_notes: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Communication message spine — typed read-over the shipped silver path
# ─────────────────────────────────────────────────────────────────────────────

# The canonical silver path is silver_comms_facts (CommsFactsRepository). These
# are typed VIEW contracts over that path — no duplicate storage. Message
# lifecycle state is CommunicationState (delivery ladder, NOT knowledge).


class CommunicationMessage(CommunicationContract):
    """Typed canonical view of one silver_comms_fact (read-over, no re-declaration)."""

    message_id: str  # canonical Aether message id
    tenant_id: str
    fact_id: Optional[str] = None  # silver_comms_facts row id
    provider: Optional[str] = None
    provider_event_id: Optional[str] = None
    external_message_id: Optional[str] = None
    external_thread_id: Optional[str] = None
    channel: Optional[str] = "email"
    direction: Optional[str] = None  # inbound | outbound
    communication_state: Optional[CommunicationState] = None  # delivery ladder, NOT knowledge
    sender_entity_id: Optional[str] = None
    recipient_entity_id: Optional[str] = None
    recipient_alias_id: Optional[str] = None
    subject: Optional[str] = None
    content_ref: Optional[str] = None
    campaign_id: Optional[str] = None
    occurred_at: str
    received_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Conversation / ProviderThread / Matter (resolution targets — Phase 6 logic)
# ─────────────────────────────────────────────────────────────────────────────


class ResolutionRecord(CommunicationContract):
    """How a conversation/matter resolved to its subject continuity (Phase 6)."""

    method: str  # e.g. participants+topics | reply_lineage | shared_matter | session_id
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


class ProviderThread(CommunicationContract):
    """A provider's own thread container — must NOT auto-equal a Conversation."""

    thread_id: str
    tenant_id: str
    provider: str
    external_thread_id: str
    provider_account_id: Optional[str] = None
    subject: Optional[str] = None
    message_ids: list[str] = Field(default_factory=list)
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None


class Conversation(CommunicationContract):
    """Canonical conversation — the resolution of provider threads + continuity."""

    conversation_id: str
    tenant_id: str
    kind: str = "conversation"  # conversation | request_thread | incident | ...
    topic: Optional[str] = None
    provider_thread_ids: list[str] = Field(default_factory=list)
    message_ids: list[str] = Field(default_factory=list)
    participant_bindings: list["ParticipantBinding"] = Field(default_factory=list)
    matter_id: Optional[str] = None
    state: ConversationState = ConversationState.UNKNOWN
    resolution: Optional[ResolutionRecord] = None
    opened_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None


class Matter(CommunicationContract):
    """Longer-lived subject continuity binding multiple channels/agents (§59)."""

    matter_id: str
    tenant_id: str
    subject: str
    kind: str = "matter"
    conversation_ids: list[str] = Field(default_factory=list)
    campaign_ids: list[str] = Field(default_factory=list)
    episode_ids: list[str] = Field(default_factory=list)
    external_refs: dict[str, str] = Field(default_factory=dict)
    resolution: Optional[ResolutionRecord] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None


# ─────────────────────────────────────────────────────────────────────────────
# Acts / Request / Commitment / ResponseExpectation
# ─────────────────────────────────────────────────────────────────────────────


class CommunicationAct(CommunicationContract):
    """A declared semantic act in a communication (extraction target — Phase 5)."""

    act_id: str
    tenant_id: str
    act_type: CommunicationActType
    message_id: Optional[str] = None
    conversation_id: Optional[str] = None
    actor_entity_id: str
    target_entity_id: Optional[str] = None
    object_ref: Optional[str] = None  # e.g. information_ref, resource id
    occurred_at: str
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class Request(CommunicationContract):
    request_id: str
    tenant_id: str
    act_id: Optional[str] = None
    requester_entity_id: str
    assignee_entity_id: Optional[str] = None
    description: Optional[str] = None
    state: str = "open"  # open | resolved | cancelled | expired
    deadline: Optional[str] = None
    occurred_at: str
    resolved_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class Commitment(CommunicationContract):
    commitment_id: str
    tenant_id: str
    act_id: Optional[str] = None
    committer_entity_id: str
    beneficiary_entity_id: Optional[str] = None
    description: Optional[str] = None
    state: str = "open"  # open | fulfilled | broken | cancelled
    due_at: Optional[str] = None
    occurred_at: str
    claim_state: Optional[EpistemicStatus] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ResponseExpectation(CommunicationContract):
    """An expected response attached to a communication (§22)."""

    expectation_id: str
    tenant_id: str
    expectation_type: str = "reply_by"  # reply_by | ack | deadline | action
    communication_ref: Optional[str] = None
    due_at: Optional[str] = None
    state: str = "open"  # open | met | violated | cancelled
    occurred_at: str
    claim_state: Optional[EpistemicStatus] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Participant / principal role matrix (R3)
# ─────────────────────────────────────────────────────────────────────────────


class ParticipantBinding(CommunicationContract):
    """One participant holding one role over a communication scope, temporally.

    Reuses identity ``EntityType`` and ``services/delegation`` grant ids; never a
    second role enum grafted onto ``EntityType``. ``valid_from``/``valid_to`` give
    temporal validity (Phase 2 R3) so a presenter, principal and author render
    distinctly and historically.
    """

    binding_id: str
    tenant_id: str
    communication_scope: str  # message_id | conversation_id | matter_id | episode_id
    communication_scope_kind: str  # message | conversation | matter | episode
    entity_id: str
    entity_type: Optional[EntityType] = None
    role: CommunicationParticipantRole
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    delegation_grant_id: Optional[str] = None  # services/delegation grant, if delegated
    principal_entity_id: Optional[str] = None  # who the actor acted for (if any)
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge / interpretation / context (R4) — delivery is not knowledge
# ─────────────────────────────────────────────────────────────────────────────

# These are observed agent-side facts, ingested from agentic observability
# (Phase 5). They never grant recipient knowledge from a delivery state.


class ContextInclusionRecord(CommunicationContract):
    """Was content actually present in an agent's context — an observed fact."""

    record_id: str
    tenant_id: str
    agent_entity_id: str
    context_ref: Optional[str] = None  # session / run / message scope
    included: bool = False
    included_at: Optional[str] = None
    source_observation_id: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class InterpretationRecord(CommunicationContract):
    """An agent's recorded interpretation — never silently promoted to fact."""

    record_id: str
    tenant_id: str
    agent_entity_id: str
    information_ref: Optional[InformationRef] = None
    text: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None  # inferred at strongest, never verified
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class KnowledgeStateRecord(CommunicationContract):
    """The strongest OBSERVED knowledge/consumption state for a subject+information."""

    record_id: str
    tenant_id: str
    subject_entity_id: str
    information_ref: Optional[InformationRef] = None
    state: AgentConsumptionState = AgentConsumptionState.UNOBSERVED
    known_since: Optional[str] = None
    observed_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Authority evaluation (Phase 5) — reuses services/delegation
# ─────────────────────────────────────────────────────────────────────────────


class AuthorityEvaluation(CommunicationContract):
    """Delegation-authority outcome for an agent-mediated communication.

    Computed (Phase 5) by consuming ``services/delegation``
    ``DelegationEngine.evaluate()`` over the participant role bindings; the
    ``decision`` mirrors the engine's allowed/denied outcome mapped onto
    :class:`AuthorityState`. Never a re-declaration of the delegation engine.
    """

    evaluation_id: str
    tenant_id: str
    agent_entity_id: str
    communication_scope: str  # message_id | conversation_id
    communication_scope_kind: str  # message | conversation
    delegation_grant_id: Optional[str] = None
    decision: AuthorityState = AuthorityState.UNKNOWN
    reason: Optional[str] = None
    evaluated_at: Optional[str] = None
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Capability + Quality (provider truth-telling — Phase 3/4)
# ─────────────────────────────────────────────────────────────────────────────


class ProviderCapability(CommunicationContract):
    """Per-provider(/account) capability truth-telling (§33).

    A capability key (content, subject, sender, recipient, thread, attachments,
    links, delivery, open, click, reply, edit_history, deletion, campaign_context,
    agent_*, authority_context, ...) maps to a :class:`CapabilityState`. The object
    rides each observation downstream; a limitation is never rendered as zero.
    """

    capability_id: str
    tenant_id: str
    provider: str
    provider_account_id: Optional[str] = None
    observed_at: Optional[str] = None
    capabilities: dict[str, CapabilityState] = Field(default_factory=dict)
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class CommunicationQuality(CommunicationContract):
    """Typed quality/degradation envelope for a communication (§124–125)."""

    quality_id: str
    tenant_id: str
    communication_ref: str  # message_id | conversation_id
    communication_scope_kind: str = "message"
    completeness: Optional[str] = None  # complete | partial | missing | unavailable
    degraded_reasons: list[str] = Field(default_factory=list)
    state: Optional[str] = None  # available | degraded | missing | unknown
    claim_state: Optional[EpistemicStatus] = None  # capped observed (R1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


__all__ = [
    # base
    "CommunicationContract",
    # vocab (Phase-2 ratified + dimension seeds)
    "CommunicationParticipantRole",
    "CommunicationActType",
    "ConversationState",
    "AgentConsumptionState",
    "AuthorityState",
    "CapabilityState",
    # information layer (R2)
    "InformationRef",
    "Information",
    "MessageClaimBinding",
    "InformationTransformation",
    # message spine
    "CommunicationMessage",
    # threads
    "ResolutionRecord",
    "ProviderThread",
    "Conversation",
    "Matter",
    # acts
    "CommunicationAct",
    "Request",
    "Commitment",
    "ResponseExpectation",
    # participants (R3)
    "ParticipantBinding",
    # knowledge (R4)
    "ContextInclusionRecord",
    "InterpretationRecord",
    "KnowledgeStateRecord",
    # authority
    "AuthorityEvaluation",
    # capability/quality
    "ProviderCapability",
    "CommunicationQuality",
]
