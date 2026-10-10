import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EventQueue } from '../src/core/event-queue';
import type { AetherEvent } from '../src/types';

// ---------------------------------------------------------------------------
// localStorage stub
// ---------------------------------------------------------------------------

const storage = new Map<string, string>();
const localStorageStub = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value); },
  removeItem: (key: string) => { storage.delete(key); },
  clear: () => { storage.clear(); },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAnalyticsEvent(overrides?: Partial<AetherEvent>): AetherEvent {
  return {
    type: 'track',
    event: 'button_click',
    anonymousId: 'anon-1',
    timestamp: new Date().toISOString(),
    messageId: 'msg-1',
    properties: { category: 'ui' },
    ...overrides,
  } as AetherEvent;
}

function makeConsentEvent(): AetherEvent {
  return {
    type: 'consent',
    anonymousId: 'anon-1',
    timestamp: new Date().toISOString(),
    messageId: 'msg-consent',
  } as unknown as AetherEvent;
}

function makeQueue(opts?: Partial<ConstructorParameters<typeof EventQueue>[0]>) {
  return new EventQueue({
    endpoint: 'https://api.test',
    apiKey: 'test-key',
    batchSize: 10,
    flushInterval: 60_000,
    maxQueueSize: 100,
    ...opts,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('consent-gating', () => {
  const originalFetch = globalThis.fetch;
  const originalLocalStorage = (globalThis as Record<string, unknown>).localStorage;

  beforeEach(() => {
    storage.clear();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: localStorageStub,
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: originalLocalStorage,
    });
    vi.useRealTimers();
  });

  // -------------------------------------------------------------------------
  // GDPR mode — events dropped when consent not granted
  // -------------------------------------------------------------------------

  it('analytics events are dropped when analytics consent is not granted (GDPR mode)', async () => {
    const q = makeQueue();
    // Simulate GDPR mode with all consent revoked
    q.setConsent({
      analytics: false,
      marketing: false,
      web3: false,
      agent: false,
      commerce: false,
      updatedAt: '',
      policyVersion: '',
    });
    q.enqueue(makeAnalyticsEvent());

    let fetched = false;
    globalThis.fetch = vi.fn(async () => {
      fetched = true;
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    // No allowed events in batch → fetch never called
    expect(fetched).toBe(false);
    q.destroy();
  });

  it('commerce events are dropped when commerce consent is not granted', async () => {
    const q = makeQueue();
    q.setConsent({
      analytics: true,
      marketing: false,
      web3: false,
      agent: false,
      commerce: false,
      updatedAt: '',
      policyVersion: '',
    });
    const commerceEvent = makeAnalyticsEvent({ type: 'payment_initiated' });
    q.enqueue(commerceEvent);

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    const paymentEvent = capturedBatch.find((e) => e.type === 'payment_initiated');
    expect(paymentEvent).toBeUndefined();
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // Consent events always pass through
  // -------------------------------------------------------------------------

  it('consent events always pass through regardless of consent state', async () => {
    const q = makeQueue();
    q.setConsent({
      analytics: false,
      marketing: false,
      web3: false,
      agent: false,
      commerce: false,
      updatedAt: '',
      policyVersion: '',
    });
    q.enqueue(makeConsentEvent());

    let count = 0;
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      count = body.batch?.length ?? 0;
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(count).toBe(1);
    q.destroy();
  });

  it('consent events pass through even when all purposes are revoked', async () => {
    const q = makeQueue();
    q.setConsent({
      analytics: false,
      marketing: false,
      web3: false,
      agent: false,
      commerce: false,
      updatedAt: '',
      policyVersion: '',
    });

    q.enqueue(makeAnalyticsEvent());  // should be dropped
    q.enqueue(makeConsentEvent());    // should pass

    let batchSent: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      batchSent = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(batchSent).toHaveLength(1);
    expect(batchSent[0].type).toBe('consent');
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // Events pass when gdprMode is false (no consent set)
  // -------------------------------------------------------------------------

  it('events pass when no consent state is set (no GDPR mode)', async () => {
    const q = makeQueue();
    // No setConsent() call — default is pass-all
    q.enqueue(makeAnalyticsEvent());

    let count = 0;
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      count = body.batch?.length ?? 0;
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(count).toBe(1);
    q.destroy();
  });

  it('events pass when analytics consent is explicitly granted', async () => {
    const q = makeQueue();
    q.setConsent({
      analytics: true,
      marketing: false,
      web3: false,
      agent: false,
      commerce: false,
      updatedAt: '',
      policyVersion: '',
    });
    q.enqueue(makeAnalyticsEvent());

    let count = 0;
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      count = body.batch?.length ?? 0;
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(count).toBe(1);
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // Consent state is stamped on event context
  // -------------------------------------------------------------------------

  it('consent state is stamped on event context before transport', async () => {
    const q = makeQueue();
    const consentState = {
      analytics: true,
      marketing: false,
      web3: false,
      agent: false,
      commerce: true,
      updatedAt: '2026-01-01T00:00:00Z',
      policyVersion: 'v1',
    };
    q.setConsent(consentState);

    // Enqueue an event with consent stamped in context
    const event = makeAnalyticsEvent();
    (event as any).context = { consent: consentState, library: { name: '@aether/web', version: '8.9.0' } };
    q.enqueue(event);

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch).toHaveLength(1);
    const ctx = (capturedBatch[0] as any).context;
    expect(ctx?.consent?.analytics).toBe(true);
    expect(ctx?.consent?.commerce).toBe(true);
    expect(ctx?.consent?.marketing).toBe(false);
    q.destroy();
  });
});
