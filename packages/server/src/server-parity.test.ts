// Phase E — server SDK parity: canonical-type enforcement, surface stamping,
// and cyclic/deep-safe recursive scrubbing.
import { describe, it, expect, vi, afterEach } from 'vitest';

import { AetherServerSDK, scrubSensitiveFields } from './index';

function captureFetch(): { bodies: any[] } {
  const bodies: any[] = [];
  (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async (_url: string, init?: any) => {
    if (init?.body) {
      try { bodies.push(JSON.parse(init.body)); } catch { /* ignore */ }
    }
    return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ accepted: 1, duplicates: 0, rejected: 0 }) };
  });
  return { bodies };
}

describe('server SDK — canonical event-type enforcement', () => {
  afterEach(() => vi.restoreAllMocks());

  it('queues a canonical event type', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => { /* silence */ });
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch' });
    sdk.track({ type: 'api_request_observed', properties: { path: '/x' } });
    expect(sdk.healthSnapshot().eventsQueued).toBe(1);
    expect(warn).not.toHaveBeenCalled();
    sdk.shutdown();
  });

  it('drops a non-canonical event type (not queued) and warns', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => { /* silence */ });
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch' });
    sdk.track({ type: 'totally_made_up_event', properties: { a: 1 } });
    expect(sdk.healthSnapshot().eventsQueued).toBe(0);
    expect(warn).toHaveBeenCalledOnce();
    expect(String(warn.mock.calls[0][0])).toContain('totally_made_up_event');
    sdk.shutdown();
  });

  it('the built-in typed emitters all use canonical types (none dropped)', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => { /* silence */ });
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch' });
    sdk.observe.apiRequest({ method: 'GET', path: '/x', statusCode: 200, durationMs: 5 });
    sdk.observe.job({ jobType: 'nightly', status: 'completed' });
    sdk.observe.connectorSync({ connectorId: 'c1', status: 'started' });
    sdk.observe.rateLimit({ path: '/x', limitType: 'ip', retryAfterMs: 100 });
    sdk.observe.dependencyFailure({ dependency: 'db', errorCode: 'ETIMEDOUT' });
    sdk.observe.webhookDelivery({ webhookId: 'w1', event: 'x', statusCode: 200, durationMs: 3, attempt: 1 });
    expect(sdk.healthSnapshot().eventsQueued).toBe(6);
    sdk.shutdown();
  });
});

describe('server SDK — surface stamping', () => {
  afterEach(() => vi.restoreAllMocks());

  it("stamps context.surface = 'server' on every event", async () => {
    const { bodies } = captureFetch();
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch', consent: { analytics: true } });
    sdk.track({ type: 'api_request_observed', properties: { path: '/x' } });
    await sdk.flush();
    await sdk.shutdown();
    const evt = bodies[0].batch[0];
    expect(evt.context.surface).toBe('server');
    expect(evt.context.timeZoneSource).toBe('server');
  });

  it('caller-supplied surface wins over the default', async () => {
    const { bodies } = captureFetch();
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch' });
    sdk.track({ type: 'api_request_observed', context: { surface: 'edge-worker' } });
    await sdk.flush();
    await sdk.shutdown();
    expect(bodies[0].batch[0].context.surface).toBe('edge-worker');
  });

  it('stamps a monotonically increasing context.sequence.event', async () => {
    const { bodies } = captureFetch();
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch' });
    sdk.track({ type: 'api_request_observed', properties: { path: '/a' } });
    sdk.track({ type: 'api_request_observed', properties: { path: '/b' } });
    await sdk.flush();
    await sdk.shutdown();
    const events = bodies.flatMap((b) => b.batch);
    expect(events).toHaveLength(2);
    expect(events[0].context.sequence.event).toBe(0);
    expect(events[1].context.sequence.event).toBe(1);
  });

  it('stamps schemaVersion from the shared contract and a real host OS identity', async () => {
    const { bodies } = captureFetch();
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch' });
    sdk.track({ type: 'api_request_observed' });
    await sdk.flush();
    await sdk.shutdown();
    const ctx = bodies[0].batch[0].context;
    expect(ctx.schemaVersion).toBe('1.0.0');
    expect(typeof ctx.operatingSystem.name).toBe('string');
    expect(ctx.operatingSystem.name.length).toBeGreaterThan(0);
    expect(typeof ctx.operatingSystem.version).toBe('string');
  });

  it('stamps application identity from config, omits it when not configured', async () => {
    const { bodies } = captureFetch();
    const withApp = new AetherServerSDK({
      writeKey: 'sk', endpoint: 'https://api.test/v1/batch',
      application: { name: 'billing-svc', version: '3.2.1', environment: 'production' },
    });
    withApp.track({ type: 'api_request_observed' });
    await withApp.flush();
    await withApp.shutdown();
    expect(bodies[0].batch[0].context.application).toEqual({
      name: 'billing-svc', version: '3.2.1', environment: 'production',
    });

    const without = new AetherServerSDK({ writeKey: 'sk', endpoint: 'https://api.test/v1/batch' });
    without.track({ type: 'api_request_observed' });
    await without.flush();
    await without.shutdown();
    const bare = bodies[1].batch[0].context;
    expect(bare.application).toBeUndefined();
  });
});

describe('server SDK — recursive scrubber (cycle/depth safe)', () => {
  it('redacts sensitive keys nested in objects and arrays', () => {
    const out = scrubSensitiveFields({
      wallet: { label: 'primary', private_key: 'deadbeef' },
      cards: [{ brand: 'visa', card_number: '4111' }],
    }) as any;
    expect(out.wallet.private_key).toBe('[REDACTED]');
    expect(out.wallet.label).toBe('primary');
    expect(out.cards[0].card_number).toBe('[REDACTED]');
    expect(out.cards[0].brand).toBe('visa');
  });

  it('tolerates a cyclic payload without throwing and still redacts', () => {
    const cyclic: Record<string, unknown> = { secret: 'x' };
    cyclic.self = cyclic;
    let out: any;
    expect(() => { out = scrubSensitiveFields({ ring: cyclic }); }).not.toThrow();
    expect(out.ring.secret).toBe('[REDACTED]');
    expect(out.ring.self).toBe('[CYCLE]');
    // Result must be JSON-serializable (no surviving cycle).
    expect(() => JSON.stringify(out)).not.toThrow();
  });

  it('does not mutate the source object', () => {
    const src = { auth: { password: 'p' } };
    scrubSensitiveFields({ nested: src });
    expect(src.auth.password).toBe('p');
  });
});
