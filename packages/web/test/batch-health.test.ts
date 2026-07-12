// Truth Kernel §2.8 — per-batch ingestion health counters.
// The EventQueue must surface accepted / duplicate / rejected (parsed from the
// backend BatchResponse) plus SDK-side dropped_by_consent and queue_depth via
// the onBatchResult callback.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EventQueue, type BatchHealth } from '../src/core/event-queue';
import type { AetherEvent, ConsentState } from '../src/types';

function makeConsent(overrides: Partial<ConsentState> = {}): ConsentState {
  return {
    analytics: false, marketing: false, personalization: false, web3: false,
    agent: false, commerce: false, financial_activity: false, credit: false,
    location: false, economic_observability: false, cross_chain_observability: false,
    updatedAt: '2026-01-01T00:00:00.000Z', policyVersion: '1.0',
    ...overrides,
  } as ConsentState;
}

function ev(type: string, properties: Record<string, unknown> = {}): AetherEvent {
  return {
    id: `id-${Math.random().toString(16).slice(2)}`,
    type: type as AetherEvent['type'],
    timestamp: new Date().toISOString(),
    anonymousId: 'anon-1',
    sessionId: 'sess-1',
    properties,
  } as unknown as AetherEvent;
}

describe('EventQueue — batch health (§2.8)', () => {
  let queues: EventQueue[] = [];

  beforeEach(() => {
    queues = [];
    (globalThis as unknown as { localStorage?: unknown }).localStorage = undefined;
  });

  afterEach(() => {
    queues.forEach((q) => q.destroy());
    vi.restoreAllMocks();
  });

  function newQueue(onBatchResult: (h: BatchHealth) => void): EventQueue {
    const q = new EventQueue({
      endpoint: 'https://api.test',
      apiKey: 'k',
      batchSize: 10,
      flushInterval: 60_000,
      onBatchResult,
    });
    queues.push(q);
    return q;
  }

  it('parses accepted / duplicate / rejected from the /v1/batch response', async () => {
    (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ accepted: 2, duplicates: 1, rejected: 0 }),
    }));

    const results: BatchHealth[] = [];
    const q = newQueue((h) => results.push(h));
    q.setConsent(makeConsent({ analytics: true }));
    q.enqueue(ev('page'));
    q.enqueue(ev('page'));
    q.enqueue(ev('page'));
    await q.flush();

    expect(results).toHaveLength(1);
    expect(results[0].accepted).toBe(2);
    // The backend uses the plural `duplicates`; BatchHealth normalizes it.
    expect(results[0].duplicate).toBe(1);
    expect(results[0].rejected).toBe(0);
    expect(results[0].queue_depth).toBe(0);
  });

  it('increments dropped_by_consent when consent gating removes events', async () => {
    (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ accepted: 1, duplicates: 0, rejected: 0 }),
    }));

    const results: BatchHealth[] = [];
    const q = newQueue((h) => results.push(h));
    // analytics granted, web3 NOT granted → the wallet event must be consent-dropped.
    q.setConsent(makeConsent({ analytics: true }));
    q.enqueue(ev('page'));       // analytics → allowed
    q.enqueue(ev('wallet'));     // web3 → dropped_by_consent
    await q.flush();

    expect(results).toHaveLength(1);
    expect(results[0].dropped_by_consent).toBe(1);
    expect(results[0].accepted).toBe(1);
  });

  it('reports dropped_by_consent even when the whole batch is consent-dropped (no network call)', async () => {
    const fetchMock = vi.fn();
    (globalThis as unknown as { fetch: unknown }).fetch = fetchMock;

    const results: BatchHealth[] = [];
    const q = newQueue((h) => results.push(h));
    q.setConsent(makeConsent()); // nothing granted
    q.enqueue(ev('page'));
    q.enqueue(ev('page'));
    await q.flush();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(results).toHaveLength(1);
    expect(results[0].dropped_by_consent).toBe(2);
    expect(results[0].accepted).toBe(0);
  });
});
