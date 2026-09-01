/**
 * DO NOT EDIT — generated from packages/shared/contracts/graph-mutation-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const graphMutationContractVersion = '1.0.0' as const;

/** Every way the graph plane may change (append-only ledger vocabulary). */
export const graphMutationTypes = [
  'node_created',
  'node_versioned',
  'node_tombstoned',
  'node_restored',
  'edge_created',
  'edge_versioned',
  'edge_expired',
  'edge_tombstoned',
  'identity_merged',
  'identity_split',
  'identity_redirected',
  'cluster_created',
  'cluster_member_added',
  'cluster_member_removed',
  'cluster_merged',
  'cluster_split',
  'score_versioned',
  'attribution_versioned',
  'policy_state_changed',
  'consent_state_changed',
  'model_version_changed',
  'projection_rebuilt',
  'historical_correction_applied',
] as const;
export type GraphMutationType = typeof graphMutationTypes[number];

/** Who (or what) performed a graph mutation. */
export const mutationActorKinds = [
  'service',
  'human',
  'agent',
  'system',
  'provider',
  'import',
] as const;
export type MutationActorKind = typeof mutationActorKinds[number];

/** Strength of the causal claim attached to a mutation. */
export const mutationCausalityClasses = [
  'observed_sequence',
  'declared_reason',
  'policy_cause',
  'authorized_delegation',
  'attributed_influence',
  'inferred_influence',
  'direct_cause',
  'correlation_only',
  'unknown',
] as const;
export type MutationCausalityClass = typeof mutationCausalityClasses[number];

/** How a mutation (or decision) is explained to reviewers. */
export const mutationExplanationTypes = [
  'observed_trigger',
  'declared_reason',
  'policy_cause',
  'authorized_delegation',
  'attributed_influence',
  'inferred_influence',
  'experimental_incrementality',
  'direct_cause',
  'correlation_only',
  'unknown',
] as const;
export type MutationExplanationType = typeof mutationExplanationTypes[number];

/** One append-only graph mutation; bitemporal field names match BITEMPORAL_EDGE_PROPERTIES (Python twin: shared/graph/mutation_models.py). */
export interface MutationRecord {
  mutation_id: string;
  tenant_id: string;
  aggregate_type: 'node' | 'edge' | 'cluster' | 'score';
  aggregate_id: string;
  operation: string;
  actor_kind?: string | null;
  actor_id?: string | null;
  subject_kind?: string | null;
  subject_id?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  recorded_at: string;
  superseded_at?: string | null;
  correlation_id?: string | null;
  causation_id?: string | null;
  source_event_id?: string | null;
  idempotency_key?: string | null;
  reason_code?: string | null;
  causality_class?: string | null;
  confidence?: number | null;
  evidence_refs?: string[] | null;
  model_refs?: string[] | null;
  policy_refs?: string[] | null;
  consent_refs?: string[] | null;
  before_version_id?: string | null;
  after_version_id?: string | null;
  change_set_id?: string | null;
  rights_decision_id?: string | null;
  rights_envelope_id?: string | null;
  rights_policy_set_ref?: string | null;
  rights_lineage_set_hash?: string | null;
  rights_source_grant_refs?: string[] | null;
  schema_version?: string | null;
}

/** Point-in-time decision snapshot pinned to fact/model/policy versions (Python twin: DecisionRecord in shared/graph/mutation_models.py). */
export interface GraphDecisionRecord {
  decision_id: string;
  tenant_id: string;
  decision_type: string;
  subject_refs?: string[] | null;
  input_fact_versions?: Record<string, string> | null;
  graph_watermark?: string | null;
  model_versions?: Record<string, string> | null;
  policy_versions?: Record<string, string> | null;
  decision?: string | null;
  confidence?: number | null;
  human_override?: boolean | null;
  action_observed?: boolean | null;
  outcome_refs?: string[] | null;
  valid_at?: string | null;
  recorded_at?: string | null;
}

/** Digest of graph deltas between two refs (Python twin: shared/graph/mutation_models.py). */
export interface ChangeSet {
  change_set_id: string;
  tenant_id: string;
  scope_type?: string | null;
  scope_id?: string | null;
  baseline_ref?: string | null;
  target_ref?: string | null;
  added_node_count?: number | null;
  removed_node_count?: number | null;
  changed_edge_count?: number | null;
  digest?: string | null;
}
