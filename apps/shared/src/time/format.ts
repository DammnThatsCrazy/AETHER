/**
 * Shared frontend time system — pure formatters.
 *
 * All functions are deterministic given (value, context[, now]): no implicit
 * browser zone/locale, no Date.now() — relative formatting takes `now`
 * explicitly so rendering is testable and reproducible. Canonical identity is
 * never altered by display: inputs are ISO-8601 instants (UTC `Z` or offset).
 */

import type { TimeContext } from './types';

function toDate(value: string | number | Date): Date {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`formatters require a valid instant, got: ${String(value)}`);
  }
  return date;
}

function options(context: TimeContext, extra: Intl.DateTimeFormatOptions): Intl.DateTimeFormatOptions {
  return {
    timeZone: context.timeZone,
    ...(context.hourCycle ? { hourCycle: context.hourCycle } : {}),
    ...extra,
  };
}

/** Full instant: date + time in the context's zone (e.g. "Jul 11, 2026, 2:42 PM"). */
export function formatInstant(value: string | number | Date, context: TimeContext): string {
  return new Intl.DateTimeFormat(
    context.locale,
    options(context, { dateStyle: 'medium', timeStyle: 'short' }),
  ).format(toDate(value));
}

/** Date only, in the context's zone. */
export function formatDate(value: string | number | Date, context: TimeContext): string {
  return new Intl.DateTimeFormat(
    context.locale,
    options(context, { dateStyle: 'medium' }),
  ).format(toDate(value));
}

/** Wall-clock time only, in the context's zone. */
export function formatTime(value: string | number | Date, context: TimeContext): string {
  return new Intl.DateTimeFormat(
    context.locale,
    options(context, { timeStyle: 'short' }),
  ).format(toDate(value));
}

/** Date + time with seconds (evidence/detail views). */
export function formatDateTime(value: string | number | Date, context: TimeContext): string {
  return new Intl.DateTimeFormat(
    context.locale,
    options(context, { dateStyle: 'medium', timeStyle: 'medium' }),
  ).format(toDate(value));
}

const RELATIVE_STEPS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
];

/**
 * Relative label ("3 hours ago"). `now` is REQUIRED — callers pass their
 * clock so rendering is deterministic and testable.
 */
export function formatRelative(
  value: string | number | Date,
  context: TimeContext,
  now: string | number | Date,
): string {
  const deltaSeconds = (toDate(value).getTime() - toDate(now).getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(context.locale, { numeric: 'auto' });
  for (const [unit, seconds] of RELATIVE_STEPS) {
    if (Math.abs(deltaSeconds) >= seconds || unit === 'second') {
      return rtf.format(Math.round(deltaSeconds / seconds), unit);
    }
  }
  return rtf.format(0, 'second');
}

/** The zone's display name + current offset (for the time-lens control). */
export function describeZone(context: TimeContext, at: string | number | Date): string {
  const parts = new Intl.DateTimeFormat(context.locale, {
    timeZone: context.timeZone,
    timeZoneName: 'shortOffset',
  }).formatToParts(toDate(at));
  const offset = parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
  return `${context.timeZone} (${offset})`;
}

/** ISO UTC string for evidence panes; canonical identity, never localized. */
export function toCanonicalUtc(value: string | number | Date): string {
  return toDate(value).toISOString();
}
