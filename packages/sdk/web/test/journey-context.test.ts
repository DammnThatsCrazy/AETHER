// @vitest-environment jsdom
/**
 * Phase E — the ACTIVE journey is attached to EVERY event's context (not only
 * to journey_* lifecycle events), so the backend can annotate any event with
 * the journey it occurred within. `EventContext.journey` was typed but never
 * populated on regular events. Runs under jsdom so AetherSDK.init() has a DOM.
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
  modules: { autoDiscovery: false, performance: false },
};

describe('active journey context on every event (jsdom)', () => {
  let sent: any[];

  beforeEach(() => {
    localStorage.clear();
    sent = installFetchCapture();
  });

  afterEach(() => {
    try { aether.destroy?.(); } catch { /* ignore */ }
    vi.restoreAllMocks();
  });

  const flush = async () => { await (aether as any).flush?.(); };

  it('attaches the active journey snapshot to a regular (non-journey) event', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.startJourney('checkout', { journeyName: 'Checkout', journeyType: 'purchase' });
    aether.track('probe');
    await flush();

    const evt = sent.find((e) => e.type === 'track');
    expect(evt).toBeTruthy();
    expect(evt.context.journey).toBeTruthy();
    expect(evt.context.journey.journeyName).toBe('Checkout');
    expect(evt.context.journey.journeyType).toBe('purchase');
    expect(evt.context.journey.journeyStatus).toBe('started');
    expect(typeof evt.context.journey.journeyId).toBe('string');
  });

  it('stamps the same journeyId returned by startJourney onto the event', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    const journey = aether.startJourney('onboarding');
    aether.track('probe');
    await flush();

    const evt = sent.find((e) => e.type === 'track');
    expect(evt.context.journey.journeyId).toBe(journey?.journeyId);
  });

  it('omits journey context when no journey is active', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.track('probe');
    await flush();

    const evt = sent.find((e) => e.type === 'track');
    expect(evt).toBeTruthy();
    expect(evt.context.journey).toBeUndefined();
  });

  it('drops journey context once the journey completes', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['analytics']);
    aether.startJourney('checkout');
    aether.completeJourney('done');
    aether.track('probe');
    await flush();

    const probe = sent.find((e) => e.type === 'track');
    expect(probe).toBeTruthy();
    expect(probe.context.journey).toBeUndefined();
  });
});
