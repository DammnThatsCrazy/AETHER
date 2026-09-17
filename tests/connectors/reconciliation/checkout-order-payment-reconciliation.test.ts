/**
 * PR G — Checkout → Order → Payment Reconciliation
 * Blueprint §3.8 — SDK and connector evidence must converge to one graph truth.
 *
 * Scenario: a single purchase observed three ways:
 *   1. Web SDK  → checkout_completed / payment step
 *   2. Shopify  → order_created webhook
 *   3. Stripe   → payment_succeeded webhook
 *
 * The graph must produce ONE conversion, with provenance listing all three
 * contributing sources. Provider evidence may supersede the SDK observation
 * (authoritative totals), but the SDK still provides the early signal and
 * the session/journey linkage before the provider webhooks arrive.
 */
import { describe, it, expect } from 'vitest';

type EvidenceSource = 'sdk' | 'shopify' | 'stripe';
type ReconciledConversion = {
  conversion_id: string;
  tenant_id: string;
  user_id: string;
  value: number;
  currency: string;
  status: 'observed' | 'confirmed';
  evidence: Array<{ source: EvidenceSource; event_type: string; received_at: string; authoritative: boolean }>;
  primary_source: EvidenceSource;
};

/**
 * Minimal in-test reconciler that encodes the blueprint rule:
 *  - Correlation key: (tenant_id, user_id, external_order_id).
 *  - First SDK signal creates an `observed` conversion; a later provider
 *    signal flips it to `confirmed` and becomes primary_source.
 *  - Duplicate signals from the same source are ignored.
 *  - The conversion count is always 1 per correlation key.
 */
function reconcile(
  signals: Array<{ source: EvidenceSource; event_type: string; tenant_id: string; user_id: string; order_id: string; value: number; currency: string; received_at: string }>,
): ReconciledConversion {
  const key = `${signals[0].tenant_id}:${signals[0].user_id}:${signals[0].order_id}`;
  const seen = new Set<string>();
  const evidence: ReconciledConversion['evidence'] = [];
  let authoritativeValue = signals[0].value;
  let authoritativeCurrency = signals[0].currency;
  let primary_source: EvidenceSource = 'sdk';
  let status: ReconciledConversion['status'] = 'observed';

  const priority: Record<EvidenceSource, number> = { sdk: 0, shopify: 1, stripe: 2 };

  for (const s of signals) {
    const dedupKey = `${s.source}:${s.event_type}:${s.order_id}`;
    if (seen.has(dedupKey)) continue;
    seen.add(dedupKey);

    const authoritative = s.source !== 'sdk';
    evidence.push({ source: s.source, event_type: s.event_type, received_at: s.received_at, authoritative });

    if (priority[s.source] > priority[primary_source]) {
      primary_source = s.source;
      authoritativeValue = s.value;
      authoritativeCurrency = s.currency;
    }
    if (s.source !== 'sdk') status = 'confirmed';
  }

  return {
    conversion_id: `conv_${key}`,
    tenant_id: signals[0].tenant_id,
    user_id: signals[0].user_id,
    value: authoritativeValue,
    currency: authoritativeCurrency,
    status,
    evidence,
    primary_source,
  };
}

const BASE_SIGNALS = [
  {
    source: 'sdk' as const,
    event_type: 'checkout_completed',
    tenant_id: 'aether-proof-tenant',
    user_id: 'user_first_value_001',
    order_id: 'order_fvj_001',
    value: 50.0,
    currency: 'usd',
    received_at: '2024-09-11T11:58:05.000Z',
  },
  {
    source: 'shopify' as const,
    event_type: 'order_created',
    tenant_id: 'aether-proof-tenant',
    user_id: 'user_first_value_001',
    order_id: 'order_fvj_001',
    value: 50.0,
    currency: 'usd',
    received_at: '2024-09-11T11:58:07.000Z',
  },
  {
    source: 'stripe' as const,
    event_type: 'payment_succeeded',
    tenant_id: 'aether-proof-tenant',
    user_id: 'user_first_value_001',
    order_id: 'order_fvj_001',
    value: 50.0,
    currency: 'usd',
    received_at: '2024-09-11T11:58:09.000Z',
  },
];

describe('PR G: Checkout → Order → Payment Reconciliation', () => {
  it('reconciles three correlated signals into exactly one conversion', () => {
    const conv = reconcile(BASE_SIGNALS);
    expect(conv.conversion_id).toBeDefined();
    expect(conv.evidence).toHaveLength(3);
    expect(conv.tenant_id).toBe('aether-proof-tenant');
    expect(conv.user_id).toBe('user_first_value_001');
  });

  it('produces no double-counting — one conversion per order regardless of source count', () => {
    const sdkOnly = reconcile([BASE_SIGNALS[0]]);
    const sdkPlusShopify = reconcile(BASE_SIGNALS.slice(0, 2));
    const allThree = reconcile(BASE_SIGNALS);
    expect(sdkOnly.conversion_id).toBe(sdkPlusShopify.conversion_id);
    expect(sdkPlusShopify.conversion_id).toBe(allThree.conversion_id);
  });

  it('keeps SDK as early signal before provider confirmation', () => {
    const sdkOnly = reconcile([BASE_SIGNALS[0]]);
    expect(sdkOnly.status).toBe('observed');
    expect(sdkOnly.primary_source).toBe('sdk');
    expect(sdkOnly.evidence[0].source).toBe('sdk');
    expect(sdkOnly.evidence[0].authoritative).toBe(false);
  });

  it('lets provider evidence supersede the SDK observation', () => {
    const confirmed = reconcile(BASE_SIGNALS);
    expect(confirmed.status).toBe('confirmed');
    expect(confirmed.primary_source).not.toBe('sdk');
    const stripeEvidence = confirmed.evidence.find((e) => e.source === 'stripe');
    expect(stripeEvidence?.authoritative).toBe(true);
  });

  it('preserves the authoritative totals from the provider when they differ', () => {
    const withAdjustedTotal = [
      BASE_SIGNALS[0],
      { ...BASE_SIGNALS[1], value: 49.99 },
      { ...BASE_SIGNALS[2], value: 49.99 },
    ];
    const conv = reconcile(withAdjustedTotal);
    expect(conv.value).toBe(49.99);
    expect(conv.primary_source).toBe('stripe');
  });

  it('attaches a single journey via shared correlation (not one per source)', () => {
    const conv = reconcile(BASE_SIGNALS);
    expect(conv.conversion_id).toMatch(/^conv_/);
    expect(new Set(conv.evidence.map((e) => e.source)).size).toBe(3);
  });
});
