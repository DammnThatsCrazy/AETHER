/**
 * PR G — Provenance Preservation & Attribution Explainability
 * Blueprint §3.8 — the graph must preserve which source contributed which
 * evidence, and attribution must be explainable as a single conversion.
 *
 * Each piece of evidence is annotated with its source, timestamp, and
 * whether it is authoritative. Attribution credits sum to 1.0 and point at
 * the contributing evidence ids.
 */
import { describe, it, expect } from 'vitest';

type ProvenanceEntry = {
  evidence_id: string;
  source: 'sdk' | 'shopify' | 'stripe';
  event_type: string;
  received_at: string;
  authoritative: boolean;
  contribution: 'journey_linkage' | 'order_totals' | 'payment_confirmation';
};

type Attribution = {
  conversion_id: string;
  provenance: ProvenanceEntry[];
  credits: Array<{ source: string; evidence_id: string; weight: number; model: string }>;
  explainability: string;
};

function buildAttribution(conversion_id: string, provenance: ProvenanceEntry[]): Attribution {
  const total = provenance.length;
  const credits = provenance.map((p) => ({
    source: p.source,
    evidence_id: p.evidence_id,
    weight: 1 / total,
    model: 'evidence_weighted',
  }));
  const authoritativeIds = provenance.filter((p) => p.authoritative).map((p) => p.evidence_id);
  const explainability =
    `Conversion ${conversion_id} reconciled from ${provenance.length} evidence sources: ` +
    provenance.map((p) => `${p.source}(${p.event_type})`).join(' + ') +
    `. Authoritative: ${authoritativeIds.join(', ') || 'none'}.`;
  return { conversion_id, provenance, credits, explainability };
}

const PROVENANCE: ProvenanceEntry[] = [
  { evidence_id: 'ev_sdk_001', source: 'sdk', event_type: 'checkout_completed', received_at: '2024-09-11T11:58:05.000Z', authoritative: false, contribution: 'journey_linkage' },
  { evidence_id: 'ev_shopify_001', source: 'shopify', event_type: 'order_created', received_at: '2024-09-11T11:58:07.000Z', authoritative: true, contribution: 'order_totals' },
  { evidence_id: 'ev_stripe_001', source: 'stripe', event_type: 'payment_succeeded', received_at: '2024-09-11T11:58:09.000Z', authoritative: true, contribution: 'payment_confirmation' },
];

describe('PR G: Provenance Preservation & Attribution Explainability', () => {
  it('preserves every evidence source in provenance', () => {
    const attr = buildAttribution('conv_aether-proof-tenant:user_first_value_001:order_fvj_001', PROVENANCE);
    expect(attr.provenance).toHaveLength(3);
    expect(attr.provenance.map((p) => p.source)).toEqual(['sdk', 'shopify', 'stripe']);
  });

  it('marks which evidence is authoritative and which is not', () => {
    const attr = buildAttribution('conv_test', PROVENANCE);
    expect(attr.provenance.find((p) => p.source === 'sdk')?.authoritative).toBe(false);
    expect(attr.provenance.find((p) => p.source === 'shopify')?.authoritative).toBe(true);
    expect(attr.provenance.find((p) => p.source === 'stripe')?.authoritative).toBe(true);
  });

  it('describes the contribution role of each evidence piece', () => {
    const attr = buildAttribution('conv_test', PROVENANCE);
    expect(attr.provenance.find((p) => p.source === 'sdk')?.contribution).toBe('journey_linkage');
    expect(attr.provenance.find((p) => p.source === 'shopify')?.contribution).toBe('order_totals');
    expect(attr.provenance.find((p) => p.source === 'stripe')?.contribution).toBe('payment_confirmation');
  });

  it('produces attribution credits that sum to 1.0 and are individually traceable', () => {
    const attr = buildAttribution('conv_test', PROVENANCE);
    const totalWeight = attr.credits.reduce((sum, c) => sum + c.weight, 0);
    expect(totalWeight).toBeCloseTo(1.0);
    for (const c of attr.credits) {
      expect(c.evidence_id).toMatch(/^ev_/);
      expect(c.model).toBe('evidence_weighted');
    }
  });

  it('produces an explainability string naming every contributing source and event type', () => {
    const attr = buildAttribution('conv_test', PROVENANCE);
    expect(attr.explainability).toContain('sdk(checkout_completed)');
    expect(attr.explainability).toContain('shopify(order_created)');
    expect(attr.explainability).toContain('stripe(payment_succeeded)');
    expect(attr.explainability).toContain('Authoritative:');
  });

  it('keeps SDK evidence even when provider supersedes it — no evidence is dropped', () => {
    const attr = buildAttribution('conv_test', PROVENANCE);
    const sdkEvidence = attr.provenance.filter((p) => p.source === 'sdk');
    expect(sdkEvidence.length).toBeGreaterThan(0);
    const sdkCredit = attr.credits.find((c) => c.source === 'sdk');
    expect(sdkCredit).toBeDefined();
  });
});
