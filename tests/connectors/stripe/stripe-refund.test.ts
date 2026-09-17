/** @description FPS-122 — Stripe Refund fixture contract.
 * Inline fixtures from @aether/proof-fixtures (not disk-loaded). */
import { describe, it, expect } from 'vitest';
import { stripeRefundFixture } from '@aether/proof-fixtures';
import { EventEnvelope } from '@aether/proof-contracts';

describe('FPS-122: Stripe Refund', () => {
  it('should have fixture metadata', () => {
    expect(stripeRefundFixture._fixture_version).toBe(1);
    expect(stripeRefundFixture.tenant_id).toBe('aether-proof-tenant');
    expect(stripeRefundFixture.platform_id).toBe('stripe');
    expect(stripeRefundFixture.event_type).toBe('order_refunded');
  });

  it('should have refund amount in cents', () => {
    const amount = stripeRefundFixture.properties.amount;
    expect(amount).toBe(5000);
    const dollars = amount / 100;
    expect(dollars).toBe(50.00);
  });

  it('should have refund metadata', () => {
    const props = stripeRefundFixture.properties;
    expect(props.id).toBe('ref_test_001');
    expect(props.paymentId).toBe('pay_test_001');
    expect(props.amount).toBe(5000);
    expect(props.currency).toBe('usd');
    expect(props.reason).toBe('requested_by_customer');
    expect(props.status).toBe('succeeded');
  });

  it('should have identity linkage', () => {
    const envelope = stripeRefundFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_stripe_001');
    expect(envelope.identity.user_id).toBe('user_005');
  });

  it('should validate against EventEnvelope shape', () => {
    const envelope = stripeRefundFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.event_type).toBe('order_refunded');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(typeof envelope.timestamp).toBe('string');
    expect(envelope.properties).toBeDefined();
  });
});
