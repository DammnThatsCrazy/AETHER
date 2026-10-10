/**
 * Locale-explicit number formatting.
 *
 * The temporal-integrity gate bans ad-hoc `toLocaleString()` calls in the
 * frontends because they silently pick up the browser's locale. Numeric
 * rendering has the same attribution requirement as temporal rendering, so
 * these helpers take the resolved viewer context (any object carrying the
 * active `locale`, i.e. a `TimeContext` from `useTimeContext()`) — never an
 * implicit browser default.
 */

import type { TimeContext } from '../time/types';

/** Anything carrying the resolved viewer locale — a TimeContext qualifies. */
export type LocaleContext = Pick<TimeContext, 'locale'>;

export interface FormatDecimalOptions {
  minimumFractionDigits?: number;
  maximumFractionDigits?: number;
}

/**
 * Grouped count formatting ("12,345"); the sanctioned replacement for the
 * bare locale-string default.
 */
export function formatCount(value: number, context: LocaleContext): string {
  return new Intl.NumberFormat(context.locale).format(value);
}

/** Decimal with explicit fraction-digit bounds ("1,234.56"). */
export function formatDecimal(
  value: number,
  context: LocaleContext,
  options: FormatDecimalOptions = {},
): string {
  return new Intl.NumberFormat(context.locale, {
    ...(options.minimumFractionDigits != null
      ? { minimumFractionDigits: options.minimumFractionDigits }
      : {}),
    ...(options.maximumFractionDigits != null
      ? { maximumFractionDigits: options.maximumFractionDigits }
      : {}),
  }).format(value);
}

/**
 * Currency amount in an explicit ISO currency code. For canonical Aether
 * value envelopes prefer `formatUSD`/`formatAetherValue` from the value
 * module — this is for plain numeric amounts (e.g. invoice totals) that
 * arrive with their own currency code.
 */
export function formatCurrency(
  value: number,
  currency: string,
  context: LocaleContext,
): string {
  return new Intl.NumberFormat(context.locale, {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(value);
}
