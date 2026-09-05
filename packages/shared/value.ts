// =============================================================================
// Aether SDK — CANONICAL VALUE CONTRACT (source of truth)
//
// Every financial / economic value that Aether surfaces is semantically typed.
// Aether observes and prices value; it never custodies, settles, or executes.
//
// Invariants (enforced by scripts/validate_financial_value_semantics.py and the
// backend services/value mirror in `services/value/models.py`):
//   - amounts are DECIMAL STRINGS, never floats
//   - usd_value is a decimal string OR null (null => unavailable/unknown, NEVER 0)
//   - unknown / stale / unpriced / conflicted values NEVER become 0
//   - mixed native currencies are never scalar-summed without a USD valuation
//   - stablecoins are not assumed to be $1 — valuation is peg-aware, source-backed
//   - liabilities are never counted as assets
// =============================================================================

import type { EconomicRole } from './financial-assets';

/** What kind of quantity a value represents. These must never be mixed in a rollup. */
export type MetricKind =
  | 'balance'
  | 'flow'
  | 'kpi'
  | 'forecast'
  | 'valuation'
  | 'liability'
  | 'cost'
  | 'fee'
  | 'revenue'
  | 'risk_exposure'
  | 'unknown';

export type ValueFreshness =
  | 'live'
  | 'recent'
  | 'stale'
  | 'expired'
  | 'unavailable';

export type ValueConfidence = 'high' | 'medium' | 'low' | 'unknown';

export type OwnershipRelationship =
  | 'owned'
  | 'linked'
  | 'controlled'
  | 'custodied'
  | 'delegated'
  | 'counterparty'
  | 'observed'
  | 'inferred'
  | 'external'
  | 'unknown';

export type ValueReconciliationState =
  | 'sdk_only'
  | 'provider_only'
  | 'matched'
  | 'stale'
  | 'conflict'
  | 'ignored_duplicate'
  | 'unreconciled'
  | 'not_applicable';

export type ValuationMethod =
  | 'fiat_identity'
  | 'fx_rate'
  | 'market_price'
  | 'provider_reported'
  | 'stablecoin_peg_verified'
  | 'manual'
  | 'unavailable';

/** The value as it exists in its native denomination (never discarded). */
export interface NativeValue {
  /** Decimal string, e.g. "1234.56". Never a float. */
  amount: string;
  /** ISO fiat code or asset symbol, e.g. "USD", "ETH", "USDC". */
  currency: string;
  asset_id?: string;
  asset_symbol?: string;
  asset_name?: string;
  chain?: string;
  network?: string;
  contract_or_mint?: string;
  decimals?: number;
  provider?: string;
  account_id?: string;
  wallet_id?: string;
  rail?: string;
  // ── Financial-normalization additive fields (packages/shared/financial-assets.ts) ──
  /** Namespaced canonical asset id (`fiat:USD`, `crypto:ETH`, `stablecoin:USDC`,
   * `token:<chain>:<contract>`) when identity is canonicalized. */
  canonical_asset_id?: string;
  /** Canonical deployment id (`deploy:<asset_id>@<chain>:<contract>`) when the
   * value is deployment-scoped. */
  deployment_id?: string;
  /** Economic role this leg plays (financial-assets EconomicRole union). */
  economic_role?: EconomicRole;
}

/** A trustworthy (or explicitly absent) USD valuation of a native value. */
export interface USDValuation {
  /** Decimal string OR null. null => no trusted USD price (NEVER coerce to "0"). */
  usd_value: string | null;
  conversion_rate?: string;
  conversion_source?: string;
  priced_at?: string;
  computed_at: string;
  freshness: ValueFreshness;
  confidence: ValueConfidence;
  valuation_method: ValuationMethod;
  stale_after_seconds?: number;
  warning?: string;
  // ── Financial-normalization additive fields (packages/shared/financial-assets.ts) ──
  /** Reporting asset id when the envelope reports in a non-USD asset
   * (e.g. `fiat:EUR`). `usd_value` above remains the required USD leg. */
  reporting_asset_id?: string;
  /** Reporting amount in `reporting_asset_id`, as a decimal string OR null.
   * null => unavailable (NEVER "0"). */
  reporting_amount?: string | null;
}

export interface ValueOwnership {
  relationship: OwnershipRelationship;
  confidence: ValueConfidence;
  evidence_type?: string;
  evidence_id?: string;
  canonical_entity_id?: string;
}

export interface ValueStatus {
  metric_kind: MetricKind;
  settlement_status?: string;
  reconciliation_state: ValueReconciliationState;
  data_freshness: ValueFreshness;
  include_in_rollups: boolean;
  /** Required when include_in_rollups is false. */
  exclusion_reason?: string;
}

export interface DisplayValue {
  /** Primary, human-facing string, e.g. "$12,430.22 USD" or "Value unavailable". */
  primary: string;
  secondary?: string;
  tertiary?: string;
  warning?: string;
}

/** The canonical, fully-typed value envelope. */
export interface AetherValue {
  id: string;
  metric: string;
  metric_kind: MetricKind;
  native: NativeValue;
  valuation: USDValuation;
  ownership: ValueOwnership;
  status: ValueStatus;
  display: DisplayValue;
  source: {
    source_system: string;
    source_record_id?: string;
    source_event_id?: string;
    observed_at?: string;
    computed_at: string;
  };
  metadata?: Record<string, unknown>;
}

export type RollupStatus = 'complete' | 'partial' | 'stale' | 'unavailable' | 'conflicted';

/** The safe result of summing many values — never a single mixed-currency scalar. */
export interface RollupResult {
  /** Decimal string OR null. null => no trustworthy USD total (NEVER "0" on absence). */
  total_usd: string | null;
  by_native_currency: Record<string, { amount: string; usd_value: string | null; count: number; priced: boolean }>;
  by_asset?: Record<string, { amount: string; usd_value: string | null; count: number }>;
  unpriced_count: number;
  stale_count: number;
  excluded_count: number;
  rollup_status: RollupStatus;
  /** Populated only when unambiguous (single native currency); null otherwise. */
  native_currency?: string | null;
  /**
   * Reporting-asset-keyed totals (financial-normalization additive). Present only
   * when a non-default reporting context was requested. Each key is a canonical
   * asset id (`fiat:USD` default). A null `total` means no trustworthy value in
   * that reporting asset — never "0". Conversion to another reporting asset is
   * never guessed: amounts are summed only where a trustworthy valuation exists.
   */
  reporting_totals?: Record<
    string,
    {
      total: string | null;
      priced_count: number;
      unpriced_count: number;
      excluded_count: number;
      stale_count: number;
      coverage_percentage: number | null;
      rollup_status: RollupStatus;
    }
  >;
  /** Provenance of the values summed into the reporting total (opt-in). */
  value_lineage?: Array<{
    source_record_id?: string;
    native_amount: string;
    native_currency: string;
    reporting_amount: string;
    reporting_asset_id: string;
  }>;
}

/** Type guard: a value is safe to include in a USD rollup. */
export function isRollupEligible(v: Pick<AetherValue, 'status' | 'valuation'>): boolean {
  return v.status.include_in_rollups === true && v.valuation.usd_value !== null;
}

// ── Financial-normalization additive contracts (canonical native value) ──────

/**
 * A NativeValue whose canonical identity is REQUIRED. Created when an
 * unresolved/symbol-only value has been resolved against the financial-assets
 * registry (packages/shared/financial-assets.ts). `canonical_asset_id` is the
 * namespaced identity — the native value keeps its original `amount`/`currency`
 * verbatim; canonicalization never rewrites the observed amount.
 */
export interface CanonicalNativeValue extends NativeValue {
  /** Namespaced canonical asset id — REQUIRED (unlike NativeValue). */
  canonical_asset_id: string;
}

/** Narrowing guard: a native value is canonical when it carries a non-empty
 * namespaced canonical_asset_id. */
export function isCanonicalNativeValue(v: NativeValue): v is CanonicalNativeValue {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof v.canonical_asset_id === 'string' &&
    v.canonical_asset_id.length > 0
  );
}

/** Assertion variant: throws a TypeError when `v` is not canonical. */
export function assertCanonicalNative(v: NativeValue): asserts v is CanonicalNativeValue {
  if (!isCanonicalNativeValue(v)) {
    throw new TypeError(
      'value is not a CanonicalNativeValue: a non-empty namespaced canonical_asset_id is required',
    );
  }
}
