/**
 * Shared time system — deterministic formatter tests.
 *
 * Every formatter takes an explicit context (and `now` for relative
 * rendering): no test depends on the machine's zone, locale, or wall clock.
 */
import { describe, expect, it } from 'vitest';

import {
  describeZone,
  formatDate,
  formatInstant,
  formatRelative,
  formatTime,
  toCanonicalUtc,
} from './format';
import { resolveViewerContext } from './time-provider';
import type { TimeContext } from './types';
import { UTC_CONTEXT } from './types';

const NY: TimeContext = { timeZone: 'America/New_York', locale: 'en-US', lens: 'viewer', hourCycle: 'h12' };
const BERLIN: TimeContext = { timeZone: 'Europe/Berlin', locale: 'de-DE', lens: 'viewer', hourCycle: 'h23' };
const INSTANT = '2026-07-11T18:42:13.482Z';

describe('formatters are zone-explicit and deterministic', () => {
  it('renders the same instant differently per context, preserving identity', () => {
    expect(formatTime(INSTANT, NY)).toBe('2:42 PM');
    expect(formatTime(INSTANT, BERLIN)).toBe('20:42');
    expect(formatTime(INSTANT, UTC_CONTEXT)).toBe('18:42');
    expect(toCanonicalUtc(INSTANT)).toBe('2026-07-11T18:42:13.482Z');
  });

  it('renders dates across the zone day boundary honestly', () => {
    const lateUtc = '2026-07-11T23:30:00Z'; // Jul 11 UTC, but Jul 12 in Berlin
    expect(formatDate(lateUtc, UTC_CONTEXT)).toContain('11');
    expect(formatDate(lateUtc, BERLIN)).toContain('12');
  });

  it('handles DST boundaries (spring-forward day)', () => {
    // 2026-03-08T07:00Z = 03:00 EDT (after the gap); 06:59Z = 01:59 EST.
    expect(formatTime('2026-03-08T06:59:00Z', NY)).toBe('1:59 AM');
    expect(formatTime('2026-03-08T07:00:00Z', NY)).toBe('3:00 AM');
  });

  it('formatInstant includes date and time', () => {
    expect(formatInstant(INSTANT, NY)).toContain('Jul 11, 2026');
    expect(formatInstant(INSTANT, NY)).toContain('2:42');
  });

  it('rejects invalid instants instead of rendering garbage', () => {
    expect(() => formatDate('not-a-time', NY)).toThrow();
  });
});

describe('formatRelative requires an explicit now', () => {
  it('is deterministic given now', () => {
    const now = '2026-07-11T20:42:13Z';
    expect(formatRelative(INSTANT, NY, now)).toBe('2 hours ago');
    expect(formatRelative('2026-07-11T20:41:00Z', NY, now)).toBe('1 minute ago');
    expect(formatRelative('2026-07-12T20:42:13Z', NY, now)).toBe('tomorrow');
  });
});

describe('describeZone discloses the active zone + offset', () => {
  it('includes zone id and offset', () => {
    const label = describeZone(NY, INSTANT);
    expect(label).toContain('America/New_York');
    expect(label).toContain('GMT-4'); // EDT at the July instant
  });
});

describe('viewer zone resolution order', () => {
  const device = { zone: 'America/Chicago', locale: 'en-US' };

  it('manual preference wins', () => {
    const resolved = resolveViewerContext(
      { mode: 'manual', manualTimeZone: 'Asia/Kolkata' },
      device,
    );
    expect(resolved.context.timeZone).toBe('Asia/Kolkata');
    expect(resolved.resolution).toBe('manual_preference');
  });

  it('automatic follows the device', () => {
    const resolved = resolveViewerContext({ mode: 'automatic' }, device);
    expect(resolved.context.timeZone).toBe('America/Chicago');
    expect(resolved.resolution).toBe('device_automatic');
  });

  it('tenant display default fills in when no device zone', () => {
    const resolved = resolveViewerContext(
      { tenantDisplayTimeZone: 'Europe/London' },
      { zone: null, locale: 'en-GB' },
    );
    expect(resolved.context.timeZone).toBe('Europe/London');
    expect(resolved.resolution).toBe('tenant_display_default');
  });

  it('falls back to UTC visibly, never silently', () => {
    const resolved = resolveViewerContext(undefined, { zone: null, locale: 'en-US' });
    expect(resolved.context.timeZone).toBe('UTC');
    expect(resolved.resolution).toBe('utc_fallback');
  });
});
