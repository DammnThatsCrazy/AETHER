// =============================================================================
// Canonical USD-first value formatting for the Aether frontends.
//
// Aether observes and prices value; every economic figure is USD-first with a
// native drilldown. The governing invariants (from the canonical contract in
// `packages/shared/value.ts`):
//   - amounts are DECIMAL STRINGS, never floats
//   - usd_value is a decimal string OR null (null => unavailable, NEVER 0)
//   - unknown / stale / unpriced values NEVER render as "$0.00"
//
// NOTE ON TYPES: the canonical types (AetherValue, USDValuation, NativeValue …)
// live in `@aether/shared` (`packages/shared/value.ts`). That package publishes
// its *built* d.ts from `dist/`, and the value contract is not yet present in
// the built output, so it is not reachable from `@aether/ui` at typecheck time.
// The minimal structural mirrors below are intentionally a subset of that
// contract (native.amount/currency + valuation.usd_value/freshness/confidence/
// warning + display) so this module stays self-contained. If/when
// `@aether/shared` ships the value d.ts, these can be swapped for
// `import type { AetherValue } from '@aether/shared'`.
// =============================================================================

/** Mirror of `ValueFreshness` in the canonical contract. */
export type ValueFreshness = 'live' | 'recent' | 'stale' | 'expired' | 'unavailable';

/** Mirror of `ValueConfidence` in the canonical contract. */
export type ValueConfidence = 'high' | 'medium' | 'low' | 'unknown';

/** Mirror of `RollupStatus` in the canonical contract. */
export type RollupStatus = 'complete' | 'partial' | 'stale' | 'unavailable' | 'conflicted';

/** Mirror of `ValueReconciliationState` in the canonical contract. */
export type ValueReconciliationState =
  | 'sdk_only'
  | 'provider_only'
  | 'matched'
  | 'stale'
  | 'conflict'
  | 'ignored_duplicate'
  | 'unreconciled'
  | 'not_applicable';

/** Mirror of `OwnershipRelationship` in the canonical contract. */
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

/** Structural mirror of the canonical `NativeValue` (subset). */
export interface NativeValueLike {
  /** Decimal string, e.g. "1.84". */
  readonly amount: string | number | null | undefined;
  /** ISO fiat code or asset symbol, e.g. "USD", "ETH", "USDC". */
  readonly currency: string;
  readonly asset_symbol?: string | undefined;
}

/** Structural mirror of the canonical `USDValuation` (subset). */
export interface USDValuationLike {
  /** Decimal string OR null. null => no trusted USD price (NEVER coerce to "0"). */
  readonly usd_value: string | number | null | undefined;
  readonly freshness?: ValueFreshness | undefined;
  readonly confidence?: ValueConfidence | undefined;
  readonly warning?: string | undefined;
}

/** Structural mirror of the canonical `DisplayValue` (subset). */
export interface DisplayValueLike {
  readonly primary?: string | undefined;
  readonly secondary?: string | undefined;
  readonly warning?: string | undefined;
}

/** Structural mirror of the canonical `AetherValue` envelope (subset). */
export interface AetherValueLike {
  readonly native?: NativeValueLike | null | undefined;
  readonly valuation?: USDValuationLike | null | undefined;
  readonly display?: DisplayValueLike | null | undefined;
}

/** The default, canonical message for a value with no trusted USD price. */
export const VALUE_UNAVAILABLE = 'Value unavailable';

export interface FormatUSDOptions {
  /** Text to show when the USD value is null / undefined / unparseable. Defaults to "Value unavailable". */
  readonly fallback?: string | undefined;
  /** Use compact notation (e.g. "$1.2K"). Defaults to false. */
  readonly compact?: boolean | undefined;
  readonly maximumFractionDigits?: number | undefined;
  readonly minimumFractionDigits?: number | undefined;
}

/**
 * Format a canonical decimal-string USD value.
 *
 * Returns the fallback ("Value unavailable" by default) when the input is
 * null / undefined / empty / unparseable — it NEVER renders an absent value as
 * "$0.00". A genuine, priced zero ("0") formats as "$0.00" because that is a
 * real value, not an absence.
 */
export function formatUSD(
  usd: string | number | null | undefined,
  opts: FormatUSDOptions = {},
): string {
  const fallback = opts.fallback ?? VALUE_UNAVAILABLE;
  if (usd === null || usd === undefined || usd === '') return fallback;
  const n = typeof usd === 'number' ? usd : Number(usd);
  if (!Number.isFinite(n)) return fallback;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: opts.compact ? 'compact' : 'standard',
    maximumFractionDigits: opts.maximumFractionDigits ?? 2,
    ...(opts.minimumFractionDigits !== undefined
      ? { minimumFractionDigits: opts.minimumFractionDigits }
      : {}),
  }).format(n);
}

export interface FormatNativeOptions {
  readonly maximumFractionDigits?: number | undefined;
  /** Returned when the amount is null / undefined / unparseable. Defaults to "". */
  readonly fallback?: string | undefined;
}

/**
 * Format a native (non-USD) value in its own denomination, e.g. "1.84 ETH".
 * Returns the fallback (empty string by default) when the amount is absent, so
 * callers can choose to hide it rather than show a misleading "0".
 */
export function formatNativeValue(
  amount: string | number | null | undefined,
  currency: string,
  opts: FormatNativeOptions = {},
): string {
  const cur = (currency ?? '').trim();
  const fallback = opts.fallback ?? '';
  if (amount === null || amount === undefined || amount === '') return fallback;
  const n = typeof amount === 'number' ? amount : Number(amount);
  if (!Number.isFinite(n)) return fallback;
  const formatted = new Intl.NumberFormat('en-US', {
    maximumFractionDigits: opts.maximumFractionDigits ?? 6,
  }).format(n);
  return cur ? `${formatted} ${cur}` : formatted;
}

export interface FormattedAetherValue {
  /** USD headline (or "Value unavailable"). Never "$0.00" for an absent price. */
  readonly primary: string;
  /** Native denomination breakdown, e.g. "1.84 ETH", or null when unavailable. */
  readonly secondary: string | null;
  /** Human-facing warning for stale / unpriced / conflicted values, or null. */
  readonly warning: string | null;
}

export interface FormatAetherValueOptions {
  readonly fallback?: string | undefined;
  readonly compact?: boolean | undefined;
}

function deriveWarning(v: AetherValueLike): string | null {
  if (v.display?.warning) return v.display.warning;
  const val = v.valuation;
  if (val?.warning) return val.warning;
  const unpriced = val == null || val.usd_value === null || val.usd_value === undefined;
  if (unpriced) {
    // Only worth flagging when there is a native amount we could not price.
    return v.native != null ? 'Unpriced — no trusted USD valuation' : null;
  }
  switch (val.freshness) {
    case 'stale':
      return 'Valuation may be stale';
    case 'expired':
      return 'Valuation expired';
    case 'unavailable':
      return 'Valuation unavailable';
    default:
      return null;
  }
}

/**
 * Reduce a canonical (or canonical-shaped) value envelope to display strings:
 * a USD-first `primary`, a native `secondary` drilldown, and an optional
 * `warning`. Honors an explicit `display` block when present.
 */
export function formatAetherValue(
  v: AetherValueLike | null | undefined,
  opts: FormatAetherValueOptions = {},
): FormattedAetherValue {
  const fallback = opts.fallback ?? VALUE_UNAVAILABLE;
  if (v == null) {
    return { primary: fallback, secondary: null, warning: null };
  }

  const primary =
    v.display?.primary ??
    formatUSD(v.valuation?.usd_value ?? null, {
      fallback,
      compact: opts.compact,
    });

  const secondaryRaw =
    v.display?.secondary ??
    (v.native != null ? formatNativeValue(v.native.amount, v.native.currency) : '');
  const secondary = secondaryRaw ? secondaryRaw : null;

  return { primary, secondary, warning: deriveWarning(v) };
}
