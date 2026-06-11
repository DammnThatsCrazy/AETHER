"""Pydantic mirrors for frontend-safe operational intelligence contracts.

These models intentionally mirror ``packages/shared/operational-intelligence.ts``
so FastAPI/OpenAPI, Kyber, and generated SDKs can agree on stable graph,
realtime, investigation, governance, and event-pipeline payloads while the
underlying engines are implemented incrementally.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Base model for API contracts that must tolerate additive fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


SortDirection = Literal["asc", "desc"]
ApiVersion = Literal["v1"]
ConsistencyMode = Literal["cache", "read_your_writes", "strong"]

EntityKind = Literal[
    "tenant",
    "org",
    "user",
    "session",
    "device",
    "application",
    "resource",
    "approval",
    "entitlement",
    "payment",
    "invoice",
    "subscription",
    "plan",
    "wallet",
    "contract",
    "chain",
    "token",
    "protocol",
    "agent",
    "service",
    "payment_intent",
    "settlement_event",
    "economic_resource",
    "facilitator",
    "agent_economic_identity",
    "agent_profile360",
]

OperationalEntityKind = Literal[
    "tenant",
    "org",
    "user",
    "session",
    "device",
    "application",
    "resource",
    "approval",
    "entitlement",
    "payment",
    "invoice",
    "subscription",
    "plan",
    "wallet",
    "contract",
    "chain",
    "token",
    "protocol",
    "agent",
    "service",
    "payment_intent",
    "settlement_event",
    "economic_resource",
    "facilitator",
    "agent_economic_identity",
    "agent_profile360",
    "individual",
    "organization",
    "cluster",
    "journey",
    "location",
    "economic_profile",
    "behavioral_profile",
    "attribution_path",
    "infrastructure_system",
]

ActorKind = Literal["human", "org", "wallet", "agent", "service", "system"]

EventType = Literal[
    "track",
    "page",
    "screen",
    "heartbeat",
    "error",
    "performance",
    "experiment",
    "identify",
    "consent",
    "conversion",
    "payment_initiated",
    "payment_completed",
    "payment_failed",
    "approval_requested",
    "approval_resolved",
    "entitlement_granted",
    "entitlement_revoked",
    "access_granted",
    "access_denied",
    "wallet",
    "transaction",
    "contract_action",
    "agent_task",
    "agent_decision",
    "a2h_interaction",
    "x402_payment",
]

IntelligenceDimension = Literal[
    "demographic",
    "geographic",
    "economic",
    "device",
    "behavioral",
    "temporal",
    "wallet",
    "chain",
    "stablecoin",
    "coordination",
    "relationship",
    "operational",
    "governance",
    "attribution",
    "agent",
]

ScoreKind = Literal[
    "confidence",
    "trust",
    "risk",
    "anomaly",
    "relationship",
    "attribution",
    "influence",
    "coordination",
]

EvidenceType = Literal[
    "event",
    "entity",
    "relationship",
    "document",
    "transaction",
    "model_output",
    "annotation",
]

RealtimeChannel = Literal[
    "tenant.events",
    "tenant.graph",
    "tenant.alerts",
    "entity.profile",
    "entity.relationships",
    "journey.timeline",
    "cluster.membership",
    "investigation.workspace",
    "governance.audit",
    "agent.coordination",
    "web3.wallets",
]

IntelligenceEventName = Literal[
    "entity.updated",
    "entity.relationship.changed",
    "journey.updated",
    "cluster.updated",
    "graph.mutated",
    "score.updated",
    "alert.created",
    "investigation.updated",
    "governance.policy.evaluated",
    "web3.wallet.updated",
    "agent.coordination.updated",
]


class PageRequest(ContractModel):
    cursor: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


class PageInfo(ContractModel):
    nextCursor: Optional[str] = None
    previousCursor: Optional[str] = None
    hasNextPage: bool = False
    hasPreviousPage: bool = False
    totalEstimate: Optional[int] = Field(default=None, ge=0)


T = TypeVar("T")


class PaginatedResponse(ContractModel, Generic[T]):
    data: list[T]
    page: PageInfo


class TimeRangeFilter(ContractModel):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    timezone: Optional[str] = None


class ScoreRangeFilter(ContractModel):
    min: Optional[float] = Field(default=None, ge=0, le=1)
    max: Optional[float] = Field(default=None, ge=0, le=1)


class ApiErrorDetail(ContractModel):
    code: str
    message: str
    requestId: str
    details: Optional[dict[str, Any]] = None
    retryable: Optional[bool] = None


class ApiErrorBody(ContractModel):
    error: ApiErrorDetail


class TenantScopedRequest(ContractModel):
    tenantId: str
    orgId: Optional[str] = None


class EntityRef(ContractModel):
    kind: EntityKind
    id: str
    label: Optional[str] = None


class IntelligenceScore(ContractModel):
    kind: ScoreKind
    value: float = Field(ge=0, le=1)
    label: Optional[Literal["low", "medium", "high", "critical"]] = None
    explanation: Optional[str] = None
    computedAt: str
    modelRef: Optional[str] = None


class EvidenceRef(ContractModel):
    id: str
    type: EvidenceType
    source: str
    observedAt: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    uri: Optional[str] = None


class ExplainabilityMetadata(ContractModel):
    summary: str
    features: Optional[dict[str, float | str | bool]] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    lineageEventIds: Optional[list[str]] = None
    policyIds: Optional[list[str]] = None


class EntityProfileRequest(TenantScopedRequest):
    entity: EntityRef
    dimensions: Optional[list[IntelligenceDimension]] = None
    consistency: Optional[ConsistencyMode] = None


class OperationalEntityProfile(ContractModel):
    entity: EntityRef
    displayName: Optional[str] = None
    kind: OperationalEntityKind
    actorKind: Optional[ActorKind] = None
    dimensions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    scores: list[IntelligenceScore] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    lastSeenAt: Optional[str] = None
    updatedAt: str


class EntityTimelineQuery(TenantScopedRequest, PageRequest):
    entity: EntityRef
    time: Optional[TimeRangeFilter] = None
    eventTypes: Optional[list[EventType]] = None
    dimensions: Optional[list[IntelligenceDimension]] = None


class EntityTimelineItem(ContractModel):
    event: dict[str, Any]
    sequence: int = Field(ge=0)
    relatedEntities: list[EntityRef] = Field(default_factory=list)
    scores: Optional[list[IntelligenceScore]] = None


class EntityRelationshipQuery(TenantScopedRequest, PageRequest):
    entity: EntityRef
    relationshipTypes: Optional[list[str]] = None
    minScore: Optional[float] = Field(default=None, ge=0, le=1)
    depth: Optional[int] = Field(default=None, ge=1, le=10)
    time: Optional[TimeRangeFilter] = None


class GraphQueryFilter(ContractModel):
    kinds: Optional[list[OperationalEntityKind]] = None
    edgeTypes: Optional[list[str]] = None
    scoreRanges: Optional[dict[ScoreKind, ScoreRangeFilter]] = None
    time: Optional[TimeRangeFilter] = None
    properties: Optional[dict[str, str | int | float | bool | list[str]]] = None


class GraphNode(ContractModel):
    id: str
    kind: OperationalEntityKind
    label: Optional[str] = None
    properties: Optional[dict[str, Any]] = None
    scores: Optional[list[IntelligenceScore]] = None


class GraphEdge(ContractModel):
    id: str
    type: str
    from_: str = Field(alias="from")
    to: str
    directed: bool
    validFrom: Optional[str] = None
    validTo: Optional[str] = None
    properties: Optional[dict[str, Any]] = None
    scores: Optional[list[IntelligenceScore]] = None
    evidence: Optional[list[EvidenceRef]] = None


class GraphOverlay(ContractModel):
    id: str
    name: str
    dimensions: list[IntelligenceDimension]
    nodeFilter: Optional[GraphQueryFilter] = None
    edgeFilter: Optional[GraphQueryFilter] = None
    properties: Optional[dict[str, Any]] = None


class GraphTraversalRequest(TenantScopedRequest):
    start: EntityRef
    depth: int = Field(ge=1, le=10)
    direction: Literal["in", "out", "both"] = "both"
    filter: Optional[GraphQueryFilter] = None
    overlays: Optional[list[str]] = None
    limit: int = Field(default=100, ge=1, le=500)


class ShortestPathRequest(TenantScopedRequest):
    from_: EntityRef = Field(alias="from")
    to: EntityRef
    maxDepth: int = Field(default=6, ge=1, le=20)
    filter: Optional[GraphQueryFilter] = None


class TemporalGraphRequest(TenantScopedRequest):
    anchor: EntityRef
    asOf: str
    window: Optional[TimeRangeFilter] = None
    depth: int = Field(default=2, ge=1, le=10)
    filter: Optional[GraphQueryFilter] = None


class GraphOverlayRequest(TenantScopedRequest):
    graph: Optional[GraphQueryFilter] = None
    overlays: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=500)


class GraphFilterRequest(TenantScopedRequest):
    filter: GraphQueryFilter
    limit: int = Field(default=100, ge=1, le=500)


class GraphResult(ContractModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    overlays: Optional[list[GraphOverlay]] = None
    explainability: Optional[ExplainabilityMetadata] = None


class JourneySummary(ContractModel):
    id: str
    tenantId: str
    primaryEntity: EntityRef
    participants: list[EntityRef] = Field(default_factory=list)
    state: Literal["started", "active", "converted", "abandoned", "escalated", "completed"]
    startedAt: str
    updatedAt: str
    completedAt: Optional[str] = None
    scores: list[IntelligenceScore] = Field(default_factory=list)


class ClusterSummary(ContractModel):
    id: str
    tenantId: str
    type: Literal[
        "deterministic_group",
        "behavioral",
        "fraud",
        "wallet",
        "geographic",
        "economic",
        "attribution",
        "coordination",
    ]
    label: Optional[str] = None
    members: int = Field(ge=0)
    exemplarEntities: Optional[list[EntityRef]] = None
    scores: list[IntelligenceScore] = Field(default_factory=list)
    updatedAt: str


class AttributionPath(ContractModel):
    id: str
    tenantId: str
    subject: EntityRef
    outcome: str
    touchpoints: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    model: Literal["first_touch", "last_touch", "linear", "markov", "shapley", "causal_graph"]
    computedAt: str


class EventPipelineEnvelope(ContractModel):
    id: str
    type: IntelligenceEventName | EventType
    tenantId: str
    orgId: Optional[str] = None
    occurredAt: str
    ingestedAt: str
    schemaVersion: str
    source: str
    subject: Optional[EntityRef] = None
    correlationId: Optional[str] = None
    causationId: Optional[str] = None
    replayable: bool
    payload: dict[str, Any] = Field(default_factory=dict)


class RealtimeSubscribeMessage(ContractModel):
    action: Literal["subscribe"]
    requestId: str
    tenantId: str
    channels: list[RealtimeChannel]
    filters: Optional[GraphQueryFilter] = None
    cursor: Optional[str] = None


class RealtimeUnsubscribeMessage(ContractModel):
    action: Literal["unsubscribe"]
    requestId: str
    channels: list[RealtimeChannel]


class RealtimeAckMessage(ContractModel):
    action: Literal["ack"]
    requestId: str
    accepted: bool
    cursor: Optional[str] = None
    error: Optional[ApiErrorDetail] = None


class RealtimeEventMessage(ContractModel):
    action: Literal["event"]
    channel: RealtimeChannel
    cursor: str
    event: EventPipelineEnvelope


class RealtimeHeartbeatMessage(ContractModel):
    action: Literal["heartbeat"]
    serverTime: str


class InvestigationAnnotation(ContractModel):
    id: str
    authorId: str
    body: str
    entityRefs: Optional[list[EntityRef]] = None
    evidenceRefs: Optional[list[EvidenceRef]] = None
    createdAt: str


class InvestigationCase(ContractModel):
    id: str
    tenantId: str
    title: str
    status: Literal["open", "triage", "active", "escalated", "closed"]
    subjects: list[EntityRef] = Field(default_factory=list)
    graphStateId: Optional[str] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    annotations: list[InvestigationAnnotation] = Field(default_factory=list)
    createdBy: str
    createdAt: str
    updatedAt: str


class GovernanceDecision(ContractModel):
    id: str
    tenantId: str
    principal: EntityRef
    action: str
    resource: EntityRef
    allowed: bool
    policies: list[str] = Field(default_factory=list)
    obligations: Optional[list[str]] = None
    explanation: ExplainabilityMetadata
    evaluatedAt: str
