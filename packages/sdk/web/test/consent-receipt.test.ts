import { afterEach, describe, expect, it, vi } from 'vitest';

import { AetherSDK } from '../src';

describe('canonical consent receipt API', () => {
  afterEach(() => vi.restoreAllMocks());

  it('posts the legacy fields plus the canonical receipt envelope', async () => {
    const request = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ data: {} }), { status: 200 }),
    );
    const sdk = new AetherSDK();
    Object.assign(sdk, {
      config: {
        apiKey: 'test-key',
        endpoint: 'https://example.test',
      },
    });

    const receipt = await sdk.consent.recordReceipt({
      tenant_id: 'tenant-1',
      subject_id: 'subject-1',
      purposes: ['marketing', 'analytics'],
      state: 'granted',
      source: 'sdk-test',
      policy_version: '2026-07-18',
      granted_at: '2026-07-18T12:00:00.000Z',
    });

    const receiptCall = request.mock.calls.find(
      ([url]) => String(url) === 'https://example.test/v1/consent/records',
    );
    expect(receiptCall).toBeDefined();
    const body = JSON.parse(String(receiptCall?.[1]?.body));
    expect(body.idempotency_key).toBe(receipt.idempotency_key);
    expect(body.canonical_receipt).toEqual(receipt);
    expect(body.purposes).toEqual(['analytics', 'marketing']);
  });
});
