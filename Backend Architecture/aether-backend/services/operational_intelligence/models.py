"""Pydantic mirrors for frontend-safe operational intelligence contracts.

These models intentionally mirror ``packages/shared/operational-intelligence.ts``
so FastAPI/OpenAPI, Kyber, and generated SDKs can agree on stable graph,
realtime, investigation, governance, and event-pipeline payloads while the
underlying engines are implemented incrementally.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Generic, Literal, Optional, TypeVar, Union

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
    kind: str  # VertexType has 200+ types; OperationalEntityKind used only for filter input
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
    snapshot_id: Optional[str] = None
    path_ids: list[str] = Field(default_factory=list)
    pinned_node_ids: list[str] = Field(default_factory=list)
    pinned_edge_ids: list[str] = Field(default_factory=list)


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


class GraphCompareRequest(TenantScopedRequest):
    """Request to compare graph state at two points in time."""
    anchor: EntityRef
    asOf: str          # primary snapshot time (ISO-8601)
    compareTo: str     # baseline snapshot time (ISO-8601); typically earlier
    depth: int = Field(default=2, ge=1, le=10)
    filter: Optional[GraphQueryFilter] = None


class SnapshotCompareRequest(TenantScopedRequest):
    """Request to compare a saved traversal snapshot against the current graph state."""
    snapshot_id: Optional[str] = None


class GraphCompareNodeDiff(ContractModel):
    id: str
    kind: str
    label: Optional[str] = None
    changeType: Literal["added", "removed", "changed"]
    changedProperties: Optional[dict[str, Any]] = None


class GraphCompareEdgeDiff(ContractModel):
    id: str
    type: str
    from_: str = Field(alias="from")
    to: str
    changeType: Literal["added", "removed", "changed"]
    changedProperties: Optional[dict[str, Any]] = None


class GraphCompareResult(ContractModel):
    """Result of a bitemporal graph comparison between two as_of snapshots."""
    tenantId: str
    anchor: EntityRef
    asOf: str
    compareTo: str
    addedNodes: list[GraphCompareNodeDiff] = Field(default_factory=list)
    removedNodes: list[GraphCompareNodeDiff] = Field(default_factory=list)
    changedNodes: list[GraphCompareNodeDiff] = Field(default_factory=list)
    addedEdges: list[GraphCompareEdgeDiff] = Field(default_factory=list)
    removedEdges: list[GraphCompareEdgeDiff] = Field(default_factory=list)
    changedEdges: list[GraphCompareEdgeDiff] = Field(default_factory=list)
    unchangedNodeCount: int = 0
    unchangedEdgeCount: int = 0
    computedAt: str


# ── Phase 4: Boolean Filter Language ──────────────────────────────────────────
# Canonical definitions moved to shared/contracts_models/filters.py so shared
# planes (exploration, comparison) can compose the filter language without a
# services dependency. Re-exported here unchanged for existing importers.

from shared.contracts_models.filters import (  # noqa: E402
    FilterExpression,
    FilterGroup,
    FilterOperator,
)


# ── Phase 4: Universal graph query ────────────────────────────────────────────

QUERY_BUDGET_DEFAULTS = {
    "max_depth": 6,
    "max_nodes": 500,
    "max_edges": 2000,
    "timeout_seconds": 30,
}


class UniversalGraphQueryRequest(ContractModel):
    """Universal graph query with boolean filter, temporal replay, and pagination."""
    tenant_id: str
    anchors: list[str] = Field(default_factory=list)
    node_types: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)
    layers: list[str] = Field(default_factory=list)
    filter: Optional[FilterGroup] = None
    depth: int = Field(default=2, ge=1, le=6)
    limit: int = Field(default=100, ge=1, le=500)
    cursor: Optional[str] = None
    include_overlays: list[str] = Field(default_factory=list)
    as_of: Optional[str] = None
    include_evidence: bool = False
    include_provenance: bool = False
    include_clusters: bool = False
    explain: bool = False


class GraphResultMeta(ContractModel):
    truncated: bool = False
    truncation_reason: Optional[str] = None
    node_count: int = 0
    edge_count: int = 0
    execution_ms: int = 0
    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    budget_used: float = 0.0
    cursor: Optional[str] = None
    as_of: Optional[str] = None
    freshness_seconds: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)


class GraphQueryResponse(ContractModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    overlays: Optional[list[GraphOverlay]] = None
    meta: GraphResultMeta
    explainability: Optional[ExplainabilityMetadata] = None


# ── Phase 4: Facets ───────────────────────────────────────────────────────────

class FacetValue(ContractModel):
    value: str
    count: int


class GraphFacet(ContractModel):
    field: str
    values: list[FacetValue] = Field(default_factory=list)


class GraphFacetRequest(ContractModel):
    tenant_id: str
    filter: Optional[FilterGroup] = None
    facet_fields: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=500)
    as_of: Optional[str] = None


class GraphFacetResponse(ContractModel):
    facets: list[GraphFacet] = Field(default_factory=list)
    meta: GraphResultMeta


# ── Phase 4: Export ────────────────────────────────────────────────────────────

class GraphExportRequest(ContractModel):
    tenant_id: str
    filter: Optional[FilterGroup] = None
    format: Literal["json", "csv", "jsonl"] = "jsonl"
    depth: int = Field(default=2, ge=1, le=6)
    limit: int = Field(default=10000, ge=1, le=100000)
    as_of: Optional[str] = None


class GraphExportJob(ContractModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    tenant_id: str
    format: str
    created_at: str
    completed_at: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None


class FlowGraphRequest(ContractModel):
    """Request body for POST /v1/graph/flow — flow-of-funds graph traversal."""
    tenant_id: str
    anchor_entity_id: str
    direction: Literal["downstream", "upstream", "both"] = "downstream"
    depth: int = Field(default=4, ge=1, le=6)
    limit: int = Field(default=200, ge=1, le=500)
    min_amount_usd: Optional[float] = Field(default=None, ge=0)
    include_overlays: list[str] = []


# ── Phase 20: Canonical Path Intelligence ─────────────────────────────────────

PathClassification = Literal[
    "observed",         # all edges causality_class == observed_sequence
    "inferred",         # at least one edge is inferred_influence
    "attributed",       # at least one edge is attributed_influence
    "correlated",       # weakest claim: at least one edge is correlation
    "causal_supported", # at least one edge is experiment_incremental or direct_cause
    "mixed",            # multiple causality classes present
]


class PathNode(ContractModel):
    id: str
    kind: str
    label: Optional[str] = None
    hop: int = Field(ge=0)
    discovered_from: Optional[str] = None
    properties: Optional[dict[str, Any]] = None


class PathEdge(ContractModel):
    id: str
    type: str
    from_: str = Field(alias="from")
    to: str
    layer: str
    hop: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    causality_class: Optional[str] = None
    validFrom: Optional[str] = None
    properties: Optional[dict[str, Any]] = None


class PathScoreBreakdown(ContractModel):
    geometric_mean_confidence: float = Field(ge=0, le=1)
    min_edge_confidence: float = Field(ge=0, le=1)
    hop_penalty: float = Field(ge=0, le=1)
    causality_penalty: float = Field(ge=0, le=1)
    overall: float = Field(ge=0, le=1)
    scoring_version: str = "1"
    components: dict[str, float] = Field(default_factory=dict)


class RelationshipPath(ContractModel):
    path_id: str
    tenant_id: str
    source_id: str
    target_id: str
    ordered_node_ids: list[str]
    ordered_edge_ids: list[str]
    nodes: list[PathNode]
    edges: list[PathEdge]
    hop_count: int = Field(ge=0)
    path_confidence: float = Field(ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)
    classification: PathClassification
    layer_sequence: list[str]
    score_breakdown: PathScoreBreakdown
    as_of: Optional[str] = None
    computed_at: str


class PathExplanation(ContractModel):
    path_id: str
    summary: str
    why_connected: str
    hop_narrative: list[str]
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    contradictory_evidence: list[dict[str, Any]] = Field(default_factory=list)
    score_breakdown: PathScoreBreakdown
    classification: PathClassification
    causal_language_allowed: bool
    policy_ids: list[str] = Field(default_factory=list)
    computed_at: str


class TraversalSnapshot(ContractModel):
    snapshot_id: str
    tenant_id: str
    query: dict[str, Any]
    graph_watermark: str
    path_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    result_digest: str
    created_at: str
    expires_at: Optional[str] = None


class PathQuery(ContractModel):
    tenant_id: str
    source_id: str
    target_id: Optional[str] = None
    mode: Literal[
        "neighborhood", "shortest", "strongest", "k_shortest",
        "temporal", "attribution", "decision_outcome", "evidence",
        "multi_source",
    ] = "shortest"
    k: int = Field(default=3, ge=1, le=10)
    max_depth: int = Field(default=6, ge=1, le=20)
    direction: Literal["in", "out", "both"] = "both"
    filter: Optional[GraphQueryFilter] = None
    as_of: Optional[str] = None
    min_confidence: float = Field(default=0.0, ge=0, le=1)
    include_explanation: bool = False
    save_snapshot: bool = False
    additional_sources: list[str] = Field(default_factory=list)


class PathQueryResponse(ContractModel):
    paths: list[RelationshipPath]
    explanations: list[PathExplanation] = Field(default_factory=list)
    snapshot_id: Optional[str] = None
    meta: GraphResultMeta


class NodeExpansionRequest(ContractModel):
    tenant_id: str
    node_id: str
    direction: Literal["in", "out", "both"] = "both"
    filter: Optional[GraphQueryFilter] = None


class NodeExpansionResponse(ContractModel):
    node_id: str
    added_nodes: list[GraphNode]
    added_edges: list[GraphEdge]
    meta: GraphResultMeta


class DeepTraversalJob(ContractModel):
    job_id: str
    tenant_id: str
    query: PathQuery
    status: Literal[
        "queued", "planning", "running", "partial",
        "complete", "failed", "cancelled", "expired",
    ]
    progress_pct: float = Field(default=0, ge=0, le=100)
    partial_path_ids: list[str] = Field(default_factory=list)
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    expires_at: Optional[str] = None


class SnapshotCreateRequest(ContractModel):
    tenant_id: str
    query: Optional[dict[str, Any]] = None
    path_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    graph_watermark: Optional[str] = None


class PathExplainRequest(ContractModel):
    tenant_id: str
    path_id: str
