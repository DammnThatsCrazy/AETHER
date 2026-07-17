/**
 * DO NOT EDIT — generated from packages/shared/contracts/comparison-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const comparisonContractVersion = '1.0.0' as const;

/** What is being compared against what. */
export const comparisonModes = [
  'entity_vs_entity',
  'entity_vs_history',
  'entity_vs_cohort',
  'entity_vs_expected',
  'cohort_vs_cohort',
  'scenario_vs_current',
] as const;
export type ComparisonMode = typeof comparisonModes[number];

/** Where the baseline side of a comparison comes from. */
export const baselineTypes = [
  'entity',
  'historical',
  'rolling_history',
  'cohort',
  'policy',
  'predicted',
  'manual',
  'scenario',
] as const;
export type BaselineType = typeof baselineTypes[number];

/** How well the two sides could be aligned before comparing. */
export const alignmentOutcomes = [
  'aligned',
  'aligned_after_conversion',
  'partially_aligned',
  'not_comparable',
  'missing_unit',
  'missing_price',
  'stale_price',
  'grain_mismatch',
  'semantic_mismatch',
  'insufficient_provenance',
] as const;
export type AlignmentOutcome = typeof alignmentOutcomes[number];

/** Lifecycle states of a comparison run. */
export const comparisonRunStates = [
  'queued',
  'resolving',
  'collecting',
  'aligning',
  'computing',
  'scoring',
  'completed',
  'completed_degraded',
  'suppressed',
  'failed',
  'cancelled',
  'expired',
] as const;
export type ComparisonRunState = typeof comparisonRunStates[number];

/** Severity ladder for comparison findings. */
export const comparisonSeverities = ['info', 'low', 'medium', 'high', 'critical'] as const;
export type ComparisonSeverity = typeof comparisonSeverities[number];

/** Recommended handling of a comparison finding. */
export const comparisonDispositions = [
  'informational',
  'monitor',
  'investigate',
  'decide',
  'act',
  'suppressed',
  'insufficient_evidence',
] as const;
export type ComparisonDisposition = typeof comparisonDispositions[number];

/** How a finding's supporting facts are linked to the subject. */
export const factLinkageStates = [
  'linked',
  'deterministically_linked',
  'probabilistically_linked',
  'pending',
  'conflicted',
  'suppressed',
  'intentionally_unlinked',
  'orphaned',
  'revoked',
  'superseded',
] as const;
export type FactLinkageState = typeof factLinkageStates[number];

/** Strength ladder for causal claims attached to a finding. */
export const causalClaimLevels = [
  'observed',
  'correlated',
  'temporally_associated',
  'attributed',
  'inferred',
  'counterfactual_estimate',
  'causally_supported',
] as const;
export type CausalClaimLevel = typeof causalClaimLevels[number];

/** Dimensions along which two subjects can be compared. */
export const comparisonDimensions = [
  'identity',
  'relationships',
  'devices',
  'sessions',
  'behavior',
  'journeys',
  'campaigns',
  'attribution',
  'wallets',
  'economic_activity',
  'agent_behavior',
  'fraud_risk',
  'trust',
  'consent',
  'governance',
  'outcomes',
  'data_quality',
  'reconciliation',
  'geography',
  'temporal_activity',
] as const;
export type ComparisonDimension = typeof comparisonDimensions[number];

/** Components blended into a finding's materiality score. */
export const materialityComponents = [
  'economic_impact',
  'risk_impact',
  'policy_impact',
  'relationship_rarity',
  'historical_deviation',
  'cohort_deviation',
  'propagation_radius',
  'confidence',
  'freshness',
  'persistence',
  'urgency',
  'strategic_entity_weight',
  'reversibility',
  'data_quality',
] as const;
export type MaterialityComponent = typeof materialityComponents[number];

/** One side of a comparison (Python twin: services/intelligence/comparison/contracts.py). */
export interface ComparisonSubject {
  subject_type: string;
  subject_id: string;
  tenant_id?: string | null;
  label?: string | null;
  as_of?: string | null;
}

/** How the baseline side of a comparison is resolved (Python twin: services/intelligence/comparison/contracts.py). */
export interface BaselineSpec {
  baseline_type: string;
  subject?: ComparisonSubject | null;
  window_start?: string | null;
  window_end?: string | null;
  rolling_window_days?: number | null;
  cohort_definition_id?: string | null;
  policy_id?: string | null;
  scenario_id?: string | null;
}

/** Saved definition of a comparison (Python twin: services/intelligence/comparison/contracts.py). */
export interface ComparisonDefinition {
  definition_id: string;
  tenant_id: string;
  name?: string | null;
  mode: string;
  subject: ComparisonSubject;
  baseline: BaselineSpec;
  dimensions?: string[] | null;
  temporal_mode?: string | null;
  created_at?: string | null;
  created_by?: string | null;
  schema_version?: string | null;
}

/** One execution of a comparison definition (Python twin: services/intelligence/comparison/contracts.py). */
export interface ComparisonRun {
  run_id: string;
  definition_id: string;
  tenant_id: string;
  state: string;
  requested_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  as_of?: string | null;
  graph_watermark?: string | null;
  alignment_outcome?: string | null;
  finding_count?: number | null;
  degraded_reason?: string | null;
  error_code?: string | null;
  schema_version?: string | null;
}

/** One materiality-scored difference surfaced by a comparison run (Python twin: services/intelligence/comparison/contracts.py). */
export interface ComparisonFinding {
  id: string;
  comparison_run_id: string;
  tenant_id: string;
  finding_type: string;
  title?: string | null;
  narrative?: string | null;
  subject_refs?: string[] | null;
  dimension?: string | null;
  metric?: string | null;
  observed_value?: number | null;
  baseline_value?: number | null;
  delta?: number | null;
  normalized_delta?: number | null;
  direction?: string | null;
  severity?: string | null;
  materiality?: number | null;
  confidence?: number | null;
  evidence_status?: string | null;
  reconciliation_state?: string | null;
  first_observed_at?: string | null;
  last_observed_at?: string | null;
  persistence?: number | null;
  affected_entity_count?: number | null;
  economic_impact?: number | null;
  risk_impact?: number | null;
  policy_impact?: number | null;
  recommended_disposition?: string | null;
  recommendation_id?: string | null;
  investigation_id?: string | null;
  suppression_reason?: string | null;
}
