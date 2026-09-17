/**
 * PR G — Duplicate Prevention
 * Blueprint §3.8 — SDK + provider duplicates must not double-count.
 *
 * Each source may retry or re-emit the same logical event (idempotency_key
 * replay, webhook redelivery). The graph must deduplicate on
 * (source, event_type, order_id) and keep the conversion count at 1.
 */
import { describe, it, expect } from 'vitest';

type Signal = { source: 'sdk' | 'shopify' | 'stripe'; event_type: string; order_id: string; idempotency_key: string };

function dedupCount(signals: Signal[]): number {
  const seen = new Set<string>();
  let unique = 0;
  for (const s of signals) {
    const k = `${s.source}:${s.event_type}:${s.order_id}:${s.idempotency_key}`;
    if (!seen.has(k)) {
      seen.add(k);
      unique++;
    }
  }
  return unique;
}

function conversionCount(signals: Signal[]): number {
  const orderIds = new Set(signals.map((s) => s.order_id));
  return orderIds.size;
}

describe('PR G: Duplicate Prevention', () => {
  const base: Signal[] = [
    { source: 'sdk', event_type: 'checkout_completed', order_id: 'order_fvj_001', idempotency_key: 'fk-checkout_completed:anon:2024-09-11T11:58:05' },
    { source: 'shopify', event_type: 'order_created', order_id: 'order_fvj_001', idempotency_key: 'shopify:order_fvj_001' },
    { source: 'stripe', event_type: 'payment_succeeded', order_id: 'order_fvj_001', idempotency_key: 'stripe:pi_fvj_001' },
  ];

  it('does not count a retried SDK signal as a new conversion', () => {
    const withRetry = [...base, { ...base[0] }];
    expect(conversionCount(withRetry)).toBe(1);
    expect(dedupCount(withRetry)).toBe(3);
  });

  it('does not count a redelivered Shopify webhook as a new conversion', () => {
    const withRedelivery = [...base, { ...base[1] }];
    expect(conversionCount(withRedelivery)).toBe(1);
    expect(dedupCount(withRedelivery)).toBe(3);
  });

  it('does not count a redelivered Stripe webhook as a new conversion', () => {
    const withRedelivery = [...base, { ...base[2] }];
    expect(conversionCount(withRedelivery)).toBe(1);
    expect(dedupCount(withRedelivery)).toBe(3);
  });

  it('treats a different order_id as a distinct conversion', () => {
    const twoOrders = [...base, { ...base[0], order_id: 'order_fvj_002', idempotency_key: 'fk-checkout_completed:anon:2024-09-11T11:59:00' }];
    expect(conversionCount(twoOrders)).toBe(2);
  });

  it('treats a replay with a new idempotency_key as a distinct signal but still one conversion', () => {
    const replayNewKey = [...base, { ...base[0], idempotency_key: 'fk-checkout_completed:anon:2024-09-11T11:58:06' }];
    expect(dedupCount(replayNewKey)).toBe(4);
    expect(conversionCount(replayNewKey)).toBe(1);
  });
});
