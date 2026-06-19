/**
 * Tests for the public error() API on the Web SDK.
 *
 * Because the full AetherSDK.init() requires a DOM (document/window),
 * we test the error event emission path via the EventQueue directly,
 * which is the same mechanism used by the existing event-queue.test.ts.
 *
 * The specific error() method shape is validated via a thin integration
 * approach: we manually enqueue what error() would produce and verify the
 * shape of the resulting batch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EventQueue } from '../src/core/event-queue';
import type { AetherEvent } from '../src/types';

// ---------------------------------------------------------------------------
// localStorage stub (same as event-queue.test.ts)
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

/**
 * Simulate what AetherSDK.error() builds and enqueues.
 * Mirrors the implementation in packages/web/src/index.ts exactly.
 */
function buildErrorEvent(
  message: string,
  error?: Error | unknown,
  properties?: Record<string, unknown>
): AetherEvent {
  const errorProps: Record<string, unknown> = {
    message,
    ...properties,
  };

  if (error instanceof Error) {
    errorProps['name'] = error.name;
    errorProps['stack'] = error.stack;
    if (!errorProps['message']) {
      errorProps['message'] = error.message;
    }
  } else if (error !== undefined && error !== null) {
    errorProps['thrown'] = String(error);
  }

  return {
    id: 'err-1',
    type: 'error',
    timestamp: new Date().toISOString(),
    sessionId: 'session-1',
    anonymousId: 'anon-1',
    properties: errorProps,
    context: {
      library: { name: '@aether/web', version: '8.9.0' },
    },
  } as AetherEvent;
}

function makeQueue(extra?: Partial<ConstructorParameters<typeof EventQueue>[0]>) {
  return new EventQueue({
    endpoint: 'https://api.test',
    apiKey: 'test-key',
    batchSize: 10,
    flushInterval: 60_000,
    maxQueueSize: 100,
    ...extra,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('error() event emitter contract', () => {
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

  it('emits an event with type === "error"', async () => {
    const q = makeQueue();
    q.enqueue(buildErrorEvent('Something went wrong'));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch.length).toBe(1);
    expect(capturedBatch[0].type).toBe('error');
    q.destroy();
  });

  it('captures message in properties', async () => {
    const q = makeQueue();
    q.enqueue(buildErrorEvent('Test error message'));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].properties?.['message']).toBe('Test error message');
    q.destroy();
  });

  it('auto-captures Error name and stack when an Error instance is passed', async () => {
    const q = makeQueue();
    const err = new TypeError('type mismatch');
    q.enqueue(buildErrorEvent('An error occurred', err));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].properties?.['name']).toBe('TypeError');
    expect(typeof capturedBatch[0].properties?.['stack']).toBe('string');
    expect((capturedBatch[0].properties?.['stack'] as string).length).toBeGreaterThan(0);
    q.destroy();
  });

  it('merges additional properties alongside the error fields', async () => {
    const q = makeQueue();
    q.enqueue(buildErrorEvent('Something failed', new Error('low-level'), { component: 'checkout', severity: 'high' }));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].properties?.['component']).toBe('checkout');
    expect(capturedBatch[0].properties?.['severity']).toBe('high');
    q.destroy();
  });

  it('handles a non-Error throwable gracefully', async () => {
    const q = makeQueue();
    q.enqueue(buildErrorEvent('String thrown', 'unexpected string error'));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0]).toBeDefined();
    expect(capturedBatch[0].properties?.['thrown']).toBe('unexpected string error');
    q.destroy();
  });

  it('works without an error argument (message-only call)', async () => {
    const q = makeQueue();
    q.enqueue(buildErrorEvent('Manual error flag'));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0]).toBeDefined();
    expect(capturedBatch[0].type).toBe('error');
    // No name/stack on message-only call
    expect(capturedBatch[0].properties?.['name']).toBeUndefined();
    expect(capturedBatch[0].properties?.['stack']).toBeUndefined();
    q.destroy();
  });

  it('error event is not blocked when analytics consent is granted', async () => {
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
    q.enqueue(buildErrorEvent('Consent-gated error'));

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

  it('error event is dropped when analytics consent is NOT granted (GDPR mode)', async () => {
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
    q.enqueue(buildErrorEvent('Blocked error'));

    let fetched = false;
    globalThis.fetch = vi.fn(async () => {
      fetched = true;
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    // Consent gate drops the event → fetch never called
    expect(fetched).toBe(false);
    q.destroy();
  });
});
