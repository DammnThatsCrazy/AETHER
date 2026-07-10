// =============================================================================
// Aether Interoperability Intelligence — canonical protocol-neutral contracts
// Read-only cross-network observation: providers, gateways, paths,
// applications, messages, intents, asset legs, security policy snapshots,
// verification/delivery actors, and reconciliation. No canonical name in this
// module depends on any single protocol's terminology; provider-native
// identifiers live in aliases and extension fields. Aether observes and
// correlates — it never relays, routes, retries, or recovers messages
// (`execution_by_aether: false`).
// =============================================================================

import type { EntityRef } from './entities';

export type InteropEvidenceClass =
  | 'fact'
  | 'computation'
  | 'inference'
  | 'insufficient_evidence';

export type InteropActorLayerClassification = 'H2H' | 'H2A' | 'A2H' | 'A2A' | 'DOMAIN_EXCLUDED';

export type InteropProviderKind =
  | 'layerzero_v2'
  | 'wormhole'
  | 'axelar'
  | 'chainlink_ccip'
  | 'hyperlane'
  | 'ibc'
  | 'debridge'
  | 'unknown';

export type InteropProtocolProduct = 'messaging' | 'asset_transfer' | 'intent' | 'query' | 'unknown';

export type InteropMessageStatus =
  | 'discovered'
  | 'source_pending'
  | 'source_confirmed'
  | 'verification_in_progress'
  | 'partially_verified'
  | 'verified'
  | 'delivery_pending'
  | 'delivery_attempted'
  | 'delivered'
  | 'executed'
  | 'settled'
  | 'failed'
  | 'verification_failed'
  | 'delivery_failed'
  | 'application_failed'
  | 'timed_out'
  | 'expired'
  | 'cancelled'
  | 'refunded'
  | 'reorged'
  | 'recovered'
  | 'unknown';

export type InteropTechnicalOutcome = 'success' | 'failure' | 'partial' | 'indeterminate' | 'unknown';

export type AssetLegType = 'debit' | 'lock' | 'burn' | 'release' | 'mint' | 'credit' | 'refund' | 'unknown';

export type VerificationModelKind =
  | 'external_verifier_set'
  | 'guardian_network'
  | 'validator_set'
  | 'light_client'
  | 'oracle_network'
  | 'optimistic'
  | 'unknown';

export type InteropImplementationStatus =
  | 'mocked_local'
  | 'scaffolded'
  | 'production_shaped'
  | 'credential_gated'
  | 'staging_validation_required'
  | 'provider_live'
  | 'degraded'
  | 'disabled'
  | 'deprecated';

export type DeliveryAttemptStatus =
  | 'requested'
  | 'submitted'
  | 'succeeded'
  | 'failed'
  | 'retrying'
  | 'abandoned'
  | 'unknown';

export type InteropGatewayRole = 'endpoint' | 'router' | 'bridge_contract' | 'channel' | 'unknown';
export type InteropTenantScope = 'public' | 'tenant';
export type InteropDataFreshness = 'live' | 'delayed' | 'backfill' | 'stale' | 'unknown';

export type InteropIntentStatus =
  | 'created'
  | 'quoted'
  | 'in_progress'
  | 'fulfilled'
  | 'settled'
  | 'refunded'
  | 'expired'
  | 'failed'
  | 'unknown';

export type InteropReconciliationStatus =
  | 'matched'
  | 'partial'
  | 'mismatched'
  | 'missing_destination'
  | 'missing_source'
  | 'provider_disagreement'
  | 'pending_finality'
  | 'unresolved'
  | 'unknown';

// -----------------------------------------------------------------------------
// Canonical lifecycle FSM — the single source of truth.
// Backend Python mirrors this table and a parity test regex-parses this const;
// keep the `state: [...]` one-entry-per-line formatting.
// -----------------------------------------------------------------------------

export const INTEROP_LEGAL_TRANSITIONS = {
  discovered: ['source_pending', 'source_confirmed', 'failed', 'unknown'],
  source_pending: ['source_confirmed', 'reorged', 'failed', 'expired', 'unknown'],
  source_confirmed: ['verification_in_progress', 'partially_verified', 'verified', 'delivered', 'reorged', 'timed_out', 'failed', 'unknown'],
  verification_in_progress: ['partially_verified', 'verified', 'verification_failed', 'timed_out', 'reorged', 'unknown'],
  partially_verified: ['verified', 'verification_failed', 'timed_out', 'reorged', 'unknown'],
  verified: ['delivery_pending', 'delivery_attempted', 'delivered', 'delivery_failed', 'timed_out', 'reorged', 'unknown'],
  delivery_pending: ['delivery_attempted', 'delivered', 'delivery_failed', 'timed_out', 'cancelled', 'unknown'],
  delivery_attempted: ['delivered', 'delivery_failed', 'timed_out', 'unknown'],
  delivered: ['executed', 'application_failed', 'settled', 'unknown'],
  executed: ['settled', 'unknown'],
  settled: [],
  failed: ['recovered', 'refunded'],
  verification_failed: ['verification_in_progress', 'failed', 'recovered', 'refunded'],
  delivery_failed: ['delivery_pending', 'delivery_attempted', 'failed', 'recovered', 'refunded'],
  application_failed: ['recovered', 'refunded', 'failed'],
  timed_out: ['recovered', 'refunded', 'failed', 'delivered'],
  expired: ['refunded'],
  cancelled: [],
  refunded: [],
  reorged: ['discovered', 'source_pending', 'source_confirmed', 'failed'],
  recovered: ['delivered', 'executed', 'settled'],
  unknown: ['discovered', 'source_pending', 'source_confirmed', 'verification_in_progress', 'verified', 'delivered', 'executed', 'settled', 'failed', 'timed_out'],
} as const satisfies Record<InteropMessageStatus, readonly InteropMessageStatus[]>;

export const INTEROP_TERMINAL_STATES: readonly InteropMessageStatus[] = [
  'settled', 'cancelled', 'refunded',
] as const;

export function isLegalTransition(from: InteropMessageStatus, to: InteropMessageStatus): boolean {
  const allowed: readonly InteropMessageStatus[] | undefined = INTEROP_LEGAL_TRANSITIONS[from];
  return Array.isArray(allowed) && (allowed as readonly string[]).includes(to);
}

// -----------------------------------------------------------------------------
// Envelope
// -----------------------------------------------------------------------------

export interface InteropEvidenceEnvelope {
  evidence_class: InteropEvidenceClass;
  source_refs: string[];
  source_event_ids: string[];
  confidence: string;
  valid_time: string;
  recorded_time: string;
  explanation: string;
}

/**
 * Tenant-scoped envelope. Public-scope rows (protocol topology, public
 * message facts) use the sentinel tenant id 'public' together with
 * `tenant_scope: 'public'` on records that carry that field.
 */
export interface InteropTenantScoped {
  tenant_id: string;
  idempotency_key: string;
  evidence: InteropEvidenceEnvelope;
  execution_by_aether: false;
}

// -----------------------------------------------------------------------------
// Reference entities (global, provider-neutral)
// -----------------------------------------------------------------------------

export interface InteropProvider {
  provider_id: string;
  provider_kind: InteropProviderKind;
  display_name: string;
  protocol_products: InteropProtocolProduct[];
  supported_versions: string[];
  implementation_status: InteropImplementationStatus;
  capabilities: string[];
  global_reference: true;
}

export interface InteropGateway {
  gateway_id: string;
  provider_id: string;
  network_id: string;
  native_chain_id: string;
  provider_network_id?: string;
  gateway_address: string;
  gateway_role: InteropGatewayRole;
  active: boolean;
  global_reference: true;
}

export interface InteropPath {
  path_id: string;
  provider_id: string;
  source_network_id: string;
  destination_network_id: string;
  source_gateway_id?: string;
  destination_gateway_id?: string;
  first_seen_at: string;
  last_seen_at?: string;
  global_reference: true;
}

export interface InteropApplication {
  application_id: string;
  network_id: string;
  contract_address: string;
  display_name?: string;
  owner_entity_ref?: EntityRef;
  provider_ids: string[];
  first_seen_at: string;
  global_reference: true;
}

export interface VerificationActor {
  verification_actor_id: string;
  provider_id: string;
  display_name?: string;
  actor_address?: string;
  networks: string[];
  actor_role: 'required' | 'optional' | 'unknown';
  global_reference: true;
}

export interface DeliveryActor {
  delivery_actor_id: string;
  provider_id: string;
  display_name?: string;
  actor_address?: string;
  networks: string[];
  global_reference: true;
}

// -----------------------------------------------------------------------------
// Message plane
// -----------------------------------------------------------------------------

export interface InteropMessageAlias {
  alias_type: string;
  alias_value: string;
  canonical: boolean;
}

export interface InteropEndpointRef {
  network_id: string;
  native_chain_id: string;
  provider_network_id?: string;
  gateway_id?: string;
  application_id?: string;
  transaction_hash?: string;
  block_number?: string;
  block_hash?: string;
  log_index?: number;
}

export interface InteropMessage extends InteropTenantScoped {
  interop_message_id: string;
  tenant_scope: InteropTenantScope;
  schema_version: string;
  provider_id: string;
  provider_kind: InteropProviderKind;
  protocol_product: InteropProtocolProduct;
  correlation_key: string;
  provider_message_refs: InteropMessageAlias[];
  source: InteropEndpointRef;
  destination?: InteropEndpointRef;
  path_id: string;
  sequence?: string;
  payload_hash?: string;
  payload_type?: string;
  status: InteropMessageStatus;
  provider_native_status?: string;
  technical_outcome: InteropTechnicalOutcome;
  source_observed_at?: string;
  source_confirmed_at?: string;
  verified_at?: string;
  delivered_at?: string;
  executed_at?: string;
  settled_at?: string;
  terminal_at?: string;
  security_snapshot_id?: string;
  intent_id?: string;
  asset_leg_ids: string[];
  delivery_attempt_ids: string[];
  fee_total_decimal?: string;
  fee_asset_id?: string;
  confidence: string;
  data_freshness: InteropDataFreshness;
  provider_extension?: Record<string, unknown>;
}

export interface InteropLifecycleTransition extends InteropTenantScoped {
  transition_id: string;
  interop_message_id: string;
  from_status: InteropMessageStatus;
  to_status: InteropMessageStatus;
  provider_native_stage?: string;
  observed_at: string;
  evidence_ref?: string;
}

// -----------------------------------------------------------------------------
// Asset and intent plane
// -----------------------------------------------------------------------------

export interface InteropIntent extends InteropTenantScoped {
  intent_id: string;
  provider_id: string;
  initiator_entity_ref?: EntityRef;
  initiator_address?: string;
  source_network_id: string;
  destination_network_id: string;
  requested_asset_id?: string;
  requested_amount_decimal?: string;
  status: InteropIntentStatus;
  created_at: string;
  resolved_at?: string;
}

export interface InteropAssetLeg extends InteropTenantScoped {
  asset_leg_id: string;
  interop_message_id?: string;
  intent_id?: string;
  leg_type: AssetLegType;
  network_id: string;
  asset_id?: string;
  token_address?: string;
  amount_atomic?: string;
  amount_decimal: string;
  from_address?: string;
  to_address?: string;
  transaction_hash?: string;
  observed_at: string;
}

// -----------------------------------------------------------------------------
// Security and infrastructure plane
// -----------------------------------------------------------------------------

export interface SecurityPolicySnapshot extends InteropTenantScoped {
  security_snapshot_id: string;
  provider_id: string;
  path_id: string;
  effective_block_number?: string;
  verification_model: VerificationModelKind;
  required_verifier_ids: string[];
  optional_verifier_ids: string[];
  optional_threshold?: number;
  confirmations_required?: number;
  delivery_actor_ids: string[];
  module_addresses: Record<string, string>;
  content_hash: string;
  captured_at: string;
}

export interface DeliveryAttempt extends InteropTenantScoped {
  delivery_attempt_id: string;
  interop_message_id: string;
  attempt_number: number;
  status: DeliveryAttemptStatus;
  delivery_actor_id?: string;
  transaction_hash?: string;
  error_class?: string;
  observed_at: string;
}

export interface InteropProviderCheckpoint extends InteropTenantScoped {
  checkpoint_id: string;
  provider_id: string;
  network_id: string;
  last_scanned_block: string;
  confirmed_block: string;
  advanced_at: string;
}

export interface InteropReconciliationRecord extends InteropTenantScoped {
  reconciliation_id: string;
  interop_message_id?: string;
  correlation_key?: string;
  status: InteropReconciliationStatus;
  sources_compared: string[];
  difference_note?: string;
  resolved_at?: string;
}

export const INTEROP_ENTITY_KINDS = [
  'interop_provider',
  'interop_gateway',
  'interop_path',
  'interop_application',
  'interop_message',
  'interop_lifecycle_transition',
  'interop_intent',
  'interop_asset_leg',
  'security_policy_snapshot',
  'verification_actor',
  'delivery_actor',
  'delivery_attempt',
  'interop_provider_checkpoint',
  'interop_reconciliation_record',
] as const;

export type InteropEntityKind = typeof INTEROP_ENTITY_KINDS[number];

export const INTEROP_ACTOR_EDGE_LAYER_MAP = {
  INITIATED_CROSS_CHAIN_WITH: 'H2H', SHARES_APPLICATION_WITH: 'H2H',
  REQUESTED_DELIVERY_FROM: 'H2A', AUTHORIZED_INTEROP_SPEND: 'H2A',
  RELAYED_FOR: 'A2H', REPORTS_DELIVERY_TO: 'A2H',
  COORDINATES_INTENT_WITH: 'A2A', VERIFIES_FOR: 'A2A',
} as const satisfies Record<string, Exclude<InteropActorLayerClassification, 'DOMAIN_EXCLUDED'>>;

export const INTEROP_DOMAIN_EDGE_LAYER_MAP = {
  SENT_VIA_PATH: 'DOMAIN_EXCLUDED', DELIVERED_VIA_GATEWAY: 'DOMAIN_EXCLUDED',
  VERIFIED_BY: 'DOMAIN_EXCLUDED', ROUTES_THROUGH: 'DOMAIN_EXCLUDED',
  CONNECTS_CHAIN: 'DOMAIN_EXCLUDED', SECURED_BY_POLICY: 'DOMAIN_EXCLUDED',
  USES_PROVIDER: 'DOMAIN_EXCLUDED', ORIGINATES_FROM_APP: 'DOMAIN_EXCLUDED',
  DELIVERS_TO_APP: 'DOMAIN_EXCLUDED', HAS_ASSET_LEG: 'DOMAIN_EXCLUDED',
  HAS_SECURITY_SNAPSHOT: 'DOMAIN_EXCLUDED', FULFILLED_INTENT: 'DOMAIN_EXCLUDED',
} as const satisfies Record<string, 'DOMAIN_EXCLUDED'>;

export const INTEROP_EDGE_LAYER_MAP = {
  ...INTEROP_ACTOR_EDGE_LAYER_MAP,
  ...INTEROP_DOMAIN_EDGE_LAYER_MAP,
} as const;

// -----------------------------------------------------------------------------
// Runtime enum arrays
// -----------------------------------------------------------------------------

export const INTEROP_MESSAGE_STATUSES: readonly InteropMessageStatus[] = [
  'discovered', 'source_pending', 'source_confirmed', 'verification_in_progress',
  'partially_verified', 'verified', 'delivery_pending', 'delivery_attempted', 'delivered',
  'executed', 'settled', 'failed', 'verification_failed', 'delivery_failed',
  'application_failed', 'timed_out', 'expired', 'cancelled', 'refunded', 'reorged',
  'recovered', 'unknown',
] as const;

export const INTEROP_PROVIDER_KINDS: readonly InteropProviderKind[] = [
  'layerzero_v2', 'wormhole', 'axelar', 'chainlink_ccip', 'hyperlane', 'ibc', 'debridge', 'unknown',
] as const;

export const ASSET_LEG_TYPES: readonly AssetLegType[] = [
  'debit', 'lock', 'burn', 'release', 'mint', 'credit', 'refund', 'unknown',
] as const;

export const INTEROP_IMPLEMENTATION_STATUSES: readonly InteropImplementationStatus[] = [
  'mocked_local', 'scaffolded', 'production_shaped', 'credential_gated',
  'staging_validation_required', 'provider_live', 'degraded', 'disabled', 'deprecated',
] as const;

export const VERIFICATION_MODEL_KINDS: readonly VerificationModelKind[] = [
  'external_verifier_set', 'guardian_network', 'validator_set', 'light_client',
  'oracle_network', 'optimistic', 'unknown',
] as const;

// -----------------------------------------------------------------------------
// Validation
// -----------------------------------------------------------------------------

export interface InteropValidationResult {
  valid: boolean;
  errors: string[];
}

const DECIMAL_STRING_RE = /^-?\d+(\.\d+)?$/;

export function isInteropDecimalString(value: unknown): value is string {
  return typeof value === 'string' && DECIMAL_STRING_RE.test(value);
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function requireNonEmptyString(
  obj: Record<string, unknown>, field: string, errors: string[],
): void {
  const v = obj[field];
  if (typeof v !== 'string' || v.length === 0) {
    errors.push(`${field} must be a non-empty string`);
  }
}

function requireObservationOnly(obj: Record<string, unknown>, errors: string[]): void {
  if (obj.execution_by_aether !== false) {
    errors.push('execution_by_aether must be exactly false — Aether never relays or executes');
  }
}

export function validateInteropMessage(input: unknown): InteropValidationResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { valid: false, errors: ['input must be an object'] };
  }
  requireNonEmptyString(input, 'interop_message_id', errors);
  requireNonEmptyString(input, 'tenant_id', errors);
  requireNonEmptyString(input, 'idempotency_key', errors);
  requireNonEmptyString(input, 'schema_version', errors);
  requireNonEmptyString(input, 'provider_id', errors);
  requireNonEmptyString(input, 'correlation_key', errors);
  requireNonEmptyString(input, 'path_id', errors);
  requireObservationOnly(input, errors);
  if (input.tenant_scope !== 'public' && input.tenant_scope !== 'tenant') {
    errors.push("tenant_scope must be 'public' or 'tenant'");
  }
  if (!INTEROP_MESSAGE_STATUSES.includes(input.status as InteropMessageStatus)) {
    errors.push('status must be a known InteropMessageStatus');
  }
  if (!INTEROP_PROVIDER_KINDS.includes(input.provider_kind as InteropProviderKind)) {
    errors.push('provider_kind must be a known InteropProviderKind');
  }
  if (!isRecord(input.source)) {
    errors.push('source endpoint reference is required');
  }
  if (!Array.isArray(input.asset_leg_ids)) {
    errors.push('asset_leg_ids must be an array');
  }
  if (!Array.isArray(input.delivery_attempt_ids)) {
    errors.push('delivery_attempt_ids must be an array');
  }
  if (input.fee_total_decimal !== undefined && !isInteropDecimalString(input.fee_total_decimal)) {
    errors.push('fee_total_decimal must be a decimal string when present');
  }
  return { valid: errors.length === 0, errors };
}

export function validateSecurityPolicySnapshot(input: unknown): InteropValidationResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { valid: false, errors: ['input must be an object'] };
  }
  requireNonEmptyString(input, 'security_snapshot_id', errors);
  requireNonEmptyString(input, 'provider_id', errors);
  requireNonEmptyString(input, 'path_id', errors);
  requireNonEmptyString(input, 'content_hash', errors);
  requireNonEmptyString(input, 'captured_at', errors);
  requireObservationOnly(input, errors);
  if (!VERIFICATION_MODEL_KINDS.includes(input.verification_model as VerificationModelKind)) {
    errors.push('verification_model must be a known VerificationModelKind');
  }
  if (!Array.isArray(input.required_verifier_ids) || !Array.isArray(input.optional_verifier_ids)) {
    errors.push('required_verifier_ids and optional_verifier_ids must be arrays');
  }
  if (!Array.isArray(input.delivery_actor_ids)) {
    errors.push('delivery_actor_ids must be an array');
  }
  return { valid: errors.length === 0, errors };
}

export function validateAssetLeg(input: unknown): InteropValidationResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { valid: false, errors: ['input must be an object'] };
  }
  requireNonEmptyString(input, 'asset_leg_id', errors);
  requireNonEmptyString(input, 'network_id', errors);
  requireNonEmptyString(input, 'observed_at', errors);
  requireObservationOnly(input, errors);
  if (!ASSET_LEG_TYPES.includes(input.leg_type as AssetLegType)) {
    errors.push('leg_type must be a known AssetLegType');
  }
  if (!isInteropDecimalString(input.amount_decimal)) {
    errors.push('amount_decimal must be a decimal string');
  }
  if (input.amount_atomic !== undefined && !isInteropDecimalString(input.amount_atomic)) {
    errors.push('amount_atomic must be a decimal string when present');
  }
  return { valid: errors.length === 0, errors };
}

export function validateLifecycleTransition(input: unknown): InteropValidationResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { valid: false, errors: ['input must be an object'] };
  }
  requireNonEmptyString(input, 'transition_id', errors);
  requireNonEmptyString(input, 'interop_message_id', errors);
  requireNonEmptyString(input, 'observed_at', errors);
  requireObservationOnly(input, errors);
  const fromStatus = input.from_status as InteropMessageStatus;
  const toStatus = input.to_status as InteropMessageStatus;
  if (!INTEROP_MESSAGE_STATUSES.includes(fromStatus)) {
    errors.push('from_status must be a known InteropMessageStatus');
  }
  if (!INTEROP_MESSAGE_STATUSES.includes(toStatus)) {
    errors.push('to_status must be a known InteropMessageStatus');
  }
  if (
    INTEROP_MESSAGE_STATUSES.includes(fromStatus)
    && INTEROP_MESSAGE_STATUSES.includes(toStatus)
    && !isLegalTransition(fromStatus, toStatus)
  ) {
    errors.push(`illegal lifecycle transition: ${fromStatus} -> ${toStatus}`);
  }
  return { valid: errors.length === 0, errors };
}
