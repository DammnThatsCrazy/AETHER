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
