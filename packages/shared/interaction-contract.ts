/**
 * DO NOT EDIT — generated from packages/shared/contracts/interaction-vocabulary.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const interactionVocabularyVersion = '1.0.0' as const;

/** Closed canonical interaction-type vocabulary. */
export const interactionTypes = [
  'click',
  'tap',
  'double_click',
  'long_press',
  'hover',
  'focus',
  'blur',
  'input',
  'select',
  'submit',
  'scroll',
  'drag',
  'drop',
  'copy',
  'share',
  'open',
  'close',
  'expand',
  'collapse',
  'approve',
  'reject',
  'sign',
  'connect',
  'disconnect',
  'execute',
  'retry',
  'backtrack',
  'navigate',
  'search',
  'filter',
  'sort',
  'download',
  'upload',
] as const;
export type InteractionType = typeof interactionTypes[number];

/** Custom interaction types must be namespaced as <namespace>.<name> using a registered namespace. Unregistered custom types stay in Bronze and are never promoted to stable Gold. */
export const interactionCustomNamespaces = [
  'tenant',
  'wallet',
  'dapp',
  'agent',
  'financial_rail',
] as const;
export type InteractionCustomNamespace = typeof interactionCustomNamespaces[number];

/** Canonical result state of an interaction. */
export const interactionResultStates = [
  'observed',
  'attempted',
  'pending',
  'succeeded',
  'failed',
  'cancelled',
  'abandoned',
  'rejected',
  'expired',
  'reverted',
  'confirmed',
  'settled',
] as const;
export type InteractionResultState = typeof interactionResultStates[number];

/** How strongly the recorded interaction is evidenced. */
export const interactionEvidenceBasis = [
  'client_observed',
  'server_observed',
  'provider_observed',
  'chain_observed',
  'reconciled',
  'imported',
  'derived',
  'probabilistic',
  'experiment_supported',
  'benchmark_only',
  'insufficient_evidence',
] as const;
export type InteractionEvidenceBasis = typeof interactionEvidenceBasis[number];

/** Who (or what) performed the interaction. */
export const interactionActorKinds = [
  'human',
  'agent',
  'service',
  'organization_member',
  'workspace',
  'wallet',
  'anonymous',
  'canonical_entity',
] as const;
export type InteractionActorKind = typeof interactionActorKinds[number];

/** Canonical interaction payload (Python twin: shared/product/models.py). */
export interface InteractionPayload {
  tenant_id: string;
  event_id: string;
  occurred_at: string;
  actor_kind?: string | null;
  canonical_entity_id?: string | null;
  anonymous_id?: string | null;
  user_id?: string | null;
  organization_id?: string | null;
  workspace_id?: string | null;
  agent_id?: string | null;
  wallet_id?: string | null;
  session_id?: string | null;
  device_id?: string | null;
  product_id?: string | null;
  product_area_id?: string | null;
  feature_id?: string | null;
  feature_version_id?: string | null;
  surface_id?: string | null;
  control_id?: string | null;
  interaction_type?: string | null;
  action_type?: string | null;
  result_state?: string | null;
  status_detail?: string | null;
  journey_id?: string | null;
  journey_step_id?: string | null;
  campaign_id?: string | null;
  experiment_id?: string | null;
  variant_id?: string | null;
  channel?: string | null;
  platform?: string | null;
  application_id?: string | null;
  application_version?: string | null;
  sdk_name?: string | null;
  sdk_version?: string | null;
  chain_id?: string | null;
  contract_address?: string | null;
  transaction_hash?: string | null;
  payment_rail?: string | null;
  payment_provider?: string | null;
  elapsed_ms?: number | null;
  visible_ms?: number | null;
  active_ms?: number | null;
  engaged_ms?: number | null;
  idle_ms?: number | null;
  network_wait_ms?: number | null;
  external_wait_ms?: number | null;
  provider_wait_ms?: number | null;
  execution_wait_ms?: number | null;
  scroll_pct?: number | null;
  viewable_pct?: number | null;
  completion_pct?: number | null;
  attempt_number?: number | null;
  friction_type?: string | null;
  error_code?: string | null;
  failure_category?: string | null;
  evidence_basis?: string | null;
  confidence?: number | null;
  consent_state?: string | null;
  mapping_version?: string | null;
  mapping_source?: string | null;
  mapping_confidence?: number | null;
  source_event_id?: string | null;
  correlation_id?: string | null;
}
