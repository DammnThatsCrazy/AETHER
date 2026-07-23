import { describe, expect, it } from 'vitest';

import {
  buildCanonicalConsentReceipt,
  canonicalConsentReceiptPreimage,
} from './consent-receipt';

const goldenInput = {
  tenant_id: 'tenant-1',
  subject_id: 'subject-1',
  purposes: ['marketing', 'analytics'],
  state: 'granted' as const,
  source: 'sdk-test',
  policy_version: '2026-07-18',
  granted_at: '2026-07-18T12:00:00.000Z',
  metadata: {},
};

describe('canonical consent receipts', () => {
  it('uses the backend-compatible deterministic golden vector', async () => {
    const receipt = await buildCanonicalConsentReceipt(goldenInput);

    expect(receipt.integrity_hash).toBe(
      'sha256:96352c9c6e59371ad054846329720b2eb1285c71bb39406ffae5b1583e1e54c0',
    );
    expect(receipt.receipt_id).toBe('ccr_96352c9c6e59371ad054846329720b2e');
    expect(receipt.idempotency_key).toBe(
      'consent-receipt:96352c9c6e59371ad054846329720b2eb1285c71bb39406ffae5b1583e1e54c0',
    );
    expect(receipt.purposes).toEqual(['analytics', 'marketing']);
  });

  it('counts UTF-8 bytes and renders empty optional fields', () => {
    const preimage = canonicalConsentReceiptPreimage({
      ...goldenInput,
      source: 'sdk-é',
    });

    expect(preimage).toContain('source=6:sdk-é\n');
    expect(preimage).toContain('anonymous_id=0:\n');
    expect(preimage).toContain('metadata=0:\n');
  });
});
