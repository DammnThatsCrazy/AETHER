// =============================================================================
// Aether Stablecoin Intelligence — canonical bounded-domain contracts
// Read-only stablecoin economic observation: canonical asset + deployment
// identity, observations, valuation, support assertions, finality, flows,
// and reconciliation. Aether observes and verifies — it never executes,
// custodies, mints, redeems, or routes funds (`execution_by_aether: false`).
// =============================================================================

import type { EntityRef } from './entities';

export type StablecoinEvidenceClass =
  | 'fact'
  | 'computation'
  | 'inference'
  | 'insufficient_evidence';

export type StablecoinActorLayerClassification = 'H2H' | 'H2A' | 'A2H' | 'A2A' | 'DOMAIN_EXCLUDED';

export type StablecoinObservationType =
  | 'transfer'
  | 'payment'
  | 'mint'
  | 'burn'
  | 'bridge_outbound'
  | 'bridge_inbound'
  | 'swap'
  | 'x402_settlement'
  | 'treasury_movement'
  | 'payout'
  | 'venue_deposit'
  | 'venue_withdrawal'
  | 'unknown';

export type PegStatus = 'on_peg' | 'minor_deviation' | 'depegged' | 'recovering' | 'unknown';

export type StablecoinFinalityStatus =
  | 'provisional'
  | 'confirmed'
  | 'finalized'
  | 'reorged'
  | 'corrected'
  | 'unknown';

export type SupportAssertionStatus =
  | 'announced'
  | 'configured'
  | 'observed'
  | 'production_active'
  | 'degraded'
  | 'suspended'
  | 'retired'
  | 'unknown';

export type StablecoinCapability =
  | 'send'
  | 'receive'
  | 'hold'
  | 'deposit'
  | 'withdraw'
  | 'accept_payment'
  | 'settle'
  | 'refund'
  | 'swap'
  | 'bridge'
  | 'mint'
  | 'redeem'
  | 'collateral'
  | 'rewards'
  | 'x402'
  | 'treasury'
  | 'unknown';

export type StablecoinBackingModel =
  | 'fiat_reserve'
  | 'crypto_collateralized'
  | 'algorithmic'
  | 'commodity_backed'
  | 'hybrid'
  | 'unknown';

export type StablecoinDeploymentType =
  | 'canonical'
  | 'bridged'
  | 'wrapped'
  | 'synthetic'
  | 'deprecated'
  | 'counterfeit_suspected'
  | 'unknown';

export type StablecoinReconciliationStatus =
  | 'matched'
  | 'partial'
  | 'mismatched'
  | 'duplicate'
  | 'missing_onchain'
  | 'missing_tenant_event'
  | 'pending_finality'
  | 'reverted'
  | 'unresolved'
  | 'unknown';

export type StablecoinAssetStatus = 'active' | 'deprecated' | 'suspended' | 'unknown';
export type StablecoinEnvironment = 'production' | 'sandbox' | 'testnet' | 'unknown';
export type StablecoinFlowDirection = 'inflow' | 'outflow' | 'net' | 'internal';

export interface StablecoinEvidenceEnvelope {
  evidence_class: StablecoinEvidenceClass;
  source_refs: string[];
  source_event_ids: string[];
  confidence: string;
  valid_time: string;
  recorded_time: string;
  explanation: string;
}

export interface StablecoinTenantScoped {
  tenant_id: string;
  idempotency_key: string;
  evidence: StablecoinEvidenceEnvelope;
  execution_by_aether: false;
}

export interface StablecoinAssetCanonical {
  canonical_asset_id: string;
  symbol: string;
  name: string;
  issuer_entity_id?: string;
  issuer_name?: string;
  backing_model: StablecoinBackingModel;
  pegged_to: string;
  asset_status: StablecoinAssetStatus;
  risk_classification?: string;
  first_seen_at: string;
  global_reference: true;
}

export interface StablecoinDeployment {
  deployment_id: string;
  canonical_asset_id: string;
  chain_id: string;
  network: string;
  token_standard: string;
  contract_or_mint: string;
  decimals: number;
  deployment_type: StablecoinDeploymentType;
  bridge_origin_deployment_id?: string;
  issuer_verified: boolean;
  active: boolean;
  testnet: boolean;
  first_seen_at: string;
  last_seen_at?: string;
  deprecated_at?: string;
  global_reference: true;
}

export interface StablecoinObservation extends StablecoinTenantScoped {
  observation_id: string;
  observation_type: StablecoinObservationType;
  deployment_id: string;
  canonical_asset_id: string;
  chain_id: string;
  network?: string;
  block_number?: string;
  block_hash?: string;
  transaction_hash: string;
  log_or_instruction_index?: number;
  amount_atomic: string;
  amount_decimal: string;
  from_address?: string;
  to_address?: string;
  from_wallet_id?: string;
  to_wallet_id?: string;
  from_entity_ref?: EntityRef;
  to_entity_ref?: EntityRef;
  counterparty_class?: string;
  protocol_id?: string;
  merchant_id?: string;
  facilitator_id?: string;
  agent_id?: string;
  campaign_id?: string;
  journey_id?: string;
  session_id?: string;
  finality_status: StablecoinFinalityStatus;
  finalized_at?: string;
  classification_confidence: string;
  observed_at: string;
  ingested_at: string;
}

export interface StablecoinValuationSnapshot extends StablecoinTenantScoped {
  valuation_id: string;
  deployment_id: string;
  price_usd: string;
  peg_deviation_bps: string;
  peg_status: PegStatus;
  source: string;
  source_record_id?: string;
  observed_at: string;
  stale_after?: string;
}

export interface StablecoinSupportAssertion extends StablecoinTenantScoped {
  assertion_id: string;
  subject_entity_ref: EntityRef;
  deployment_id: string;
  capability: StablecoinCapability;
  support_status: SupportAssertionStatus;
  environment: StablecoinEnvironment;
  evidence_type: string;
  evidence_reference?: string;
  first_observed_at?: string;
  last_observed_at?: string;
  successful_observation_count: number;
  failed_observation_count: number;
  confidence: string;
  expires_at?: string;
}

export interface StablecoinFlowAggregate extends StablecoinTenantScoped {
  flow_aggregate_id: string;
  canonical_asset_id: string;
  deployment_id?: string;
  chain_id?: string;
  window_start: string;
  window_end: string;
  direction: StablecoinFlowDirection;
  gross_transfer_volume_decimal: string;
  finalized_payment_volume_decimal: string;
  transfer_count: number;
  unique_senders: number;
  unique_recipients: number;
  metric_version: string;
  materialized_at: string;
}

export interface StablecoinReconciliationRecord extends StablecoinTenantScoped {
  reconciliation_id: string;
  observation_id?: string;
  transaction_hash?: string;
  status: StablecoinReconciliationStatus;
  expected_amount_decimal?: string;
  observed_amount_decimal?: string;
  difference_decimal?: string;
  sources_compared: string[];
  resolved_at?: string;
  resolution_note?: string;
}

export interface StablecoinFinalityCheckpoint extends StablecoinTenantScoped {
  checkpoint_id: string;
  chain_id: string;
  confirmed_block_number: string;
  confirmed_block_hash?: string;
  confirmation_horizon: number;
  advanced_at: string;
}

export const STABLECOIN_ENTITY_KINDS = [
  'stablecoin_asset',
  'stablecoin_deployment',
  'stablecoin_observation',
  'stablecoin_valuation_snapshot',
  'stablecoin_support_assertion',
  'stablecoin_flow_aggregate',
  'stablecoin_reconciliation_record',
  'stablecoin_finality_checkpoint',
] as const;

export type StablecoinEntityKind = typeof STABLECOIN_ENTITY_KINDS[number];

export const STABLECOIN_ACTOR_EDGE_LAYER_MAP = {
  SENT_STABLECOIN_TO: 'H2H', PAID_MERCHANT: 'H2H', SHARES_TREASURY_WITH: 'H2H',
  AUTHORIZED_STABLECOIN_SPEND: 'H2A', FUNDS_AGENT_WALLET: 'H2A',
  REQUESTED_STABLECOIN_PAYMENT: 'A2H', REPORTS_FLOW_TO: 'A2H',
  SETTLES_WITH_AGENT: 'A2A', ROUTES_PAYMENT_TO: 'A2A',
} as const satisfies Record<string, Exclude<StablecoinActorLayerClassification, 'DOMAIN_EXCLUDED'>>;

export const STABLECOIN_DOMAIN_EDGE_LAYER_MAP = {
  TRANSFERRED_STABLECOIN: 'DOMAIN_EXCLUDED', BRIDGED_STABLECOIN: 'DOMAIN_EXCLUDED',
  SWAPPED_STABLECOIN: 'DOMAIN_EXCLUDED', ISSUED_BY: 'DOMAIN_EXCLUDED',
  DEPLOYED_ON_CHAIN: 'DOMAIN_EXCLUDED', SUPPORTS_ASSET: 'DOMAIN_EXCLUDED',
  PEGGED_TO: 'DOMAIN_EXCLUDED', VALUED_AT: 'DOMAIN_EXCLUDED',
  RECONCILED_WITH: 'DOMAIN_EXCLUDED',
} as const satisfies Record<string, 'DOMAIN_EXCLUDED'>;

export const STABLECOIN_EDGE_LAYER_MAP = {
  ...STABLECOIN_ACTOR_EDGE_LAYER_MAP,
  ...STABLECOIN_DOMAIN_EDGE_LAYER_MAP,
} as const;

// -----------------------------------------------------------------------------
// Runtime enum arrays (used by validators and by backend parity tests)
// -----------------------------------------------------------------------------

export const STABLECOIN_OBSERVATION_TYPES: readonly StablecoinObservationType[] = [
  'transfer', 'payment', 'mint', 'burn', 'bridge_outbound', 'bridge_inbound', 'swap',
  'x402_settlement', 'treasury_movement', 'payout', 'venue_deposit', 'venue_withdrawal', 'unknown',
] as const;

export const STABLECOIN_FINALITY_STATUSES: readonly StablecoinFinalityStatus[] = [
  'provisional', 'confirmed', 'finalized', 'reorged', 'corrected', 'unknown',
] as const;

export const SUPPORT_ASSERTION_STATUSES: readonly SupportAssertionStatus[] = [
  'announced', 'configured', 'observed', 'production_active', 'degraded', 'suspended', 'retired', 'unknown',
] as const;

export const STABLECOIN_CAPABILITIES: readonly StablecoinCapability[] = [
  'send', 'receive', 'hold', 'deposit', 'withdraw', 'accept_payment', 'settle', 'refund',
  'swap', 'bridge', 'mint', 'redeem', 'collateral', 'rewards', 'x402', 'treasury', 'unknown',
] as const;

export const PEG_STATUSES: readonly PegStatus[] = [
  'on_peg', 'minor_deviation', 'depegged', 'recovering', 'unknown',
] as const;

export const STABLECOIN_DEPLOYMENT_TYPES: readonly StablecoinDeploymentType[] = [
  'canonical', 'bridged', 'wrapped', 'synthetic', 'deprecated', 'counterfeit_suspected', 'unknown',
] as const;

// -----------------------------------------------------------------------------
// Validation
// -----------------------------------------------------------------------------

export interface StablecoinValidationResult {
  valid: boolean;
  errors: string[];
}

const DECIMAL_STRING_RE = /^-?\d+(\.\d+)?$/;

/** Canonical financial values travel as fixed-precision decimal strings — never binary floats. */
export function isDecimalString(value: unknown): value is string {
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
    errors.push('execution_by_aether must be exactly false — Aether never executes');
  }
}

export function validateStablecoinObservation(input: unknown): StablecoinValidationResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { valid: false, errors: ['input must be an object'] };
  }
  requireNonEmptyString(input, 'observation_id', errors);
  requireNonEmptyString(input, 'tenant_id', errors);
  requireNonEmptyString(input, 'idempotency_key', errors);
  requireNonEmptyString(input, 'deployment_id', errors);
  requireNonEmptyString(input, 'canonical_asset_id', errors);
  requireNonEmptyString(input, 'chain_id', errors);
  requireNonEmptyString(input, 'transaction_hash', errors);
  requireNonEmptyString(input, 'observed_at', errors);
  requireNonEmptyString(input, 'ingested_at', errors);
  requireObservationOnly(input, errors);
  if (!STABLECOIN_OBSERVATION_TYPES.includes(input.observation_type as StablecoinObservationType)) {
    errors.push(`observation_type must be one of ${STABLECOIN_OBSERVATION_TYPES.join(', ')}`);
  }
  if (!STABLECOIN_FINALITY_STATUSES.includes(input.finality_status as StablecoinFinalityStatus)) {
    errors.push(`finality_status must be one of ${STABLECOIN_FINALITY_STATUSES.join(', ')}`);
  }
  if (!isDecimalString(input.amount_atomic)) {
    errors.push('amount_atomic must be a decimal string');
  }
  if (!isDecimalString(input.amount_decimal)) {
    errors.push('amount_decimal must be a decimal string');
  }
  if (!isDecimalString(input.classification_confidence)) {
    errors.push('classification_confidence must be a decimal string');
  }
  return { valid: errors.length === 0, errors };
}

export function validateStablecoinDeployment(input: unknown): StablecoinValidationResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { valid: false, errors: ['input must be an object'] };
  }
  requireNonEmptyString(input, 'deployment_id', errors);
  requireNonEmptyString(input, 'canonical_asset_id', errors);
  requireNonEmptyString(input, 'chain_id', errors);
  requireNonEmptyString(input, 'network', errors);
  requireNonEmptyString(input, 'token_standard', errors);
  requireNonEmptyString(input, 'contract_or_mint', errors);
  requireNonEmptyString(input, 'first_seen_at', errors);
  if (!STABLECOIN_DEPLOYMENT_TYPES.includes(input.deployment_type as StablecoinDeploymentType)) {
    errors.push(`deployment_type must be one of ${STABLECOIN_DEPLOYMENT_TYPES.join(', ')}`);
  }
  const decimals = input.decimals;
  if (typeof decimals !== 'number' || !Number.isInteger(decimals) || decimals < 0 || decimals > 36) {
    errors.push('decimals must be an integer between 0 and 36');
  }
  if (input.global_reference !== true) {
    errors.push('global_reference must be exactly true for deployments');
  }
  return { valid: errors.length === 0, errors };
}

export function validateStablecoinSupportAssertion(input: unknown): StablecoinValidationResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { valid: false, errors: ['input must be an object'] };
  }
  requireNonEmptyString(input, 'assertion_id', errors);
  requireNonEmptyString(input, 'tenant_id', errors);
  requireNonEmptyString(input, 'idempotency_key', errors);
  requireNonEmptyString(input, 'deployment_id', errors);
  requireNonEmptyString(input, 'evidence_type', errors);
  requireObservationOnly(input, errors);
  if (!STABLECOIN_CAPABILITIES.includes(input.capability as StablecoinCapability)) {
    errors.push(`capability must be one of ${STABLECOIN_CAPABILITIES.join(', ')}`);
  }
  if (!SUPPORT_ASSERTION_STATUSES.includes(input.support_status as SupportAssertionStatus)) {
    errors.push(`support_status must be one of ${SUPPORT_ASSERTION_STATUSES.join(', ')}`);
  }
  for (const countField of ['successful_observation_count', 'failed_observation_count']) {
    const v = input[countField];
    if (typeof v !== 'number' || !Number.isInteger(v) || v < 0) {
      errors.push(`${countField} must be a non-negative integer`);
    }
  }
  return { valid: errors.length === 0, errors };
}
