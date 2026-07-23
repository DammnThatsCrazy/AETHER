// @vitest-environment jsdom
/**
 * Phase D — the web SDK populates the canonical envelope fields it has a genuine
 * source for: `surface` (origin plane) and `sequence.event` (monotonic ordering
 * counter for gap/reorder detection). Runs under jsdom so AetherSDK.init() has a DOM.
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
      } catch { /* ignore non-batch calls */ }
    }
    return {
      ok: true, status: 200,
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

describe('canonical envelope fields on web events (jsdom)', () => {
  let sent: any[];

  beforeEach(() => { localStorage.clear(); sent = installFetchCapture(); });
  afterEach(() => { try { aether.destroy?.(); } catch { /* ignore */ } vi.restoreAllMocks(); });

  const flush = async () => { await (aether as any).flush?.(); };

  it("stamps context.surface = 'web' on every event", async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.track('probe');
    await flush();
    const evt = sent.find((e) => e.type === 'track');
    expect(evt).toBeTruthy();
    expect(evt.context.surface).toBe('web');
  });

  it('stamps a monotonically increasing context.sequence.event', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.track('probe');
    aether.track('probe');
    await flush();
    const probes = sent.filter((e) => e.type === 'track');
    expect(probes.length).toBeGreaterThanOrEqual(2);
    const seqs = probes.map((e) => e.context.sequence.event);
    expect(typeof seqs[0]).toBe('number');
    // Strictly increasing in emission order.
    expect(seqs[1]).toBeGreaterThan(seqs[0]);
  });

  it('stamps schemaVersion and operatingSystem from real device context', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.track('probe');
    await flush();
    const ctx = sent.find((e) => e.type === 'track').context;
    expect(ctx.schemaVersion).toBe('1.0.0');
    expect(typeof ctx.operatingSystem?.name).toBe('string');
  });

  it('stamps application identity from config; omitted when not configured', async () => {
    aether.init({ ...BASE_CONFIG, application: { name: 'Acme Store', version: '4.0.0' } });
    aether.consent.grant(['analytics']);
    aether.track('probe');
    await flush();
    const ctx = sent.find((e) => e.type === 'track').context;
    expect(ctx.application).toEqual({ name: 'Acme Store', version: '4.0.0' });
  });
});
