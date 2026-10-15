// @vitest-environment jsdom
/**
 * PR2 — SDK-level behavior for the canonical observe() API, client-side
 * execution_by_aether rejection, and personalization-gated fingerprinting.
 * Runs under jsdom so AetherSDK.init() has a DOM.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import aether from '../src/index';

// Capture every event the SDK flushes to /v1/batch.
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
  modules: { autoDiscovery: false, performance: false, ecommerce: true },
};

describe('AetherSDK.observe() + guards (jsdom)', () => {
  let sent: any[];

  beforeEach(() => {
    localStorage.clear();
    sent = installFetchCapture();
  });

  afterEach(() => {
    try { aether.destroy?.(); } catch { /* ignore */ }
    vi.restoreAllMocks();
  });

  async function flush() {
    await (aether as any).flush?.();
  }

  it('observe() emits the canonical top-level event type', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['commerce']);
    aether.observe('order_completed', { orderId: 'O-1' });
    await flush();
    const evt = sent.find((e) => e.type === 'order_completed');
    expect(evt).toBeTruthy();
    expect(evt.properties.orderId).toBe('O-1');
  });

  it('observe() ignores a non-canonical type (no mislabeled event)', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['commerce', 'analytics']);
    aether.observe('not_a_real_event_type', { x: 1 });
    await flush();
    expect(sent.find((e) => e.type === 'not_a_real_event_type')).toBeUndefined();
  });

  it('drops any event asserting execution_by_aether: true', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['commerce']);
    aether.observe('order_completed', { orderId: 'O-2', execution_by_aether: true });
    await flush();
    expect(sent.find((e) => e.properties?.orderId === 'O-2')).toBeUndefined();
  });

  it('ecommerce helper emits cart_item_added under commerce consent', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['commerce']);
    (aether as any).ecommerce.trackAddToCart({ sku: 'A1' });
    await flush();
    expect(sent.find((e) => e.type === 'cart_item_added')).toBeTruthy();
  });
});

describe('fingerprint is personalization-gated (jsdom)', () => {
  let sent: any[];

  beforeEach(() => {
    localStorage.clear();
    sent = installFetchCapture();
  });

  afterEach(() => {
    try { aether.destroy?.(); } catch { /* ignore */ }
    vi.restoreAllMocks();
  });

  it('does not stamp a fingerprint before personalization consent', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.track('probe');
    await (aether as any).flush?.();
    const evt = sent.find((e) => e.type === 'track');
    expect(evt).toBeTruthy();
    expect(evt.context?.fingerprint).toBeUndefined();
  });
});
