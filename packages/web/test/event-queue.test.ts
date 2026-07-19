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
        return { ok: true, status: 200 } as Response;
      }) as unknown as typeof fetch;

      await q.flush();
      expect(calls).toBe(2);
      expect(q.size).toBe(0);
      q.destroy();
    });

    it('re-queues batch on non-retryable error', async () => {
      const q = makeQueue();
      q.enqueue(makeTrackEvent());

      let errorFired = false;
      const qWithError = makeQueue({
        onError: () => { errorFired = true; },
        retry: { maxRetries: 0, baseDelay: 1, maxDelay: 1, backoffMultiplier: 1 },
      });
      qWithError.enqueue(makeTrackEvent());

      globalThis.fetch = vi.fn(async () => {
        return { ok: false, status: 400, statusText: 'Bad Request', headers: new Headers() } as Response;
      }) as unknown as typeof fetch;

      await qWithError.flush();
      // 400 is not retried — error callback fires and events re-queued
      expect(errorFired).toBe(true);
      expect(qWithError.size).toBe(1);
      qWithError.destroy();
      q.destroy();
    });
  });
});
