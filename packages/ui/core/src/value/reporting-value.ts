// =============================================================================
// Reporting-asset + viewer display-currency PRESENTATION (pure, self-contained).
//
// Additive Wave-3 display layer for the canonical financial contracts
// (`packages/shared/value.ts` USDValuation.reporting_asset_id/reporting_amount
// + `packages/shared/financial-assets.ts` canonical asset metadata). Rendering
// a value in a tenant reporting asset or a viewer display currency NEVER
// mutates the stored native fact and NEVER formats through a JS float.
//
// Invariants honored here (mirrors of the canonical contract):
//   - amounts are DECIMAL STRINGS; this module never calls Number() on a
//     canonical amount, never does float arithmetic, and never uses Intl on a
//     value (grouping + decimal scaling are pure string/BigInt operations so
//     arbitrarily large canonical amounts keep full precision).
//   - reporting_amount === null / undefined / non-decimal => "Reporting
//     unavailable" (an explicit state), NEVER "0" / "$0".
//   - a viewer display currency is applied ONLY from an explicit caller-supplied
//     decimal-string conversion rate; absent / malformed rates render the
//     reporting amount plus a clear "Display conversion unavailable" affordance
//     rather than fabricating a $1 or 1:1 assumption.
//   - a bare / non-namespaced asset id is rejected (no symbol/decimals are
//     guessed from an uncanonicalized id).
//
// NOTE ON TYPES: like `./format.ts`, this module mirrors the canonical types it
// consumes so the display core stays self-contained (the @aether/shared value
// contract is not reliably reachable from @aether/ui at typecheck time). The
// canonical metadata RESOLVER lives in ./reporting-asset-meta.ts and imports
// `@aether/shared/financial-assets` directly; this file accepts resolved
// `AssetDisplayMeta` so its logic is pure and testable without that import.
// =============================================================================

/** Default message when no reporting amount is available (never "0"). */
export const REPORTING_UNAVAILABLE = 'Reporting unavailable';

/** Explicit affordance when a viewer display currency was requested but cannot
 * be applied (no rate, malformed rate, or unrecognized display currency). */
export const DISPLAY_CONVERSION_UNAVAILABLE = 'Display conversion unavailable';

// -----------------------------------------------------------------------------
// Decimal-string primitives (no floats anywhere)
// -----------------------------------------------------------------------------

/** Canonical decimal-string shape: optional sign, digits, optional fraction. */
const DECIMAL_STRING_RE = /^-?\d+(?:\.\d+)?$/;

/** True when `value` is a canonical decimal string ("1234", "0.5", "-12.30"). */
export function isDecimalString(value: unknown): value is string {
  return typeof value === 'string' && DECIMAL_STRING_RE.test(value.trim());
}

/**
 * Structural mirror of the canonical asset metadata a reporting asset needs for
 * display. Populated by `resolveReportingAssetMeta` (./reporting-asset-meta.ts)
 * from `@aether/shared/financial-assets` registry data; tests may supply it
 * directly.
 */
export interface AssetDisplayMeta {
  /** Canonical namespaced asset id, e.g. `fiat:EUR`, `crypto:ETH`. */
  readonly assetId: string;
  /** Display code / ticker: ISO code ("EUR") or canonical id symbol segment
   * ("ETH") or the full id for `token:...` assets. Never a guessed symbol. */
  readonly code: string;
  /** Currency symbol rendered as a prefix ("$", "€"), or null when unknown —
   * a code label is shown instead. */
  readonly symbol: string | null;
  /** Display decimals (fiat `minor_units`, registry `display_decimals`), or
   * null when unknown — stored precision is then preserved. */
  readonly minorUnits: number | null;
}

/** A viewer display-currency request: canonical currency id + an EXPLICIT
 * decimal-string conversion rate (display-currency units per 1 reporting unit).
 * `rate` is OPTIONAL because requesting a display currency without a rate is a
 * legitimate state — this layer then renders the reporting amount plus a clear
 * "Display conversion unavailable" affordance and never invents a $1/1:1 rate. */
export interface DisplayCurrencyQuote {
  readonly currencyId: string;
  readonly rate?: string | null | undefined;
}

/** Structural mirror of the additive USDValuation reporting fields. */
export interface ReportingValuationLike {
  readonly reporting_asset_id?: string | null | undefined;
  readonly reporting_amount?: string | null | undefined;
}

// -----------------------------------------------------------------------------
// Scaled-integer decimal math
// -----------------------------------------------------------------------------

interface ParsedDecimal {
  readonly negative: boolean;
  readonly int: string;
  readonly frac: string;
  readonly scale: number;
}

function parseDecimalString(value: string): ParsedDecimal {
  const trimmed = value.trim();
  if (!DECIMAL_STRING_RE.test(trimmed)) {
    throw new Error(
      `reporting-value: "${value}" is not a decimal string (expected optional sign, digits, optional fraction)`,
    );
  }
  let negative = false;
  let body = trimmed;
  if (body.startsWith('-')) {
    negative = true;
    body = body.slice(1);
  } else if (body.startsWith('+')) {
    body = body.slice(1);
  }
  const dot = body.indexOf('.');
  const int = dot === -1 ? body : body.slice(0, dot);
  const frac = dot === -1 ? '' : body.slice(dot + 1);
  return { negative, int, frac, scale: frac.length };
}

/** Render a scaled integer (`int * 10^-scale`) as a canonical decimal string. */
function scaledIntegerToString(value: bigint, scale: number, negative: boolean): string {
  const isNegative = negative && value !== 0n;
  const raw = value.toString();
  if (scale === 0) {
    return isNegative ? `-${raw}` : raw;
  }
  const padded = raw.padStart(scale + 1, '0');
  const intPart = padded.slice(0, padded.length - scale);
  const fracPart = padded.slice(padded.length - scale).replace(/0+$/, '');
  const out = fracPart.length > 0 ? `${intPart}.${fracPart}` : intPart;
  return isNegative ? `-${out}` : out;
}

/**
 * Multiply two decimal strings exactly (BigInt scaled-integer arithmetic; no
 * floats, no precision loss). `amount * rate`. Throws on non-decimal input.
 * `"1049.376"` from `"1234.56" * "0.85"`.
 */
export function convertDecimalAmount(amount: string, rate: string): string {
  const a = parseDecimalString(amount);
  const r = parseDecimalString(rate);
  const negative = a.negative !== r.negative;
  const value = BigInt(a.int + a.frac) * BigInt(r.int + r.frac);
  return scaledIntegerToString(value, a.scale + r.scale, negative);
}

/** Group an integer digit string with thousands separators (pure string op). */
function groupThousands(digits: string): string {
  const parts: string[] = [];
  let remaining = digits;
  while (remaining.length > 3) {
    const start = remaining.length - 3;
    parts.unshift(remaining.slice(start));
    remaining = remaining.slice(0, start);
  }
  parts.unshift(remaining);
  return parts.join(',');
}

/** Drop leading zeros (keep a single "0") for clean integer presentation. */
function normalizeInt(digits: string): string {
  const stripped = digits.replace(/^0+/, '');
  return stripped.length > 0 ? stripped : '0';
}

export interface FormatDecimalAmountOptions {
  /** Number of fraction digits to show. Extra digits are TRUNCATED (never
   * rounded, never inflated); missing digits are zero-padded. null/undefined
   * preserves the amount's stored precision. */
  readonly minorUnits?: number | null | undefined;
  /** Group the integer part with thousands separators. Defaults to true. */
  readonly group?: boolean | undefined;
}

/**
 * Format a canonical decimal string using a resolved asset's display decimals.
 * Pure string work — the full precision of arbitrarily large amounts is kept.
 */
export function formatDecimalAmount(
  amount: string,
  opts: FormatDecimalAmountOptions = {},
): string {
  const p = parseDecimalString(amount);
  let frac = p.frac;
  const minorUnits = opts.minorUnits ?? null;
  if (minorUnits !== null) {
    if (minorUnits < 0) {
      throw new Error(`reporting-value: minorUnits must be >= 0 (got ${minorUnits})`);
    }
    if (minorUnits === 0) {
      frac = '';
    } else if (frac.length > minorUnits) {
      frac = frac.slice(0, minorUnits);
    } else {
      frac = frac.padEnd(minorUnits, '0');
    }
  }
  const int = normalizeInt(p.int);
  const grouped = opts.group === false ? int : groupThousands(int);
  const sign = p.negative ? '-' : '';
  return frac.length > 0 ? `${sign}${grouped}.${frac}` : `${sign}${grouped}`;
}

/** Prefix a symbol onto an already-formatted amount ("-€1,234.56"). */
export function decorateAmountText(amountText: string, symbol: string | null): string {
  if (!symbol) return amountText;
  if (amountText.startsWith('-')) {
    return `-${symbol}${amountText.slice(1)}`;
  }
  return `${symbol}${amountText}`;
}

// -----------------------------------------------------------------------------
// Reporting value presentation
// -----------------------------------------------------------------------------

export type ReportingValueKind =
  | 'unavailable-reporting'
  | 'reporting'
  | 'reporting-no-display-rate'
  | 'reporting-display-converted';

export type ReportingUnavailableReason =
  | 'no-reporting-amount'
  | 'invalid-reporting-amount'
  | 'missing-reporting-asset-id'
  | 'unrecognized-reporting-asset';

export interface ReportingValueRender {
  /** Discriminates what a consumer should present. */
  readonly kind: ReportingValueKind;
  /** Reason the value could not be attributed/shown (null when available). */
  readonly unavailableReason: ReportingUnavailableReason | null;
  /** "Reporting unavailable" (or a caller fallback) when unavailable; the
   * decorated reporting amount otherwise. NEVER a monetary zero on absence. */
  readonly reportingText: string;
  /** Undecorated, formatted reporting amount (null when unavailable). */
  readonly reportingAmountText: string | null;
  /** Reporting display code ("EUR", "ETH") or canonical id (token) — null when
   * unavailable. */
  readonly reportingCode: string | null;
  /** Canonical reporting asset id (e.g. `fiat:EUR`) or null. */
  readonly reportingAssetId: string | null;
  /** Decorated viewer display-currency amount when a conversion was applied. */
  readonly convertedText: string | null;
  /** Display-currency display code when a conversion was applied. */
  readonly convertedCode: string | null;
  /** The explicit conversion rate that was applied (decimal string), or null. */
  readonly rateApplied: string | null;
  /** Explicit affordance when a display currency was requested but NOT applied
   * (absent/malformed rate, or unrecognized display currency id). */
  readonly displayConversionUnavailableText: string | null;
}

export interface ComposeReportingDisplayInput {
  /** Canonical reporting amount as a decimal string, or null => unavailable. */
  readonly reportingAmount: string | null | undefined;
  /** Canonical reporting asset id (`fiat:EUR`). A bare symbol is rejected. */
  readonly reportingAssetId: string | null | undefined;
  /** Resolved canonical metadata for the reporting asset (null when the id is
   * absent or not namespaced => rejected, no symbol/decimals guessed). */
  readonly assetMeta: AssetDisplayMeta | null | undefined;
  /** Optional viewer display-currency request. PURE DISPLAY only — the input
   * value is never written back. */
  readonly displayCurrencyQuote?: DisplayCurrencyQuote | null | undefined;
  /** Resolved metadata for the display currency (null => cannot convert). */
  readonly displayCurrencyMeta?: AssetDisplayMeta | null | undefined;
  /** Override the unavailable message (default REPORTING_UNAVAILABLE). */
  readonly fallbackLabel?: string | null | undefined;
}

/** Shared shape-helper for the "amount attributed to a reporting asset" render. */
function attributedRender(
  reportingAmount: string,
  assetMeta: AssetDisplayMeta,
): ReportingValueRender {
  const reportingAmountText = formatDecimalAmount(reportingAmount, {
    minorUnits: assetMeta.minorUnits,
  });
  return {
    kind: 'reporting',
    unavailableReason: null,
    reportingText: decorateAmountText(reportingAmountText, assetMeta.symbol),
    reportingAmountText,
    reportingCode: assetMeta.code,
    reportingAssetId: assetMeta.assetId,
    convertedText: null,
    convertedCode: null,
    rateApplied: null,
    displayConversionUnavailableText: null,
  };
}

/**
 * Compose the reporting-asset / display-currency presentation for a value.
 *
 * Pure: reads its inputs and returns a render model; it never mutates the input
 * value object and never writes a formatted figure back into it. Absence is
 * always an explicit state (never "0"), and a viewer display currency is only
 * ever derived from an explicit caller-supplied rate.
 */
export function composeReportingDisplay(
  input: ComposeReportingDisplayInput,
): ReportingValueRender {
  const fallback = input.fallbackLabel ?? REPORTING_UNAVAILABLE;

  const unavailable = (
    unavailableReason: ReportingUnavailableReason,
  ): ReportingValueRender => ({
    kind: 'unavailable-reporting',
    unavailableReason,
    reportingText: fallback,
    reportingAmountText: null,
    reportingCode: null,
    reportingAssetId: null,
    convertedText: null,
    convertedCode: null,
    rateApplied: null,
    displayConversionUnavailableText: null,
  });

  const { reportingAmount, reportingAssetId, assetMeta } = input;
  if (reportingAmount === null || reportingAmount === undefined || reportingAmount === '') {
    return unavailable('no-reporting-amount');
  }
  if (!isDecimalString(reportingAmount)) {
    // A non-decimal-string amount is a contract violation — never float-parse it.
    return unavailable('invalid-reporting-amount');
  }
  if (reportingAssetId === null || reportingAssetId === undefined || reportingAssetId.trim() === '') {
    return unavailable('missing-reporting-asset-id');
  }
  if (!assetMeta) {
    // Bare / non-namespaced id: no canonical metadata to render against. Reject
    // rather than guess a symbol or decimals.
    return unavailable('unrecognized-reporting-asset');
  }

  const base = attributedRender(reportingAmount, assetMeta);
  const quote = input.displayCurrencyQuote;
  const wantsDisplayCurrency =
    quote !== null && quote !== undefined && quote.currencyId.trim() !== '';

  if (!wantsDisplayCurrency) {
    return base;
  }

  // Only a decimal-string rate is ever used; any other payload is "no rate".
  const rawRate: unknown = quote.rate;
  const rate = typeof rawRate === 'string' ? rawRate.trim() : '';
  const displayMeta = input.displayCurrencyMeta;

  if (rate === '' || !isDecimalString(rate) || !displayMeta) {
    // No trustworthy rate (or an unrecognized display currency id) => show the
    // reporting amount plus an explicit "conversion unavailable" affordance.
    return {
      ...base,
      kind: 'reporting-no-display-rate',
      displayConversionUnavailableText: DISPLAY_CONVERSION_UNAVAILABLE,
    };
  }

  const converted = convertDecimalAmount(reportingAmount, rate);
  const convertedAmountText = formatDecimalAmount(converted, {
    minorUnits: displayMeta.minorUnits,
  });
  return {
    ...base,
    kind: 'reporting-display-converted',
    convertedText: decorateAmountText(convertedAmountText, displayMeta.symbol),
    convertedCode: displayMeta.code,
    rateApplied: rate,
  };
}
