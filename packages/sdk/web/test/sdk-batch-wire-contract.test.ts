import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';

import { EventQueue } from '../src/core/event-queue';
import type { AetherEvent } from '../src/types';

const vector = JSON.parse(
  readFileSync(new URL('../../../shared/contracts/sdk-batch-wire-v1.json', import.meta.url), 'utf8'),
) as {
  endpoint: string;
  request: { batch: Record<string, unknown>[]; sentAt: string };
  requiredBatchFields: string[];
  requiredEventFields: string[];
  optionalBatchFields: string[];
};

describe('SDK batch wire contract v1', () => {
  it('the Web queue emits the shared event vector in the canonical batch envelope', async () => {
    let request: { url: string; init: RequestInit } | undefined;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      request = { url: String(input), init: init ?? {} };
      return {
        ok: true,
        status: 200,
        json: async () => ({ accepted: 1, duplicates: 0, rejected: 0 }),
      } as Response;
    }));

    const queue = new EventQueue({
      endpoint: 'https://api.test',
      apiKey: 'test-key',
      batchSize: 10,
      flushInterval: 60_000,
    });
    try {
      queue.enqueue(vector.request.batch[0] as unknown as AetherEvent);
      await queue.flush();
    } finally {
      queue.destroy();
      vi.unstubAllGlobals();
    }

    expect(request?.url).toBe(`https://api.test${vector.endpoint}`);
    const payload = JSON.parse(String(request?.init.body)) as Record<string, unknown>;
    for (const field of vector.requiredBatchFields) expect(payload).toHaveProperty(field);
    const allowedBatchFields = new Set([...vector.requiredBatchFields, ...vector.optionalBatchFields]);
    for (const field of Object.keys(payload)) expect(allowedBatchFields.has(field)).toBe(true);
    expect(payload.batch).toEqual(vector.request.batch);
    expect(typeof payload.sentAt).toBe('string');
    expect(new Date(String(payload.sentAt)).toISOString()).toBe(payload.sentAt);
    const event = (payload.batch as Record<string, unknown>[])[0];
    for (const field of vector.requiredEventFields) expect(event).toHaveProperty(field);
  });
});
