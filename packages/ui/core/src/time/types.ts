/**
 * Shared frontend time system — types.
 *
 * Every formatter in this package takes an EXPLICIT TimeContext: there is no
 * implicit browser-locale fallback anywhere, so what a component renders is
 * always attributable to a resolved viewer/tenant/event/UTC lens. This
 * package is the ONLY sanctioned home for Intl date/time calls in the
 * frontends (enforced by scripts/validate_temporal_integrity.py).
 */

/** Which temporal authority the UI is currently rendering in. */
export type TimeLens = 'viewer' | 'tenant' | 'event' | 'utc';

export const TIME_LENSES: readonly TimeLens[] = ['viewer', 'tenant', 'event', 'utc'];

export interface TimeContext {
  /** IANA zone id actually used for rendering (never an abbreviation). */
  timeZone: string;
  /** BCP-47 locale for spelling/ordering. */
  locale: string;
  /** The active lens that produced this context. */
  lens: TimeLens;
  hourCycle?: 'h12' | 'h23';
  /** 0 = Sunday … 6 = Saturday. */
  weekStart?: number;
}

/** How the viewer's zone was resolved (display transparency). */
export type TimeZoneResolution =
  | 'manual_preference'
  | 'device_automatic'
  | 'tenant_display_default'
  | 'utc_fallback';

export interface ResolvedViewerTime {
  context: TimeContext;
  resolution: TimeZoneResolution;
}

export const UTC_CONTEXT: TimeContext = {
  timeZone: 'UTC',
  locale: 'en-US',
  lens: 'utc',
  hourCycle: 'h23',
};
