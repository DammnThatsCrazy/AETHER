/**
 * Journey lifecycle event contract tests.
 *
 * We test the journey event shapes and consent gates via two approaches:
 *
 * 1. EventQueue-level: enqueue pre-built journey events and verify they
 *    flush correctly (same pattern as event-queue.test.ts and consent-gating.test.ts).
 *
 * 2. Shared contract: import EVENT_CONSENT_PURPOSE to verify every journey
 *    event type is analytics-gated.
 *
 * This avoids the DOM requirement of AetherSDK.init() while still testing
 * the real queue and consent logic paths.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EventQueue } from '../src/core/event-queue';
import type { AetherEvent } from '../src/types';
import { EVENT_CONSENT_PURPOSE, EVENT_FAMILY } from '../../shared/events';

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

const JOURNEY_ID = 'jrn-test-42';

function makeJourneyEvent(
  type: string,
  props: Record<string, unknown> = {}
): AetherEvent {
  return {
    id: `evt-${type}`,
    type,
    timestamp: new Date().toISOString(),
    sessionId: 'session-1',
    anonymousId: 'anon-1',
    properties: {
      journeyId: JOURNEY_ID,
      journeyStatus: type.replace('journey_', ''),
      ...props,
    },
    context: {
      library: { name: '@aether/web', version: '8.9.0' },
    },
  } as unknown as AetherEvent;
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

describe('journey lifecycle events', () => {
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
  // journey_started
  // -------------------------------------------------------------------------

  it('journey_started emits with journeyId and journeyStatus="started"', async () => {
    const q = makeQueue();
    q.enqueue(makeJourneyEvent('journey_started'));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch).toHaveLength(1);
    expect(capturedBatch[0].type).toBe('journey_started');
    expect(capturedBatch[0].properties?.['journeyStatus']).toBe('started');
    expect(capturedBatch[0].properties?.['journeyId']).toBe(JOURNEY_ID);
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // journey_paused
  // -------------------------------------------------------------------------

  it('journey_paused emits with pauseReason in properties', async () => {
    const q = makeQueue();
    q.enqueue(makeJourneyEvent('journey_paused', { pauseReason: 'page_hidden' }));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].type).toBe('journey_paused');
    expect(capturedBatch[0].properties?.['journeyStatus']).toBe('paused');
    expect(capturedBatch[0].properties?.['pauseReason']).toBe('page_hidden');
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // journey_resumed
  // -------------------------------------------------------------------------

  it('journey_resumed emits with journeyStatus="resumed"', async () => {
    const q = makeQueue();
    q.enqueue(makeJourneyEvent('journey_resumed', { resumeReason: 'page_visible' }));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].type).toBe('journey_resumed');
    expect(capturedBatch[0].properties?.['journeyStatus']).toBe('resumed');
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // journey_completed
  // -------------------------------------------------------------------------

  it('journey_completed emits with completionReason in properties', async () => {
    const q = makeQueue();
    q.enqueue(makeJourneyEvent('journey_completed', { completionReason: 'order_confirmed' }));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].type).toBe('journey_completed');
    expect(capturedBatch[0].properties?.['completionReason']).toBe('order_confirmed');
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // journey_abandoned
  // -------------------------------------------------------------------------

  it('journey_abandoned emits with abandonmentReason in properties', async () => {
    const q = makeQueue();
    q.enqueue(makeJourneyEvent('journey_abandoned', { abandonmentReason: 'user_left' }));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].type).toBe('journey_abandoned');
    expect(capturedBatch[0].properties?.['abandonmentReason']).toBe('user_left');
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // journey_checkpoint
  // -------------------------------------------------------------------------

  it('journey_checkpoint emits with journeyStatus="checkpoint"', async () => {
    const q = makeQueue();
    q.enqueue(makeJourneyEvent('journey_checkpoint', { stepId: 'step-2' }));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch[0].type).toBe('journey_checkpoint');
    expect(capturedBatch[0].properties?.['journeyStatus']).toBe('checkpoint');
    q.destroy();
  });

  // -------------------------------------------------------------------------
  // Consent gate — all journey events are analytics-gated
  // -------------------------------------------------------------------------

  it('each journey event type is gated behind analytics consent', () => {
    const journeyTypes = [
      'journey_started',
      'journey_paused',
      'journey_resumed',
      'journey_continued',
      'journey_completed',
      'journey_abandoned',
      'journey_checkpoint',
    ] as const;

    for (const t of journeyTypes) {
      expect(EVENT_CONSENT_PURPOSE[t]).toBe('analytics');
    }
  });

  it('each journey event type is in the journey family', () => {
    const journeyTypes = [
      'journey_started',
      'journey_paused',
      'journey_resumed',
      'journey_continued',
      'journey_completed',
      'journey_abandoned',
      'journey_checkpoint',
    ] as const;

    for (const t of journeyTypes) {
      expect(EVENT_FAMILY[t]).toBe('journey');
    }
  });

  it('journey events are dropped when analytics consent is not granted', async () => {
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
    q.enqueue(makeJourneyEvent('journey_started'));

    let fetched = false;
    globalThis.fetch = vi.fn(async () => {
      fetched = true;
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(fetched).toBe(false);
    q.destroy();
  });

  it('journey events pass through when analytics consent is granted', async () => {
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
    q.enqueue(makeJourneyEvent('journey_completed'));

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
  // Multiple journey events carry same journeyId
  // -------------------------------------------------------------------------

  it('multiple lifecycle events carry the same journeyId', async () => {
    const q = makeQueue();
    q.enqueue(makeJourneyEvent('journey_started'));
    q.enqueue(makeJourneyEvent('journey_checkpoint', { stepId: 'step-1' }));
    q.enqueue(makeJourneyEvent('journey_completed', { completionReason: 'done' }));

    let capturedBatch: AetherEvent[] = [];
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      const body = JSON.parse((init?.body as string) ?? '{}');
      capturedBatch = body.batch ?? [];
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    await q.flush();
    expect(capturedBatch).toHaveLength(3);
    const ids = capturedBatch.map((e) => e.properties?.['journeyId']);
    expect(new Set(ids).size).toBe(1);
    expect(ids[0]).toBe(JOURNEY_ID);
    q.destroy();
  });
});
