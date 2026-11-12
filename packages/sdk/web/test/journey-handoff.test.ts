// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import aether from '../src/index';

interface Call { url: string; body: any; headers: Record<string, string> }

function installFetch(responder: (url: string, body: any) => { ok: boolean; json?: unknown }) {
  const calls: Call[] = [];
  const batches: Array<{ type: string; properties?: Record<string, unknown> }> = [];
  globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = String(url);
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    if (body && Array.isArray(body.batch)) {
      batches.push(...body.batch);
      return { ok: true, status: 200, json: async () => ({ accepted: 1, duplicates: 0, rejected: 0, events: [] }), text: async () => '{}' } as Response;
    }
    calls.push({ url: u, body, headers: (init?.headers ?? {}) as Record<string, string> });
    const r = responder(u, body);
    return { ok: r.ok, status: r.ok ? 200 : 404, json: async () => r.json ?? {}, text: async () => '{}' } as Response;
  });
  return { calls, batches };
}

function initialize() {
  aether.init({
    apiKey: 'test-key',
    endpoint: 'https://api.test',
    advanced: { batchSize: 200, flushInterval: 60_000 },
    modules: { autoDiscovery: false, performance: false, ecommerce: false },
  });
  aether.consent.grant(['analytics', 'marketing']);
}

const LINK = {
  handoff_id: 'hof_1', journey_id: 'journey-9', link_basis: 'explicit_handoff',
  identity_merge: 'not_performed',
  from: { session_id: 'mob-1', anonymous_id: 'anon-m', platform: 'ios' },
  to: { session_id: 'web-1', anonymous_id: 'anon-w', platform: 'web' },
  redeemed_at: '2026-10-23T10:00:00Z',
};

describe('journey handoff', () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { aether.destroy(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/'); });

  it('creates a token for the active journey using the session and anonymous ids', async () => {
    const { calls } = installFetch(() => ({ ok: true, json: { data: { token: 'hnd_abc', handoff_id: 'hof_1', expires_at: '2026-10-23T10:10:00Z' } } }));
    initialize();
    aether.startJourney('checkout', { journeyId: 'journey-9' });
    const out = await aether.createJourneyHandoff({ ttlSeconds: 120 });
    expect(out).toEqual({ token: 'hnd_abc', handoffId: 'hof_1', expiresAt: '2026-10-23T10:10:00Z' });
    const call = calls.find((c) => c.url.endsWith('/sdk/journey-handoff'))!;
    expect(call.headers['x-api-key']).toBe('test-key');
    expect(call.body).toMatchObject({ journey_id: 'journey-9', platform: 'web', ttl_seconds: 120 });
    expect(call.body.session_id).toBeTruthy();
    expect(call.body.anonymous_id).toBeTruthy();
  });

  it('returns null without an active journey or on a refusal, never throwing', async () => {
    installFetch(() => ({ ok: false }));
    initialize();
    expect(await aether.createJourneyHandoff()).toBeNull();
    aether.startJourney('checkout', { journeyId: 'j' });
    expect(await aether.createJourneyHandoff()).toBeNull();
    globalThis.fetch = vi.fn(async () => { throw new Error('offline'); }) as any;
    expect(await aether.createJourneyHandoff()).toBeNull();
  });

  it('redeems a token, continues the journey, and reports an explicit, non-merging link', async () => {
    const { calls, batches } = installFetch(() => ({ ok: true, json: { data: LINK } }));
    initialize();
    const link = await aether.redeemJourneyHandoff('hnd_abc');
    expect(link).toMatchObject({
      handoffId: 'hof_1', journeyId: 'journey-9', linkBasis: 'explicit_handoff', identityMerge: 'not_performed',
    });
    expect(link?.from.platform).toBe('ios');
    expect(calls.find((c) => c.url.endsWith('/redeem'))!.body).toMatchObject({ token: 'hnd_abc', platform: 'web' });
    expect(aether.getCurrentJourney()?.journeyId).toBe('journey-9');
    await aether.flush();
    const resumed = batches.find((e) => e.type === 'journey_resumed' || e.properties?.journeyEventType === 'journey_resumed');
    expect(JSON.stringify(resumed)).toContain('explicit_handoff');
  });

  it('returns null for a rejected token and leaves the journey untouched', async () => {
    installFetch(() => ({ ok: false }));
    initialize();
    aether.startJourney('checkout', { journeyId: 'keep-me' });
    expect(await aether.redeemJourneyHandoff('hnd_bad')).toBeNull();
    expect(aether.getCurrentJourney()?.journeyId).toBe('keep-me');
  });

  it('rejects a malformed server answer instead of trusting it', async () => {
    installFetch(() => ({ ok: true, json: { data: { ...LINK, link_basis: 'inferred' } } }));
    initialize();
    expect(await aether.redeemJourneyHandoff('hnd_abc')).toBeNull();
  });

  it('strips the token from the URL before redeeming it', async () => {
    const { calls } = installFetch(() => ({ ok: true, json: { data: LINK } }));
    window.history.replaceState({}, '', '/landing?utm=x&aether_handoff=hnd_from_url');
    initialize();
    const link = await aether.redeemJourneyHandoffFromUrl();
    expect(link?.journeyId).toBe('journey-9');
    expect(calls.find((c) => c.url.endsWith('/redeem'))!.body.token).toBe('hnd_from_url');
    expect(window.location.search).toBe('?utm=x');
    expect(await aether.redeemJourneyHandoffFromUrl()).toBeNull();
  });
});
