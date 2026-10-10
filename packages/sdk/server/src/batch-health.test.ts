// Truth Kernel §2.8 — the server SDK must parse per-batch ingestion health
// (accepted / duplicate / rejected) from the /v1/batch response and surface it
// alongside SDK-side queue_depth / dropped_by_consent.
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AetherServerSDK } from './index';
import { parseIngestCounters, sendBatch } from './transport';
import type { BatchHealth } from './types';

describe('server transport — parseIngestCounters', () => {
  it('parses accepted / duplicate / rejected', () => {
    expect(parseIngestCounters({ accepted: 3, duplicate: 1, rejected: 2 })).toEqual({
      accepted: 3, duplicate: 1, rejected: 2,
    });
  });

  it('normalizes the backend plural `duplicates`', () => {
    expect(parseIngestCounters({ accepted: 5, duplicates: 4 })).toEqual({
      accepted: 5, duplicate: 4, rejected: 0,
    });
  });

  it('returns undefined when no counters are present', () => {
    expect(parseIngestCounters({ batchId: 'b1' })).toBeUndefined();
    expect(parseIngestCounters(null)).toBeUndefined();
  });
});

describe('server transport — counters attached to 2xx result', () => {
  afterEach(() => vi.restoreAllMocks());

  it('attaches parsed counters from the response body', async () => {
    (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ accepted: 2, duplicates: 0, rejected: 1 }),
    }));

    const res = await sendBatch(
      { endpoint: 'https://api.test/v1/batch', writeKey: 'sk' },
      [{ id: 'e1', type: 'job_started' }, { id: 'e2', type: 'job_completed' }],
      ['analytics'],
    );
    expect(res.ok).toBe(true);
    expect(res.counters).toEqual({ accepted: 2, duplicate: 0, rejected: 1 });
  });
});

describe('AetherServerSDK — onBatchResult (§2.8)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('invokes onBatchResult with parsed counters + queue_depth after flush', async () => {
    (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ accepted: 1, duplicates: 0, rejected: 0 }),
    }));

    const seen: BatchHealth[] = [];
    const sdk = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'https://api.test/v1/batch',
      consent: { analytics: true },
      onBatchResult: (h) => seen.push(h),
    });
    sdk.track({ type: 'api_request_observed', properties: { path: '/x' } });
    await sdk.flush();
    await sdk.shutdown();

    expect(seen).toHaveLength(1);
    expect(seen[0].accepted).toBe(1);
    expect(seen[0].rejected).toBe(0);
    expect(seen[0].dropped_by_consent).toBe(0);
    expect(seen[0].queue_depth).toBe(0);
    expect(sdk.lastBatchResult()).toEqual(seen[0]);
  });
});
