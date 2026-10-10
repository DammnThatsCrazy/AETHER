// @vitest-environment jsdom
/**
 * Temporal provenance emission — every event context carries the device
 * timezone, the UTC offset captured at event occurrence (not SDK init),
 * and explicit timeZoneSource/clockSource claims for the backend temporal
 * kernel to cross-check.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import aether from '../src/index';

function installFetchCapture() {
  const sent: any[] = [];
  const fetchMock = vi.fn(async (_url: string, init?: any) => {
    if (init?.body) {
      try {
        const parsed = JSON.parse(init.body);
        if (Array.isArray(parsed.batch)) sent.push(...parsed.batch);
      } catch { /* ignore non-batch calls (manifest, heartbeat) */ }
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ accepted: 1, duplicates: 0, rejected: 0, events: [] }),
      text: async () => '{}',
    } as any;
  });
  (globalThis as any).fetch = fetchMock;
  return sent;
}

const BASE_CONFIG = {
  apiKey: 'test-key',
  endpoint: 'https://api.test',
  flushInterval: 60_000,
  modules: { autoDiscovery: false, performance: false },
};

describe('temporal provenance on event context (jsdom)', () => {
  let sent: any[];

  beforeEach(() => {
    localStorage.clear();
    sent = installFetchCapture();
  });

  afterEach(() => {
    try { aether.destroy?.(); } catch { /* ignore */ }
    vi.restoreAllMocks();
  });

  it('stamps timezone, utcOffsetMinutes, timeZoneSource and clockSource per event', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.track('probe');
    await (aether as any).flush?.();

    const evt = sent.find((e) => e.type === 'track');
    expect(evt).toBeTruthy();
    expect(evt.context.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    // `+ 0` normalizes -0 → 0 (a UTC test env yields -0; JSON serializes it as 0).
    expect(evt.context.utcOffsetMinutes).toBe(-new Date().getTimezoneOffset() + 0);
    expect(typeof evt.context.utcOffsetMinutes).toBe('number');
    expect(evt.context.timeZoneSource).toBe('device');
    expect(evt.context.clockSource).toBe('device');
  });

  it('captures the offset at occurrence time, not at init', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);

    // Simulate the device moving zones (or crossing a DST boundary) after init.
    const offsetSpy = vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(-120);
    aether.track('after_zone_change');
    offsetSpy.mockRestore();
    await (aether as any).flush?.();

    const evt = sent.find((e) => e.type === 'track');
    expect(evt).toBeTruthy();
    expect(evt.context.utcOffsetMinutes).toBe(120);
  });
});
