// =============================================================================
// Card-linked payment rail observability — canonical V1 semantics
// =============================================================================
// Observation-first contracts for crypto-card/card-linked economic activity.
// Aether observes, normalizes, graphs, filters, and diagnoses these flows; it
// never issues cards, processes payments, custodies funds, stores PAN/CVV/KYC,
// or treats PaymentScan benchmarks as deterministic user-level truth.
// =============================================================================

export type CardActivityBasis =
  | 'topup'
  | 'funding'
  | 'spend'
  | 'settlement'
  | 'clearing'
  | 'refund'
  | 'reversal'
  | 'mixed'
  | 'benchmark_only'
  | 'unknown';

export const cardActivityBases = [
  'topup', 'funding', 'spend', 'settlement', 'clearing', 'refund', 'reversal',
  'mixed', 'benchmark_only', 'unknown',
] as const satisfies readonly CardActivityBasis[];

export type CardLinkedSource =
  | 'paymentscan'
  | 'sdk'
  | 'onchain_observer'
  | 'provider_webhook'
  | 'issuer_api'
  | 'tenant_import'
  | 'manual_seed';

export const cardLinkedSources = [
  'paymentscan', 'sdk', 'onchain_observer', 'provider_webhook', 'issuer_api',
  'tenant_import', 'manual_seed',
] as const satisfies readonly CardLinkedSource[];

export type ObservationConfidence = 'weak' | 'probable' | 'strong' | 'deterministic';
export const observationConfidences = ['weak', 'probable', 'strong', 'deterministic'] as const;

export type RegionPolicyMode =
  | 'US_STANDARD'
  | 'EU_RESTRICTED'
  | 'UK_RESTRICTED'
  | 'APAC_RESTRICTED'
  | 'GLOBAL_AGGREGATE_ONLY';

export const regionPolicyModes = [
  'US_STANDARD', 'EU_RESTRICTED', 'UK_RESTRICTED', 'APAC_RESTRICTED', 'GLOBAL_AGGREGATE_ONLY',
] as const satisfies readonly RegionPolicyMode[];

export type CardLinkedRail = 'card' | 'onchain' | 'bank_transfer' | 'x402' | 'unknown';
export type CardLinkedActorKind = 'human' | 'agent' | 'org' | 'wallet' | 'service' | 'system';
export type CardLinkedReconciliationState =
  | 'sdk_only'
  | 'provider_only'
  | 'onchain_only'
  | 'benchmark_only'
  | 'matched'
  | 'stale'
  | 'conflict'
  | 'ignored_duplicate';

export interface CardLinkedFlowObserved {
  id: string;
  tenant_id: string;
  actor_kind: CardLinkedActorKind;
  canonical_entity_id?: string;
  user_id?: string;
  agent_id?: string;
  org_id?: string;
  wallet_address_hash?: string;
  card_program_id?: string;
  issuer_id?: string;
  payment_network?: 'visa' | 'mastercard' | 'unknown';
  rail: CardLinkedRail;
  basis: CardActivityBasis;
  chain?: string;
  asset?: string;
  amount_usd?: string;
  amount_native?: string;
  amount_bucket?: string;
  campaign_id?: string;
  journey_id?: string;
  session_id?: string;
  device_id?: string;
  source: CardLinkedSource;
  confidence: ObservationConfidence;
  evidence_refs: string[];
  reconciliation_state: CardLinkedReconciliationState;
  region_policy?: RegionPolicyMode;
  consent_snapshot?: Record<string, boolean>;
  occurred_at: string;
  observed_at: string;
  created_at: string;
  updated_at: string;
}

export type CardLinkedFieldClassification =
  | 'public_onchain'
  | 'pseudonymous_identifier'
  | 'restricted_identifier'
  | 'catalog_dimension'
  | 'financial_behavior'
  | 'financial_behavior_metadata'
  | 'attribution_metadata'
  | 'behavioral_metadata'
  | 'blocked';

export const cardLinkedFieldClassification: Record<string, CardLinkedFieldClassification> = {
  tx_hash: 'public_onchain',
  wallet_address_hash: 'pseudonymous_identifier',
  provider_customer_ref: 'restricted_identifier',
  card_program_id: 'catalog_dimension',
  issuer_id: 'catalog_dimension',
  payment_network: 'catalog_dimension',
  amount_usd: 'financial_behavior',
  basis: 'financial_behavior_metadata',
  campaign_id: 'attribution_metadata',
  journey_id: 'behavioral_metadata',
  pan: 'blocked',
  cvv: 'blocked',
  raw_kyc_document: 'blocked',
  full_bank_account: 'blocked',
  routing_number: 'blocked',
  provider_secret: 'blocked',
};

export const blockedCardLinkedFields = Object.entries(cardLinkedFieldClassification)
  .filter(([, classification]) => classification === 'blocked')
  .map(([field]) => field);

export function assertCardActivityBasis(value: string): asserts value is CardActivityBasis {
  if (!(cardActivityBases as readonly string[]).includes(value)) {
    throw new Error(`Unsupported card-linked basis: ${value}`);
  }
}

export function normalizeCardLinkedBasis(value: string | undefined, source?: CardLinkedSource): CardActivityBasis {
  if (!value) return source === 'paymentscan' ? 'benchmark_only' : 'unknown';
  assertCardActivityBasis(value);
  return value;
}

export function redactBlockedCardLinkedFields<T extends Record<string, unknown>>(payload: T): T {
  const copy = { ...payload };
  for (const field of blockedCardLinkedFields) {
    if (field in copy) copy[field as keyof T] = '[REDACTED_BLOCKED]' as T[keyof T];
  }
  return copy;
}

export function rejectBlockedCardLinkedFields(payload: Record<string, unknown>): void {
  const present = blockedCardLinkedFields.filter((field) => payload[field] !== undefined && payload[field] !== null);
  if (present.length > 0) {
    throw new Error(`Blocked card-linked fields present: ${present.join(', ')}`);
  }
}

export const cardLinkedConsentPurposeMap = {
  card_payment_topup_metadata: ['commerce'],
  wallet_onchain_transaction: ['web3'],
  agent_influenced_card_activity: ['agent', 'commerce'],
  credit_underwriting_card_eligibility: ['credit_explicit_opt_in'],
  merchant_location_mcc_geographic_behavior: ['location_explicit_opt_in'],
  raw_card_kyc_bank_data: ['blocked'],
} as const;
