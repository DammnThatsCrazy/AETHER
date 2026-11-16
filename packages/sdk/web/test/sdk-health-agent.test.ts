import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SDKHealthAgent } from '../src/health/sdk-health-agent';

// Minimal EventQueue stand-in — the agent only reads `.size`.
const fakeQueue = { size: 3 } as unknown as import('../src/core/event-queue').EventQueue;

describe('SDKHealthAgent', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('merges custom headers and reports dynamic state in heartbeats', async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    globalThis.fetch = vi.fn(async (url: unknown, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return { ok: true, status: 200, json: async () => ({ data: null }) } as Response;
    }) as unknown as typeof fetch;

    const agent = new SDKHealthAgent(
      {
        endpoint: 'https://api.test',
        apiKey: 'k',
        sdkId: 'web_test',
        customHeaders: { 'X-Gateway-Token': 'gw-123' },
        getDynamicState: () => ({ authValid: true, consentValid: false, walletConnected: true }),
      },
      fakeQueue,
    );

    await agent.sendHeartbeat();

    const hb = calls.find(c => c.url.includes('/v1/diagnostics/sdk/heartbeat'));
    expect(hb).toBeDefined();
    const headers = hb!.init!.headers as Record<string, string>;
    expect(headers['X-Gateway-Token']).toBe('gw-123');
    expect(headers['Authorization']).toBe('Bearer k');

    const body = JSON.parse(hb!.init!.body as string);
    expect(body.queue_depth).toBe(3);
    expect(body.consent_valid).toBe(false);
    expect(body.wallet_connected).toBe(true);
  });

  it('includes custom headers on the manifest fetch', async () => {
    const calls: string[] = [];
    const headerSpy: Record<string, string>[] = [];
    globalThis.fetch = vi.fn(async (url: unknown, init?: RequestInit) => {
      calls.push(String(url));
      if (init?.headers) headerSpy.push(init.headers as Record<string, string>);
      return { ok: true, status: 200, json: async () => ({ data: null }) } as Response;
    }) as unknown as typeof fetch;

    const agent = new SDKHealthAgent(
      { endpoint: 'https://api.test', apiKey: 'k', sdkId: 'web_test', customHeaders: { 'X-Gateway-Token': 'gw-123' } },
      fakeQueue,
    );

    await agent.fetchManifest();

    const idx = calls.findIndex(u => u.includes('/v1/config/sdk/manifest'));
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(headerSpy[idx]['X-Gateway-Token']).toBe('gw-123');
  });

  it('forwards the event queue\'s drop counters and credential-pause state', () => {
    const queue = {
      size: 2,
      getDiagnostics: () => ({
        droppedEvents: {
          consent_denied: 1, schema_invalid: 0, queue_full: 4, offline_expired: 0, retry_exhausted: 0,
          manifest_blocked: 0, unsupported_sdk_version: 0, payload_too_large: 0, auth_failed: 0, shutdown_unflushed: 0,
        },
        queueDepth: 2,
        lastFlushStatus: 'pending',
        authPaused: true,
      }),
    } as unknown as import('../src/core/event-queue').EventQueue;
    const agent = new SDKHealthAgent(
      { endpoint: 'https://api.test', apiKey: 'k', sdkId: 'web_test' },
      queue,
    );

    const d = agent.getDiagnostics();
    expect(d.droppedEvents.queue_full).toBe(4);
    expect(d.droppedEvents.consent_denied).toBe(1);
    expect(d.authPaused).toBe(true);
    expect(d.queueDepth).toBe(2);
  });

  it('reports queue evictions in the fleet heartbeat', async () => {
    const { EventQueue } = await import('../src/core/event-queue');
    const queue = new EventQueue({
      endpoint: 'https://api.test', apiKey: 'k', maxQueueSize: 1, batchSize: 1000, flushInterval: 1e9,
    });
    for (let i = 0; i < 3; i++) {
      queue.enqueue({ type: 'track', event: 'e', anonymousId: 'a', timestamp: new Date().toISOString(), properties: {} } as never);
    }
    const bodies: Record<string, unknown>[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.body) bodies.push(JSON.parse(init.body as string));
      return { ok: true, status: 200, json: async () => ({ data: null }) } as Response;
    }) as unknown as typeof fetch;

    const agent = new SDKHealthAgent({ endpoint: 'https://api.test', apiKey: 'k', sdkId: 'web_test' }, queue);
    await agent.sendHeartbeat();

    const hb = bodies.find((b) => 'dropped_events' in b)!;
    expect(hb.dropped_events).toBe(2);
    expect((hb.dropped_event_counts as Record<string, number>).queue_full).toBe(2);
    queue.destroy();
  });

  it('does not apply a manifest that arrives after the agent stopped', async () => {
    let respond!: (r: Response) => void;
    globalThis.fetch = vi.fn((url: unknown) => {
      if (String(url).includes('/v1/config/sdk/manifest')) {
        return new Promise<Response>((resolve) => { respond = resolve; });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: null }) } as Response);
    }) as unknown as typeof fetch;

    const agent = new SDKHealthAgent({ endpoint: 'https://api.test', apiKey: 'k', sdkId: 'web_test' }, fakeQueue);
    const applied = vi.fn();
    agent.onManifestUpdate(applied);
    const pending = agent.fetchManifest();  // request in flight
    agent.stop();                           // e.g. the SDK restarts for a new key
    respond({
      ok: true,
      status: 200,
      json: async () => ({ data: { manifest_version: 'v2', features: { analytics: false }, rollout_percentage: 100 } }),
    } as unknown as Response);
    await pending;

    expect(applied).not.toHaveBeenCalled();
  });
});
