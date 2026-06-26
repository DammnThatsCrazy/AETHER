// =============================================================================
// Aether Operational Intelligence — frontend-safe API, graph, realtime, and
// event contracts for the backend intelligence platform.
//
// These contracts are additive and preserve the existing SDK event envelope,
// entity refs, and Profile 360 contracts. They define the stable boundary that
// Kyber and future generated SDKs can consume while backend engines continue to
// evolve behind versioned APIs.
// =============================================================================

import type { BaseEvent, EventType } from './events';
import type { EntityKind, EntityRef } from './entities';
import type { ActorKind } from './provenance';

// ---------------------------------------------------------------------------
// Shared API standards
// ---------------------------------------------------------------------------

export type ApiVersion = 'v1';

export type SortDirection = 'asc' | 'desc';

export interface PageRequest {
  /** Opaque cursor returned by a previous response. Prefer over offset. */
  cursor?: string;
  /** Hard limit for frontend requests. Backend default: 50; max: 500. */
  limit?: number;
}

export interface PageInfo {
  nextCursor?: string;
  previousCursor?: string;
  hasNextPage: boolean;
  hasPreviousPage: boolean;
  totalEstimate?: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  page: PageInfo;
}

export interface TimeRangeFilter {
  from?: string;
  to?: string;
  timezone?: string;
}

export interface ScoreRangeFilter {
  min?: number;
  max?: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    requestId: string;
    details?: Record<string, unknown>;
    retryable?: boolean;
  };
}

export interface TenantScopedRequest {
  tenantId: string;
  orgId?: string;
}

export type ConsistencyMode = 'cache' | 'read_your_writes' | 'strong';

// ---------------------------------------------------------------------------
// Intelligence dimensions and scores
// ---------------------------------------------------------------------------

export type IntelligenceDimension =
  | 'demographic'
  | 'geographic'
  | 'economic'
  | 'device'
  | 'behavioral'
  | 'temporal'
  | 'wallet'
  | 'chain'
  | 'stablecoin'
  | 'coordination'
  | 'relationship'
  | 'operational'
  | 'governance'
  | 'attribution'
  | 'agent';

export type ScoreKind =
  | 'confidence'
  | 'trust'
  | 'risk'
  | 'anomaly'
  | 'relationship'
  | 'attribution'
  | 'influence'
  | 'coordination';

export interface IntelligenceScore {
  kind: ScoreKind;
  value: number;
  label?: 'low' | 'medium' | 'high' | 'critical';
  explanation?: string;
  computedAt: string;
  modelRef?: string;
}

export interface EvidenceRef {
  id: string;
  type: 'event' | 'entity' | 'relationship' | 'document' | 'transaction' | 'model_output' | 'annotation';
  source: string;
  observedAt?: string;
  confidence?: number;
  uri?: string;
}

export interface ExplainabilityMetadata {
  summary: string;
  features?: Record<string, number | string | boolean>;
  evidence: EvidenceRef[];
  lineageEventIds?: string[];
  policyIds?: string[];
}

// ---------------------------------------------------------------------------
// Entity intelligence APIs
// ---------------------------------------------------------------------------

export type OperationalEntityKind =
  | EntityKind
  | 'individual'
  | 'organization'
  | 'cluster'
  | 'journey'
  | 'location'
  | 'economic_profile'
  | 'behavioral_profile'
  | 'attribution_path'
  | 'infrastructure_system';

export interface EntityProfileRequest extends TenantScopedRequest {
  entity: EntityRef;
  dimensions?: IntelligenceDimension[];
  consistency?: ConsistencyMode;
}

export interface OperationalEntityProfile {
  entity: EntityRef;
  displayName?: string;
  kind: OperationalEntityKind;
  actorKind?: ActorKind;
  dimensions: Partial<Record<IntelligenceDimension, Record<string, unknown>>>;
  scores: IntelligenceScore[];
  evidence: EvidenceRef[];
  lastSeenAt?: string;
  updatedAt: string;
}

export interface EntityTimelineQuery extends TenantScopedRequest, PageRequest {
  entity: EntityRef;
  time?: TimeRangeFilter;
  eventTypes?: EventType[];
  dimensions?: IntelligenceDimension[];
}

export interface EntityTimelineItem {
  event: BaseEvent;
  sequence: number;
  relatedEntities: EntityRef[];
  scores?: IntelligenceScore[];
}

export interface EntityRelationshipQuery extends TenantScopedRequest, PageRequest {
  entity: EntityRef;
  relationshipTypes?: string[];
  minScore?: number;
  depth?: number;
  time?: TimeRangeFilter;
}

// ---------------------------------------------------------------------------
// Graph intelligence APIs
// ---------------------------------------------------------------------------

export interface GraphNode {
  id: string;
  kind: OperationalEntityKind;
  label?: string;
  properties?: Record<string, unknown>;
  scores?: IntelligenceScore[];
}

export interface GraphEdge {
  id: string;
  type: string;
  from: string;
  to: string;
  directed: boolean;
  validFrom?: string;
  validTo?: string;
  properties?: Record<string, unknown>;
  scores?: IntelligenceScore[];
  evidence?: EvidenceRef[];
}

export interface GraphOverlay {
  id: string;
  name: string;
  dimensions: IntelligenceDimension[];
  nodeFilter?: GraphQueryFilter;
  edgeFilter?: GraphQueryFilter;
}

export interface GraphQueryFilter {
  kinds?: OperationalEntityKind[];
  edgeTypes?: string[];
  scoreRanges?: Partial<Record<ScoreKind, ScoreRangeFilter>>;
  time?: TimeRangeFilter;
  properties?: Record<string, string | number | boolean | string[]>;
}

export interface GraphTraversalRequest extends TenantScopedRequest {
  start: EntityRef;
  depth: number;
  direction?: 'in' | 'out' | 'both';
  filter?: GraphQueryFilter;
  overlays?: string[];
  limit?: number;
}

export interface ShortestPathRequest extends TenantScopedRequest {
  from: EntityRef;
  to: EntityRef;
  maxDepth?: number;
  filter?: GraphQueryFilter;
}

export interface TemporalGraphRequest extends TenantScopedRequest {
  anchor: EntityRef;
  asOf: string;
  window?: TimeRangeFilter;
  depth?: number;
  filter?: GraphQueryFilter;
}

export interface GraphOverlayRequest extends TenantScopedRequest {
  graph?: GraphQueryFilter;
  overlays: string[];
  limit?: number;
}

export interface GraphFilterRequest extends TenantScopedRequest {
  filter: GraphQueryFilter;
  limit?: number;
}

export interface GraphResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
  overlays?: GraphOverlay[];
  explainability?: ExplainabilityMetadata;
}

// ---------------------------------------------------------------------------
// Journey, group, cluster, and attribution APIs
// ---------------------------------------------------------------------------

export type JourneyState = 'started' | 'active' | 'converted' | 'abandoned' | 'escalated' | 'completed';

export interface JourneySummary {
  id: string;
  tenantId: string;
  primaryEntity: EntityRef;
  participants: EntityRef[];
  state: JourneyState;
  startedAt: string;
  updatedAt: string;
  completedAt?: string;
  scores: IntelligenceScore[];
}

export interface ClusterSummary {
  id: string;
  tenantId: string;
  type: 'deterministic_group' | 'behavioral' | 'fraud' | 'wallet' | 'geographic' | 'economic' | 'attribution' | 'coordination';
  label?: string;
  members: number;
  exemplarEntities?: EntityRef[];
  scores: IntelligenceScore[];
  updatedAt: string;
}

export interface AttributionPath {
  id: string;
  tenantId: string;
  subject: EntityRef;
  outcome: string;
  touchpoints: EvidenceRef[];
  confidence: number;
  model: 'first_touch' | 'last_touch' | 'linear' | 'markov' | 'shapley' | 'causal_graph';
  computedAt: string;
}

// ---------------------------------------------------------------------------
// Event pipeline and realtime contracts
// ---------------------------------------------------------------------------

export type IntelligenceEventName =
  | 'entity.updated'
  | 'entity.relationship.changed'
  | 'journey.updated'
  | 'cluster.updated'
  | 'graph.mutated'
  | 'score.updated'
  | 'alert.created'
  | 'investigation.updated'
  | 'governance.policy.evaluated'
  | 'web3.wallet.updated'
  | 'agent.coordination.updated'
  | 'suggestion.detected'
  | 'suggestion.oriented'
  | 'suggestion.created'
  | 'suggestion.review_required'
  | 'suggestion.approved'
  | 'suggestion.rejected'
  | 'suggestion.suppressed'
  | 'suggestion.executing'
  | 'suggestion.executed'
  | 'suggestion.delivered'
  | 'suggestion.outcome_recorded'
  | 'suggestion.closed'
  | 'suggestion.failed'
  | 'suggestion.expired';

export interface EventPipelineEnvelope<TPayload = Record<string, unknown>> {
  id: string;
  type: IntelligenceEventName | EventType;
  tenantId: string;
  orgId?: string;
  occurredAt: string;
  ingestedAt: string;
  schemaVersion: string;
  source: string;
  subject?: EntityRef;
  correlationId?: string;
  causationId?: string;
  replayable: boolean;
  payload: TPayload;
}

export interface RealtimeSubscribeMessage {
  action: 'subscribe';
  requestId: string;
  tenantId: string;
  channels: RealtimeChannel[];
  filters?: GraphQueryFilter & { entityIds?: string[]; investigationIds?: string[] };
  cursor?: string;
}

export interface RealtimeAckMessage {
  action: 'ack';
  requestId: string;
  accepted: boolean;
  cursor?: string;
  error?: ApiErrorBody['error'];
}

export interface RealtimeEventMessage<TPayload = Record<string, unknown>> {
  action: 'event';
  channel: RealtimeChannel;
  cursor: string;
  event: EventPipelineEnvelope<TPayload>;
}

export interface RealtimeHeartbeatMessage {
  action: 'heartbeat';
  serverTime: string;
}

export type RealtimeClientMessage = RealtimeSubscribeMessage | { action: 'unsubscribe'; requestId: string; channels: RealtimeChannel[] };
export type RealtimeServerMessage = RealtimeAckMessage | RealtimeEventMessage | RealtimeHeartbeatMessage;

export type RealtimeChannel =
  | 'tenant.events'
  | 'tenant.graph'
  | 'tenant.alerts'
  | 'entity.profile'
  | 'entity.relationships'
  | 'journey.timeline'
  | 'cluster.membership'
  | 'investigation.workspace'
  | 'governance.audit'
  | 'agent.coordination'
  | 'web3.wallets'
  | 'suggestions.feed'
  | 'suggestions.review'
  | 'suggestions.outcomes';

// ---------------------------------------------------------------------------
// Investigation and governance APIs
// ---------------------------------------------------------------------------

export type InvestigationStatus = 'open' | 'triage' | 'active' | 'escalated' | 'closed';

export interface InvestigationCase {
  id: string;
  tenantId: string;
  title: string;
  status: InvestigationStatus;
  subjects: EntityRef[];
  graphStateId?: string;
  evidence: EvidenceRef[];
  annotations: InvestigationAnnotation[];
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface InvestigationAnnotation {
  id: string;
  authorId: string;
  body: string;
  entityRefs?: EntityRef[];
  evidenceRefs?: EvidenceRef[];
  createdAt: string;
}

export interface GovernanceDecision {
  id: string;
  tenantId: string;
  principal: EntityRef;
  action: string;
  resource: EntityRef;
  allowed: boolean;
  policies: string[];
  obligations?: string[];
  explanation: ExplainabilityMetadata;
  evaluatedAt: string;
}

// ---------------------------------------------------------------------------
// Event Replay API
// ---------------------------------------------------------------------------

export interface ReplayRequest extends TenantScopedRequest {
  sourceTag: string;
  fromTime: string;
  toTime?: string;
  eventTypes?: string[];
  dryRun?: boolean;
}

export type ReplayJobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface ReplayJobResponse {
  id: string;
  tenantId: string;
  sourceTag: string;
  fromTime: string;
  toTime?: string;
  eventTypes?: string[];
  dryRun: boolean;
  status: ReplayJobStatus;
  cursor?: string;
  submittedAt: string;
  completedAt?: string;
  totalReplayed: number;
}

// ---------------------------------------------------------------------------
// Path Intelligence Types (Phase 20)
// ---------------------------------------------------------------------------

export type PathClassification =
  | 'observed'
  | 'inferred'
  | 'attributed'
  | 'correlated'
  | 'causal_supported'
  | 'mixed';

export interface PathNode {
  id: string;
  kind: string;
  label?: string;
  hop: number;
  discovered_from?: string;
  properties?: Record<string, unknown>;
}

export interface PathEdge {
  id: string;
  type: string;
  from: string;
  to: string;
  layer: string;
  hop: number;
  confidence: number;
  causality_class?: string;
  validFrom?: string;
  properties?: Record<string, unknown>;
}

export interface PathScoreBreakdown {
  geometric_mean_confidence: number;
  min_edge_confidence: number;
  hop_penalty: number;
  causality_penalty: number;
  overall: number;
  scoring_version: string;
  components: Record<string, number>;
}

export interface RelationshipPath {
  path_id: string;
  tenant_id: string;
  source_id: string;
  target_id: string;
  ordered_node_ids: string[];
  ordered_edge_ids: string[];
  nodes: PathNode[];
  edges: PathEdge[];
  hop_count: number;
  path_confidence: number;
  evidence_coverage: number;
  classification: PathClassification;
  layer_sequence: string[];
  score_breakdown: PathScoreBreakdown;
  as_of?: string;
  computed_at: string;
}

export interface PathExplanation {
  path_id: string;
  summary: string;
  why_connected: string;
  hop_narrative: string[];
  supporting_evidence: Record<string, unknown>[];
  contradictory_evidence: Record<string, unknown>[];
  score_breakdown: PathScoreBreakdown;
  classification: PathClassification;
  causal_language_allowed: boolean;
  policy_ids: string[];
  computed_at: string;
}

export interface TraversalSnapshot {
  snapshot_id: string;
  tenant_id: string;
  query: Record<string, unknown>;
  graph_watermark: string;
  path_ids: string[];
  node_ids: string[];
  edge_ids: string[];
  result_digest: string;
  created_at: string;
  expires_at?: string;
}

export type PathMode =
  | 'neighborhood'
  | 'shortest'
  | 'strongest'
  | 'k_shortest'
  | 'temporal'
  | 'attribution'
  | 'decision_outcome'
  | 'evidence'
  | 'multi_source';

export interface PathQuery {
  tenant_id: string;
  source_id: string;
  target_id?: string;
  mode?: PathMode;
  k?: number;
  max_depth?: number;
  direction?: 'in' | 'out' | 'both';
  filter?: GraphQueryFilter;
  as_of?: string;
  min_confidence?: number;
  include_explanation?: boolean;
  save_snapshot?: boolean;
  additional_sources?: string[];
}

export interface GraphResultMeta {
  truncated: boolean;
  truncation_reason?: string;
  node_count: number;
  edge_count: number;
  execution_ms: number;
  query_id: string;
  budget_used: number;
  cursor?: string;
  as_of?: string;
  freshness_seconds?: number;
  warnings: string[];
}

export interface PathQueryResponse {
  paths: RelationshipPath[];
  explanations: PathExplanation[];
  snapshot_id?: string;
  meta: GraphResultMeta;
}

export interface NodeExpansionRequest {
  tenant_id: string;
  node_id: string;
  direction?: 'in' | 'out' | 'both';
  filter?: GraphQueryFilter;
}

export interface NodeExpansionResponse {
  node_id: string;
  added_nodes: GraphNode[];
  added_edges: GraphEdge[];
  meta: GraphResultMeta;
}

export type DeepTraversalJobStatus =
  | 'queued'
  | 'planning'
  | 'running'
  | 'partial'
  | 'complete'
  | 'failed'
  | 'cancelled'
  | 'expired';

export interface DeepTraversalJob {
  job_id: string;
  tenant_id: string;
  query: PathQuery;
  status: DeepTraversalJobStatus;
  progress_pct: number;
  partial_path_ids: string[];
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
  expires_at?: string;
}
