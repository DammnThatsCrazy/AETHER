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
});
