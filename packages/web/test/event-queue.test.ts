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
// helpers
// ---------------------------------------------------------------------------
function makeTrackEvent(overrides?: Partial<Record<string, unknown>>): AetherEvent {
  return {
    type: 'track',
    event: 'test_event',
    anonymousId: 'anon-1',
    timestamp: new Date().toISOString(),
    messageId: 'msg-1',
    properties: { foo: 'bar', ...overrides },
  } as AetherEvent;
}

function makeQueue(extra?: Partial<ConstructorParameters<typeof EventQueue>[0]>) {
  return new EventQueue({
    endpoint: 'https://api.test',
    apiKey: 'test-key',
    batchSize: 10,
    flushInterval: 60_000, // long — don't auto-flush in tests
    maxQueueSize: 100,
    ...extra,
  });
}

describe('EventQueue', () => {
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
  // Basic queue behaviour
  // -------------------------------------------------------------------------

  describe('enqueue / size', () => {
    it('increments size as events are enqueued', () => {
      const q = makeQueue();
      expect(q.size).toBe(0);
      q.enqueue(makeTrackEvent());
      expect(q.size).toBe(1);
      q.enqueue(makeTrackEvent());
      expect(q.size).toBe(2);
      q.destroy();
    });
  });

  // -------------------------------------------------------------------------
  // Sensitive field scrubber
  // -------------------------------------------------------------------------

  describe('sensitive field scrubbing', () => {
    const sensitiveFields = [
      'privatekey', 'private_key',
      'seedphrase', 'seed_phrase',
      'mnemonic',
      'secret', 'secretkey', 'secret_key',
      'password', 'pin',
      'cardnumber', 'card_number',
      'pan', 'cvv', 'cvc', 'cvv2',
      'paymenttoken', 'payment_token',
      'authcode', 'auth_code',
    ];

    for (const field of sensitiveFields) {
      it(`redacts "${field}" from event properties`, () => {
        const q = makeQueue();
        const event = makeTrackEvent({ [field]: 'super-secret-value' });
        q.enqueue(event);

        // Inspect the internal queue via flush — intercept fetch.
        let capturedBatch: AetherEvent[] = [];
        globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
          const body = JSON.parse((init?.body as string) ?? '{}');
          capturedBatch = body.batch;
          return { ok: true, status: 200 } as Response;
        }) as unknown as typeof fetch;

        return q.flush().then(() => {
          expect(capturedBatch).toHaveLength(1);
          const props = capturedBatch[0].properties as Record<string, unknown>;
          expect(props[field]).toBe('[REDACTED]');
          expect(props['foo']).toBe('bar'); // safe fields untouched
          q.destroy();
        });
      });
    }

    it('preserves non-sensitive properties unchanged', () => {
      const q = makeQueue();
      q.enqueue(makeTrackEvent({ userId: 'u1', amount: 100, label: 'checkout' }));

      let capturedBatch: AetherEvent[] = [];
      globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
        const body = JSON.parse((init?.body ?? '{}') as string);
        capturedBatch = body.batch;
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;

      return q.flush().then(() => {
        const props = capturedBatch[0].properties as Record<string, unknown>;
        expect(props['userId']).toBe('u1');
        expect(props['amount']).toBe(100);
        expect(props['label']).toBe('checkout');
        q.destroy();
      });
    });

    it('is case-insensitive (e.g. "Password", "PASSWORD")', () => {
      const q = makeQueue();
      q.enqueue(makeTrackEvent({ Password: 'abc', PASSWORD: 'xyz' }));

      let capturedBatch: AetherEvent[] = [];
      globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
        const body = JSON.parse((init?.body ?? '{}') as string);
        capturedBatch = body.batch;
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;

      return q.flush().then(() => {
        const props = capturedBatch[0].properties as Record<string, unknown>;
        expect(props['Password']).toBe('[REDACTED]');
        expect(props['PASSWORD']).toBe('[REDACTED]');
        q.destroy();
      });
    });

    it('does not mutate the original event object passed to enqueue', () => {
      const q = makeQueue();
      const event = makeTrackEvent({ password: 'original' });
      const originalProps = { ...(event.properties as Record<string, unknown>) };
      q.enqueue(event);
      expect((event.properties as Record<string, unknown>)['password']).toBe(originalProps['password']);
      q.destroy();
    });

    // -----------------------------------------------------------------------
    // Recursive scrubbing — a sensitive key at ANY depth is redacted, not just
    // top-level keys.
    // -----------------------------------------------------------------------

    async function captureFlushed(q: EventQueue): Promise<AetherEvent[]> {
      let capturedBatch: AetherEvent[] = [];
      globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
        const body = JSON.parse((init?.body as string) ?? '{}');
        capturedBatch = body.batch;
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;
      await q.flush();
      return capturedBatch;
    }

    it('redacts a sensitive key nested inside a child object', async () => {
      const q = makeQueue();
      q.enqueue(makeTrackEvent({
        wallet: { label: 'primary', recovery: { mnemonic: 'twelve secret words', note: 'keep' } },
      }));
      const batch = await captureFlushed(q);
      const props = batch[0].properties as Record<string, any>;
      expect(props.wallet.recovery.mnemonic).toBe('[REDACTED]');
      expect(props.wallet.recovery.note).toBe('keep'); // safe sibling untouched
      expect(props.wallet.label).toBe('primary');
      q.destroy();
    });

    it('redacts sensitive keys inside array elements', async () => {
      const q = makeQueue();
      q.enqueue(makeTrackEvent({
        cards: [
          { brand: 'visa', card_number: '4111111111111111' },
          { brand: 'mc', cvv: '123' },
        ],
      }));
      const batch = await captureFlushed(q);
      const props = batch[0].properties as Record<string, any>;
      expect(props.cards[0].card_number).toBe('[REDACTED]');
      expect(props.cards[0].brand).toBe('visa');
      expect(props.cards[1].cvv).toBe('[REDACTED]');
      expect(props.cards[1].brand).toBe('mc');
      q.destroy();
    });

    it('does not mutate a nested source object', async () => {
      const q = makeQueue();
      const original = { auth: { password: 'p@ss' } };
      q.enqueue(makeTrackEvent({ nested: original }));
      await captureFlushed(q);
      expect(original.auth.password).toBe('p@ss'); // source untouched
      q.destroy();
    });

    it('tolerates a cyclic payload without infinite recursion', async () => {
      const q = makeQueue();
      const cyclic: Record<string, unknown> = { secret: 'x' };
      cyclic['self'] = cyclic; // cycle
      q.enqueue(makeTrackEvent({ ring: cyclic }));
      const batch = await captureFlushed(q);
      const props = batch[0].properties as Record<string, any>;
      expect(props.ring.secret).toBe('[REDACTED]');
      q.destroy();
    });
  });

  // -------------------------------------------------------------------------
  // Consent filtering
  // -------------------------------------------------------------------------

  describe('consent filtering', () => {
    it('passes all events when no consent is set', () => {
      const q = makeQueue();
      q.enqueue(makeTrackEvent());

      let count = 0;
      globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
        const body = JSON.parse((init?.body ?? '{}') as string);
        count = body.batch.length;
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;

      return q.flush().then(() => {
        expect(count).toBe(1);
        q.destroy();
      });
    });

    it('drops events when gdprMode=true and analytics consent not granted', () => {
      const q = makeQueue();
      q.setConsent({ analytics: false, marketing: false, web3: false, agent: false, commerce: false, updatedAt: '', policyVersion: '' });
      q.enqueue(makeTrackEvent());

      let fetched = false;
      globalThis.fetch = vi.fn(async () => {
        fetched = true;
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;

      return q.flush().then(() => {
        // Consent filtering empties allowed batch → fetch never called
        expect(fetched).toBe(false);
        q.destroy();
      });
    });

    it('passes events when analytics consent is granted', () => {
      const q = makeQueue();
      q.setConsent({ analytics: true, marketing: false, web3: false, agent: false, commerce: false, updatedAt: '', policyVersion: '' });
      q.enqueue(makeTrackEvent());

      let count = 0;
      globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
        const body = JSON.parse((init?.body ?? '{}') as string);
        count = body.batch.length;
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;

      return q.flush().then(() => {
        expect(count).toBe(1);
        q.destroy();
      });
    });

    it('never blocks consent events regardless of consent state', () => {
      const q = makeQueue();
      q.setConsent({ analytics: false, marketing: false, web3: false, agent: false, commerce: false, updatedAt: '', policyVersion: '' });
      q.enqueue({ type: 'consent', anonymousId: 'a', timestamp: '', messageId: 'm' } as unknown as AetherEvent);

      let count = 0;
      globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
        const body = JSON.parse((init?.body ?? '{}') as string);
        count = body.batch.length;
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;

      return q.flush().then(() => {
        expect(count).toBe(1);
        q.destroy();
      });
    });
  });

  // -------------------------------------------------------------------------
  // Retry / error path
  // -------------------------------------------------------------------------

  describe('retry on 5xx', () => {
    it('retries on 500 and succeeds on second attempt', async () => {
      // Use real timers so the 1 ms sleep in sendBatch actually resolves.
      vi.useRealTimers();
      const q = makeQueue({ retry: { maxRetries: 2, baseDelay: 1, maxDelay: 10, backoffMultiplier: 1 } });
      q.enqueue(makeTrackEvent());

      let calls = 0;
      globalThis.fetch = vi.fn(async () => {
        calls++;
        if (calls === 1) return { ok: false, status: 500, statusText: 'Internal Server Error', headers: new Headers() } as Response;
        // Second attempt is a CONFIRMED success (real counters body) — this
        // test is about the 500-then-succeed retry path, not the separate
        // ambiguous-2xx path covered below.
        return { ok: true, status: 200, json: async () => ({ accepted: 1, duplicate: 0, rejected: 0 }) } as unknown as Response;
      }) as unknown as typeof fetch;

      await q.flush();
      expect(calls).toBe(2);
      expect(q.size).toBe(0);
      q.destroy();
    });

    it('drops a terminal 4xx (poison) so it cannot block the queue head', async () => {
      let errorFired = false;
      const q = makeQueue({
        onError: () => { errorFired = true; },
        retry: { maxRetries: 0, baseDelay: 1, maxDelay: 1, backoffMultiplier: 1 },
      });
      q.enqueue(makeTrackEvent());

      globalThis.fetch = vi.fn(async () => (
        { ok: false, status: 400, statusText: 'Bad Request', headers: new Headers() } as Response
      )) as unknown as typeof fetch;

      await q.flush();
      // 400 is a terminal rejection: surfaced via onError and DROPPED (not
      // re-queued), so one permanently-rejected batch can't block later events.
      expect(errorFired).toBe(true);
      expect(q.size).toBe(0);
      q.destroy();
    });

    it('re-queues a transient 5xx failure for a later retry', async () => {
      let errorFired = false;
      const q = makeQueue({
        onError: () => { errorFired = true; },
        retry: { maxRetries: 0, baseDelay: 1, maxDelay: 1, backoffMultiplier: 1 },
      });
      q.enqueue(makeTrackEvent());

      globalThis.fetch = vi.fn(async () => (
        { ok: false, status: 503, statusText: 'Service Unavailable', headers: new Headers() } as Response
      )) as unknown as typeof fetch;

      await q.flush();
      // 5xx is transient: the batch returns to the head, not dropped.
      expect(errorFired).toBe(true);
      expect(q.size).toBe(1);
      q.destroy();
    });
  });

  // -------------------------------------------------------------------------
  // Ambiguous 2xx (no parseable delivery counters) — web ids are stable
  // (minted once per event in enqueueEvent(), never regenerated on
  // requeue/retry — see packages/web/src/index.ts), so the backend safely
  // dedups a resend. A counter-less 2xx must therefore be treated as
  // UNCONFIRMED delivery: not credited, and retried — never dropped, and
  // never optimistically counted as accepted. This aligns the web SDK with
  // the server SDK's identical fix (packages/server/src/index.ts flush()).
  // -------------------------------------------------------------------------

  describe('ambiguous 2xx (no parseable delivery counters)', () => {
    it('does not credit a 2xx with a missing/non-JSON body, and retains the batch for retry', async () => {
      let errorFired = false;
      let batchResultCalls = 0;
      const q = makeQueue({
        onError: () => { errorFired = true; },
        onBatchResult: () => { batchResultCalls++; },
        retry: { maxRetries: 0, baseDelay: 1, maxDelay: 1, backoffMultiplier: 1 },
      });
      q.enqueue(makeTrackEvent());

      // `ok: true` with no `json` method at all — same shape used elsewhere
      // in this file for a bare 2xx, but now must NOT be optimistically
      // credited.
      globalThis.fetch = vi.fn(async () => (
        { ok: true, status: 200 } as Response
      )) as unknown as typeof fetch;

      await q.flush();
      // Unconfirmed delivery: surfaced via onError, NEVER counted as
      // delivered (onBatchResult only fires on a confirmed outcome), and the
      // batch is retained (requeued) rather than dropped like a poison 4xx.
      expect(errorFired).toBe(true);
      expect(batchResultCalls).toBe(0);
      expect(q.size).toBe(1);
      q.destroy();
    });

    it('does not credit a 2xx whose JSON body carries no accepted/duplicate/rejected keys', async () => {
      let errorFired = false;
      const q = makeQueue({
        onError: () => { errorFired = true; },
        retry: { maxRetries: 0, baseDelay: 1, maxDelay: 1, backoffMultiplier: 1 },
      });
      q.enqueue(makeTrackEvent());

      // Parseable JSON, but none of the known counter keys — still ambiguous.
      globalThis.fetch = vi.fn(async () => (
        { ok: true, status: 200, json: async () => ({ status: 'queued' }) } as unknown as Response
      )) as unknown as typeof fetch;

      await q.flush();
      expect(errorFired).toBe(true);
      expect(q.size).toBe(1);
      q.destroy();
    });

    it('does not double-drop: an ambiguous 2xx is retained (not dropped like a terminal 4xx)', async () => {
      const q = makeQueue({
        retry: { maxRetries: 0, baseDelay: 1, maxDelay: 1, backoffMultiplier: 1 },
      });
      const event = makeTrackEvent();
      q.enqueue(event);

      globalThis.fetch = vi.fn(async () => (
        { ok: true, status: 200 } as Response
      )) as unknown as typeof fetch;

      await q.flush();
      // Retained (not dropped): the exact same event is still queued, so the
      // eventual confirmed retry sends the identical, stably-id'd event.
      expect(q.size).toBe(1);
      q.destroy();
    });

    it('a subsequent batch still flushes after an ambiguous 2xx (head-of-line not blocked)', async () => {
      let accepted = -1;
      let batchResultCalls = 0;
      const q = makeQueue({
        onBatchResult: (health) => { batchResultCalls++; accepted = health.accepted; },
        retry: { maxRetries: 0, baseDelay: 1, maxDelay: 1, backoffMultiplier: 1 },
      });
      q.enqueue(makeTrackEvent({ seq: 1 }));

      // First flush: ambiguous 2xx — retained, not credited (onBatchResult
      // does not fire for this attempt).
      globalThis.fetch = vi.fn(async () => (
        { ok: true, status: 200 } as Response
      )) as unknown as typeof fetch;
      await q.flush();
      expect(q.size).toBe(1);
      expect(batchResultCalls).toBe(0);

      // A second, distinct event arrives after the failed attempt.
      q.enqueue(makeTrackEvent({ seq: 2 }));
      expect(q.size).toBe(2);

      // Second flush: backend now returns a confirmed, fully-accepted
      // response. Both the retried batch and the newly-enqueued event go out
      // together and are credited — proving the earlier ambiguous response
      // did not permanently wedge the queue (no head-of-line blocking).
      let capturedBatch: AetherEvent[] = [];
      globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
        const body = JSON.parse((init?.body as string) ?? '{}');
        capturedBatch = body.batch;
        return { ok: true, status: 200, json: async () => ({ accepted: capturedBatch.length, duplicate: 0, rejected: 0 }) } as unknown as Response;
      }) as unknown as typeof fetch;

      await q.flush();
      expect(capturedBatch).toHaveLength(2);
      expect(capturedBatch.map((e) => (e.properties as Record<string, unknown>)?.seq)).toEqual([1, 2]);
      expect(q.size).toBe(0);
      expect(batchResultCalls).toBe(1);
      expect(accepted).toBe(2);
      q.destroy();
    });
  });

  // -------------------------------------------------------------------------
  // Offline persistence on unload (persist BEFORE clearing)
  // -------------------------------------------------------------------------

  describe('offline persistence on unload', () => {
    it('persists the queue on destroy so a failed beacon is recoverable next load', () => {
      const q = makeQueue();
      q.enqueue(makeTrackEvent());

      // sendBeacon is fire-and-forget fetch(keepalive); simulate a failed send.
      globalThis.fetch = vi.fn(async () => { throw new Error('network down'); }) as unknown as typeof fetch;

      q.destroy(); // persists BEFORE clearing the in-memory queue

      // A fresh queue restores the persisted events (constructor → restoreQueue),
      // so a beacon failure on unload is not permanent data loss.
      const q2 = makeQueue();
      expect(q2.size).toBe(1);
      q2.destroy();
    });
  });
});
