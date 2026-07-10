// =============================================================================
// Payment Rail Observability — canonical funding session contracts
// =============================================================================
// Aether observes, normalizes, reconciles, and displays how money enters,
// exits, settles, or fails across providers. Aether does not execute or
// settle payments, custody funds, or sign transactions.
//
// Named providers only (no generic webhook fallback): Privy, Stripe crypto
// onramp, Coinbase onramp/offramp, MoonPay buy/sell, Bridge virtual accounts.
// Records never carry raw KYC documents, card numbers, bank/routing numbers,
// or provider secrets; metadata is sanitized and explicitly PII-safe.
// =============================================================================

export const PAYMENT_RAILS_SCHEMA_VERSION = 'payment.rails.v1' as const;

export const paymentRailProviders = [
  'privy',
  'stripe',
  'coinbase',
  'moonpay',
  'bridge',
] as const;
export type PaymentRailProvider = typeof paymentRailProviders[number];

export const fundingFlowTypes = [
  'fiat_onramp',
  'crypto_onramp',
  'bank_deposit',
  'crypto_deposit',
  'offramp',
  'settlement',
  'refund',
] as const;
export type FundingFlowType = typeof fundingFlowTypes[number];

export const paymentRails = [
  'fiat',
  'stripe',
  'coinbase',
  'moonpay',
  'bridge',
  'bank_transfer',
  'card',
  'ach',
  'wire',
  'sepa',
  'onchain',
  'x402',
] as const;
export type PaymentRail = typeof paymentRails[number];

/**
 * Canonical funding session status. Final states (completed, failed,
 * refunded, cancelled) never regress on duplicate or out-of-order provider
 * events.
 */
export const fundingSessionStatuses = [
  'initiated',
  'submitted',
  'pending',
  'completed',
  'failed',
  'refunded',
  'cancelled',
  'unresolved',
] as const;
export type FundingSessionStatus = typeof fundingSessionStatuses[number];

export const reconciliationStates = [
  'sdk_only',
  'provider_only',
  'matched',
  'stale',
  'conflict',
  'ignored_duplicate',
] as const;
export type ReconciliationState = typeof reconciliationStates[number];

export const fundingActorKinds = [
  'human',
  'agent',
  'org',
  'wallet',
  'service',
  'system',
] as const;
export type FundingActorKind = typeof fundingActorKinds[number];

/**
 * Canonical internal funding session — one normalized record per observed
 * onramp/offramp/deposit/settlement/refund flow, tenant-scoped and idempotent
 * on (tenant_id, idempotency_key).
 */
export interface FundingSession {
  id: string;
  tenant_id: string;
  provider: PaymentRailProvider;
  /** Underlying processor when the provider routes through another rail (e.g. Privy → Stripe/MoonPay/Coinbase/Meld). */
  provider_detail?: string;
  flow_type: FundingFlowType;
  rail: PaymentRail;
  status: FundingSessionStatus;
  /** Provider-native status string the canonical status was mapped from. */
  provider_status?: string;
  /** Failure/rejection reason metadata (e.g. AML, fraud, min-amount), sanitized. */
  status_reason?: string;
  reconciliation_state: ReconciliationState;

  actor_kind: FundingActorKind;
  user_id?: string;
  agent_id?: string;
  org_id?: string;
  session_id?: string;
  device_id?: string;
  journey_id?: string;
  campaign_id?: string;

  source_asset?: string;
  source_chain?: string;
  source_amount?: string;
  fiat_currency?: string;
  destination_asset?: string;
  destination_chain?: string;
  destination_amount?: string;
  destination_address?: string;

  /** Fee total where safely reported by the provider, in fiat_currency or destination_asset units. */
  fee_amount?: string;
  fee_currency?: string;

  provider_session_id?: string;
  provider_transaction_id?: string;
  /** Safe opaque customer reference only — never a PAN, account number, or KYC identifier. */
  provider_customer_ref?: string;
  deposit_address_id?: string;
  virtual_account_id?: string;
  tx_hash?: string;

  idempotency_key: string;
  occurred_at: string;
  created_at: string;
  updated_at: string;
  /** Sanitized, explicitly PII-safe metadata. */
  metadata?: Record<string, unknown>;
}

/** Tenant-scoped provider connection metadata. Secrets live in the key vault, never here. */
export interface PaymentProviderAccount {
  id: string;
  tenant_id: string;
  provider: PaymentRailProvider;
  display_name?: string;
  /** Safe provider-side account/business identifier. */
  provider_account_ref?: string;
  environment: 'production' | 'sandbox';
  status: 'configured' | 'not_configured' | 'error' | 'disabled';
  /** Whether a webhook verification secret is configured (never the secret itself). */
  webhook_configured: boolean;
  /** Whether API polling credentials are configured (never the credentials). */
  polling_configured: boolean;
  created_at: string;
  updated_at: string;
}

/** Provider-issued crypto deposit address reference (Privy et al.). */
export interface DepositAddress {
  id: string;
  tenant_id: string;
  provider: PaymentRailProvider;
  provider_address_id?: string;
  address: string;
  chain: string;
  asset?: string;
  user_id?: string;
  wallet_id?: string;
  status: 'active' | 'inactive' | 'unknown';
  created_at: string;
  updated_at: string;
}

/** Provider-issued virtual bank account reference (Bridge et al.). */
export interface VirtualAccount {
  id: string;
  tenant_id: string;
  provider: PaymentRailProvider;
  provider_virtual_account_id: string;
  provider_customer_ref?: string;
  /** Masked/partial account reference safe for display (never full account/routing numbers). */
  masked_account_ref?: string;
  currency?: string;
  destination_address?: string;
  destination_chain?: string;
  status: 'active' | 'deactivated' | 'unknown';
  created_at: string;
  updated_at: string;
}

/**
 * Per-provider mapping from provider-native statuses to canonical
 * FundingSessionStatus values, with ordering rank for non-regression.
 */
export interface PaymentRailStatusMap {
  provider: PaymentRailProvider;
  /** provider-native status → canonical status */
  statuses: Record<string, FundingSessionStatus>;
  /** Canonical status → monotonic rank; final states hold the highest ranks. */
  ordering: Record<FundingSessionStatus, number>;
  version: string;
}

/** Result of reconciling a funding session against provider/SDK truth. */
export interface ReconciliationRecord {
  id: string;
  tenant_id: string;
  funding_session_id: string;
  provider: PaymentRailProvider;
  state: ReconciliationState;
  /** Source that most recently advanced this record: 'sdk' | 'webhook' | 'polling' | 'manual'. */
  last_source: string;
  sdk_event_id?: string;
  provider_event_id?: string;
  /** Field-level mismatches found when state is 'conflict', sanitized. */
  discrepancies?: Array<{ field: string; sdk_value?: string; provider_value?: string }>;
  first_observed_at: string;
  last_checked_at: string;
  resolved_at?: string;
  created_at: string;
  updated_at: string;
}

/** Aggregate per-provider health for Aether/Kyber surfaces. */
export interface PaymentRailHealth {
  tenant_id?: string;
  provider: PaymentRailProvider;
  configured: boolean;
  enabled: boolean;
  webhook_verified_24h: number;
  webhook_rejected_24h: number;
  sessions_observed_24h: number;
  sessions_completed_24h: number;
  sessions_failed_24h: number;
  sessions_unresolved: number;
  reconciliation_matched_rate?: number;
  reconciliation_conflicts: number;
  last_event_at?: string;
  last_poll_at?: string;
  status: 'healthy' | 'degraded' | 'not_configured' | 'error';
  computed_at: string;
}
