/**
 * Intelligence Graph Contract — canonical TypeScript definitions.
 *
 * Four relationship layers: H2H, H2A, A2H, A2A.
 * This file is the single TypeScript source of truth for graph layer
 * classification. Any backend or frontend code that classifies edges
 * must agree with these definitions.
 *
 * Validated in CI by tests/contracts/test_graph_contract_parity.py.
 */

// ── Relationship layers ───────────────────────────────────────────────────────

/** All four canonical relationship layers. Must never be reduced to three. */
export type RelationshipLayer = 'H2H' | 'H2A' | 'A2H' | 'A2A';

export const RELATIONSHIP_LAYERS: readonly RelationshipLayer[] = [
  'H2H', // Human-to-Human
  'H2A', // Human-to-Agent
  'A2H', // Agent-to-Human
  'A2A', // Agent-to-Agent
] as const;

export const LAYER_COUNT = RELATIONSHIP_LAYERS.length; // must be 4

/** Layer metadata for display and documentation. */
export const LAYER_DESCRIPTIONS: Record<RelationshipLayer, { label: string; description: string }> = {
  H2H: {
    label: 'Human-to-Human',
    description: 'Identity graph: merges, referrals, clusters, behavioral similarity',
  },
  H2A: {
    label: 'Human-to-Agent',
    description: 'Delegation, configuration, ownership, supervision of agents by humans',
  },
  A2H: {
    label: 'Agent-to-Human',
    description: 'Agent notifications, recommendations, result delivery, and escalations to humans',
  },
  A2A: {
    label: 'Agent-to-Agent',
    description: 'Orchestration, hiring, payments, and trust propagation between agents',
  },
};

// ── Edge type classification ──────────────────────────────────────────────────

/** Canonical edge types with their layer classification. */
export const EDGE_LAYER_MAP: Record<string, RelationshipLayer> = {
  // H2H edges
  HAS_SESSION: 'H2H',
  VIEWED_PAGE: 'H2H',
  TRIGGERED_EVENT: 'H2H',
  USED_DEVICE: 'H2H',
  BELONGS_TO: 'H2H',
  RESOLVED_AS: 'H2H',
  ENRICHED_BY: 'H2H',
  HAS_FINGERPRINT: 'H2H',
  SEEN_FROM_IP: 'H2H',
  LOCATED_IN: 'H2H',
  HAS_EMAIL: 'H2H',
  HAS_PHONE: 'H2H',
  OWNS_WALLET: 'H2H',
  MEMBER_OF_CLUSTER: 'H2H',
  SIMILAR_TO: 'H2H',
  IP_MAPS_TO: 'H2H',

  // H2A edges
  LAUNCHED_BY: 'H2A',
  DELEGATES: 'H2A',
  INTERACTS_WITH: 'H2A',
  ATTRIBUTED_TO: 'H2A',

  // A2H edges
  NOTIFIES: 'A2H',
  RECOMMENDS: 'A2H',
  DELIVERS_TO: 'A2H',
  ESCALATES_TO: 'A2H',
  HAS_RECOMMENDATION: 'A2H',
  SUPPORTED_BY: 'A2H',
  SELECTED_BY: 'A2H',
  // A2H — additional delivery/approval/escalation edges
  ACTED_FOR: 'A2H',
  HAS_RETARGET_RECOMMENDATION: 'A2H',
  APPROVED_BY: 'A2H',
  REJECTED_BY: 'A2H',
  REQUESTS_APPROVAL_FROM: 'A2H',
  ESCALATES_PAYMENT_TO: 'A2H',
  ESCALATED_TO_HUMAN: 'A2H',
  AGENT_PRODUCED_RISK_SIGNAL: 'A2H',
  EXTERNAL_ACCOUNT_EMITTED_NOTIFICATION: 'A2H',
  INTERACTION_FLAGGED_REPLAY_RISK: 'A2H',

  // A2A edges
  PAYS: 'A2A',
  CONSUMES: 'A2A',
  HIRED: 'A2A',
  DEPLOYED: 'A2A',
  CALLED: 'A2A',
  COMPOSED_WITH: 'A2A',
  UPGRADED: 'A2A',
  GOVERNED_BY: 'A2A',
  DEPENDS_ON: 'A2A',
  PERFORMED_ACTION: 'A2A',
  EXECUTED_AS: 'A2A',
  PRODUCED: 'A2A',
  UPDATES_CONFIDENCE_FOR: 'A2A',

  // Fraud Network Intelligence edges
  MEMBER_OF_FRAUD_NETWORK: 'H2H',
  HAS_RISK_ROLE: 'H2H',
  SCORED_AS_RISKY: 'H2H',
  SUPPORTED_BY_EVIDENCE: 'H2H',
  PART_OF_FLOW_TRACE: 'H2H',
  FLOW_PATH_NEXT: 'H2H',
  HAS_SOURCE: 'H2H',
  HAS_SINK: 'H2H',
  HAS_CONTROLLER: 'H2H',
  USES_MULE: 'H2H',
  LINKED_BY_DEVICE: 'H2H',
  LINKED_BY_IP: 'H2H',
  LINKED_BY_WALLET: 'H2H',
  LINKED_BY_AGENT: 'A2A',
  LINKED_BY_DELEGATION: 'H2A',
  ATTACHED_TO_CASE: 'H2H',
  // Silver-sourced commerce & outcome edges
  PURCHASED: 'H2A',
  ACHIEVED_OUTCOME: 'H2H',
  CONTACTED: 'A2H',

  // Economic flow edges (Phase 2)
  PAYS_FOR: 'A2A',
  TRANSFERS_TO: 'H2H',
  SETTLED_VIA: 'A2A',
  REFUNDED_BY: 'H2H',
  CHARGED_BACK_BY: 'H2H',

  // Fraud ring edges (Phase 2)
  LAYERED_THROUGH: 'H2H',
  SMURFED_VIA: 'H2H',

  // Campaign and attribution edges (Phase 2)
  ACQUIRED_VIA: 'H2H',
  CONVERTED_FROM: 'H2H',
  ATTRIBUTED_TO_CAMPAIGN: 'H2H',
  TOUCHPOINT_IN: 'H2H',

  // Journey step edges (Phase 2)
  NEXT_IN_JOURNEY: 'H2H',
  ABANDONED_AT: 'H2H',
  CONVERTED_AT: 'H2H',

  // Cluster lifecycle edges (Phase 2)
  BRIDGES: 'H2H',
  MERGED_INTO: 'H2H',
  SPLIT_FROM: 'H2H',
};

/** Classify an edge type string into its relationship layer. */
export function classifyEdgeType(edgeType: string): RelationshipLayer | null {
  return (EDGE_LAYER_MAP[edgeType] as RelationshipLayer) ?? null;
}

// ── Layer counts ──────────────────────────────────────────────────────────────

export type LayerCounts = Record<RelationshipLayer, number>;

/** Count edges by relationship layer. */
export function countEdgesByLayer(edges: Array<{ type: string }>): LayerCounts {
  const counts: LayerCounts = { H2H: 0, H2A: 0, A2H: 0, A2A: 0 };
  for (const edge of edges) {
    const layer = classifyEdgeType(edge.type);
    if (layer) counts[layer]++;
  }
  return counts;
}

// ── Overlay status ────────────────────────────────────────────────────────────

/** Valid overlay status values — "placeholder" is never valid. */
export type OverlayStatus = 'computed' | 'no_data';

export interface GraphOverlayProperties {
  status: OverlayStatus;
  node_count?: number;
  edge_count?: number;
  layer_counts?: LayerCounts;
  layer_distribution_pct?: Record<string, number>;
  layers_present?: RelationshipLayer[];
  computed_at?: string;
  reason?: string;
}

// ── Graph health ──────────────────────────────────────────────────────────────

export interface GraphHealthResponse {
  status: 'healthy' | 'no_data' | 'degraded' | 'dependency_unavailable';
  backend_mode: 'neptune' | 'local' | 'staging';
  node_count: number;
  edge_count: number;
  layer_counts: LayerCounts;
  layers_with_data: RelationshipLayer[];
  all_four_layers_present: boolean;
  relationship_layers: typeof RELATIONSHIP_LAYERS;
  computed_at: string;
}

// ── Tenant isolation ──────────────────────────────────────────────────────────

/** Every graph request must carry tenantId for tenant-scoped reads. */
export interface TenantScopedGraphRequest {
  tenantId: string;
}

/** Layer filter for tenant-facing UI — includes all four layers. */
export type LayerFilter = RelationshipLayer | 'all';

export const LAYER_FILTERS: readonly LayerFilter[] = ['all', ...RELATIONSHIP_LAYERS];

// ── Universal Envelopes (Phase 2) ─────────────────────────────────────────────

/**
 * How a data point was produced. Replaces the thin `Observation` type from
 * provenance.ts. Any graph node or edge may carry this classification.
 */
export type ObservationClass =
  | 'observed'            // directly measured from a real signal
  | 'deterministic'       // resolved by rule without uncertainty
  | 'probabilistic'       // ML model output with confidence
  | 'derived'             // computed from other observations
  | 'predicted'           // future-state model output
  | 'simulated'           // counterfactual / what-if scenario
  | 'manually_asserted'   // human annotation
  | 'externally_enriched' // third-party data enrichment

/** Lifecycle state of a graph node or cluster. */
export type LifecycleState =
  | 'provisional'   // newly created, not yet confirmed
  | 'unresolved'    // identity not yet resolved
  | 'active'        // healthy, receiving signals
  | 'growing'       // cluster expanding
  | 'stable'        // cluster stable over time
  | 'shrinking'     // cluster losing members
  | 'dormant'       // no recent signals
  | 'decaying'      // signal quality declining
  | 'reactivated'   // dormant → active again
  | 'merged'        // merged into another entity/cluster
  | 'split'         // split into multiple entities/clusters
  | 'suppressed'    // suppressed by consent or policy
  | 'disputed'      // under investigation or contested
  | 'expired'       // past retention window
  | 'revoked'       // access or consent revoked
  | 'invalidated'   // found to be erroneous
  | 'deleted'       // soft-deleted, pending purge
  | 'tombstoned'    // permanently removed, marker retained

/** Bitemporal time envelope — every graph element may carry this. */
export interface TemporalEnvelope {
  event_time: string;         // when it happened externally (ISO8601)
  observed_time: string;      // when Aether first received the signal
  ingestion_time?: string;    // when the raw event entered the pipeline
  processed_time?: string;    // when the event was processed into the graph
  graph_mutation_time?: string; // when the graph was actually mutated
  first_seen: string;         // earliest known occurrence (ISO8601)
  last_seen: string;          // most recent known occurrence (ISO8601)
  valid_from?: string;        // bitemporal valid-time start (when true in reality)
  valid_to?: string;          // bitemporal valid-time end (null = still valid)
  recorded_at?: string;       // system-time when Aether recorded this fact
  superseded_at?: string;     // system-time when this fact was superseded
  age_days?: number;          // derived: days since first_seen
  recency_score?: number;     // 0–1 freshness score (1 = just seen)
  lifecycle_state: LifecycleState;
}

/** Full provenance envelope — supersedes the thin Provenance from provenance.ts. */
export interface ProvenanceEnvelope {
  source_kind: string;          // 'sdk' | 'connector' | 'backend' | 'inferred' | 'import'
  source_platform?: string;     // 'web' | 'ios' | 'android' | 'react-native' | 'server'
  source_system?: string;       // originating external system name
  source_connector?: string;    // connector ID that ingested this
  actor_kind?: string;          // 'human' | 'org' | 'wallet' | 'agent' | 'service' | 'system'
  rail?: string;                // payment/transport rail if applicable
  collection_method?: string;   // 'sdk_event' | 'batch_import' | 'stream' | 'api_poll'
  processing_pipeline?: string; // pipeline name that produced this node/edge
  graph_projector?: string;     // projector that wrote this to the graph
  schema_version?: string;      // contract schema version at time of write
  model_id?: string;            // ML model that produced this (if derived/predicted)
  model_version?: string;       // version of that model
  freshness_seconds?: number;   // seconds since source event
  quality_score?: number;       // 0–1 data quality estimate
  evidence_refs: string[];      // IDs of supporting evidence nodes
  correlation_id?: string;      // request/trace correlation ID
  idempotency_key?: string;     // dedup key for write operations
  observation_class: ObservationClass;
  external_ref?: string;        // external ID (charge ID, tx hash, x402 ref)
}

/** Risk signal envelope for any node or edge. */
export interface RiskEnvelope {
  risk_score: number;             // 0–100 normalized risk score
  risk_type?: string;             // 'fraud' | 'credit' | 'compliance' | 'aml' | 'operational'
  severity?: 'low' | 'medium' | 'high' | 'critical';
  confidence: number;             // 0–1 model confidence
  reason_codes: string[];         // machine-readable reason codes
  evidence_refs: string[];        // graph node IDs of supporting evidence
  alert_state?: string;           // 'open' | 'investigating' | 'resolved' | 'dismissed'
  investigation_state?: string;   // 'open' | 'pending_review' | 'closed'
  disposition?: string;           // 'confirmed_fraud' | 'false_positive' | 'inconclusive'
}

/** Economic value envelope for any node or edge. */
export interface EconomicEnvelope {
  amount?: number;                // raw numeric amount
  currency?: string;              // ISO 4217 currency code
  currency_normalized_to?: string; // currency after FX normalization
  fx_rate?: number;               // FX rate applied during normalization
  direction?: 'inflow' | 'outflow' | 'internal';
  rail?: string;                  // 'fiat' | 'stripe' | 'onchain' | 'x402' | 'internal_credit'
  revenue?: number;               // attributed revenue (normalized)
  cost?: number;                  // attributed cost (normalized)
  value?: number;                 // net value (revenue - cost)
  margin?: number;                // margin fraction 0–1
  counterparty_id?: string;       // entity ID of the counterparty
  economic_role?: string;         // 'payer' | 'payee' | 'intermediary' | 'facilitator'
  attribution_share?: number;     // 0–1 share of credit for this touchpoint
  value_confidence?: number;      // 0–1 confidence in the value estimate
}

/** Governance and consent envelope for any node or edge. */
export interface GovernanceEnvelope {
  tenant_id: string;
  consent_purpose?: string;       // 'analytics' | 'marketing' | 'personalization' | 'agent' | ...
  consent_state?: 'granted' | 'withdrawn' | 'expired' | 'not_required';
  authorization_source?: string;  // what granted access to this data
  authorization_scope?: string[]; // list of authorized operations
  jurisdiction?: string;          // ISO 3166-1 alpha-2 country or region code
  retention_days?: number;        // days until deletion required
  redacted?: boolean;             // true if personal fields were redacted
  activation_eligible?: boolean;  // false when consent withdrawn/expired
  policy_version?: string;        // version of governing policy
}

/** Identity resolution envelope for any entity node. */
export interface IdentityEnvelope {
  canonical_entity_id: string;    // stable canonical ID after resolution
  aliases: string[];              // known alternate IDs for this entity
  resolution_method?: 'deterministic' | 'probabilistic' | 'asserted';
  identity_confidence?: number;   // 0–1 confidence in the canonical ID
  cluster_memberships: string[];  // cluster IDs this entity belongs to
  merge_history?: string[];       // previous canonical IDs merged into this
  split_history?: string[];       // entity IDs that split from this
  resolution_state: 'resolved' | 'unresolved' | 'anonymous' | 'pseudonymous' | 'disputed';
}

/** Outcome tracking envelope for predictions, recommendations, and experiments. */
export interface OutcomeEnvelope {
  intended_outcome?: string;      // what the action was meant to achieve
  observed_outcome?: string;      // what actually happened
  value?: number;                 // economic value of the outcome (normalized)
  result_state?: 'converted' | 'retained' | 'churned' | 'no_impact' | 'unknown';
  feedback?: string;              // human or system feedback on the outcome
  measurement_quality?: number;   // 0–1 confidence in the measurement
  recorded_time?: string;         // ISO8601 when the outcome was observed
}

/** Composite: all universal envelopes optional on any graph element. */
export interface UniversalEnvelopes {
  temporal?: TemporalEnvelope;
  provenance?: ProvenanceEnvelope;
  risk?: RiskEnvelope;
  economic?: EconomicEnvelope;
  governance?: GovernanceEnvelope;
  identity?: IdentityEnvelope;
  outcome?: OutcomeEnvelope;
}

// ── Cluster contract (Phase 2) ────────────────────────────────────────────────

/** All supported cluster types. */
export type ClusterType =
  | 'identity'        // resolved identity cluster (same person, multiple signals)
  | 'household'       // co-located household members
  | 'org'             // organization / corporate group
  | 'device'          // shared device cluster
  | 'wallet'          // linked wallet cluster
  | 'behavioral'      // behavioral similarity cluster
  | 'geographic'      // geographic proximity cluster
  | 'economic_segment' // economic tier / LTV segment
  | 'campaign_cohort' // users acquired via same campaign
  | 'journey'         // users on same journey path
  | 'fraud_network'   // fraud ring cluster
  | 'risk'            // elevated-risk entity cluster
  | 'dormant'         // inactive / churned cohort
  | 'reactivated'     // previously dormant, now active
  | 'unresolved'      // pending resolution

/** Full cluster node representation (Cluster360 data model). */
export interface ClusterNode {
  cluster_id: string;
  cluster_type: ClusterType;
  tenant_id: string;
  label: string;
  member_count: number;
  formation_reason?: string;       // why this cluster was created
  confidence: number;              // 0–1 confidence in cluster membership
  lifecycle_state: LifecycleState;
  // Economic summary
  total_revenue?: number;
  total_spend?: number;
  ltv_estimate?: number;
  economic_tier?: string;
  // Risk summary
  max_risk_score?: number;
  risk_member_count?: number;
  fraud_network_id?: string;
  // Growth metrics
  growth_rate?: number;            // members added per day (rolling 30d)
  shrinkage_rate?: number;         // members removed per day (rolling 30d)
  stability_score?: number;        // 0–1 how stable membership is
  cohesion_score?: number;         // 0–1 how similar members are
  bridge_entity_ids?: string[];    // entity IDs that connect sub-clusters
  // Campaign attribution
  acquisition_campaign_id?: string;
  campaign_attribution_share?: number;
  // Temporal
  first_seen: string;
  last_seen: string;
  last_mutation_time?: string;
  // Envelopes
  envelopes?: UniversalEnvelopes;
}

// ── Filter language (Phase 2 / Phase 4) ───────────────────────────────────────

/** Comparison operators for graph filter expressions. */
export type FilterOperator =
  | 'eq' | 'neq'
  | 'gt' | 'gte' | 'lt' | 'lte'
  | 'in' | 'not_in'
  | 'exists' | 'not_exists'
  | 'contains' | 'starts_with'
  | 'between' | 'relative_time' | 'threshold'

/** A single field-level filter predicate. */
export interface FilterExpression {
  field: string;          // dot-path e.g. 'risk.risk_score', 'economic.revenue'
  op: FilterOperator;
  value: unknown;         // scalar, array, or {from, to} range object
}

/** Boolean group combining expressions and nested groups. */
export interface FilterGroup {
  logic: 'AND' | 'OR' | 'NOT';
  expressions: Array<FilterExpression | FilterGroup>;
}

// ── Universal graph query request (Phase 4) ───────────────────────────────────

export interface UniversalGraphQueryRequest {
  tenant_id: string;
  anchors?: string[];                  // start vertex IDs for traversal
  node_types?: string[];               // VertexType strings to include
  edge_types?: string[];               // EdgeType strings to include
  layers?: RelationshipLayer[];        // restrict to these layers
  filter?: FilterGroup;                // boolean filter tree
  depth?: number;                      // BFS depth 1–6 (default 2)
  limit?: number;                      // max nodes 1–500 (default 100)
  cursor?: string;                     // opaque pagination cursor
  include_overlays?: string[];         // 'risk' | 'economic' | 'campaign' | 'geography' | 'consent'
  as_of?: string;                      // ISO8601 point-in-time (replay)
  include_evidence?: boolean;
  include_provenance?: boolean;
  include_clusters?: boolean;
  explain?: boolean;                   // return query plan instead of results
}

// ── Graph result metadata (Phase 4) ──────────────────────────────────────────

/** Attached to every graph query response for observability and pagination. */
export interface GraphResultMeta {
  truncated: boolean;
  truncation_reason?: string;          // 'node_budget' | 'edge_budget' | 'timeout' | 'depth'
  node_count: number;
  edge_count: number;
  execution_ms: number;
  query_id: string;
  budget_used: number;                 // 0–1 fraction of allowed budget consumed
  cursor?: string;                     // cursor for next page (null if final page)
  as_of?: string;                      // effective point-in-time if temporal query
  freshness_seconds?: number;          // seconds since graph data was last updated
  warnings: string[];                  // non-fatal issues (unknown overlays, partial data, etc.)
}
