/** @description FPS-121 — Stripe Payment fixture contract.
 * Inline fixtures from @aether/proof-fixtures (not disk-loaded). */
import { describe, it, expect } from 'vitest';
import { stripePaymentFixture } from '@aether/proof-fixtures';
import { EventEnvelope } from '@aether/proof-contracts';

describe('FPS-121: Stripe Payment', () => {
  it('should have fixture metadata', () => {
    expect(stripePaymentFixture._fixture_version).toBe(1);
    expect(stripePaymentFixture.tenant_id).toBe('aether-proof-tenant');
    expect(stripePaymentFixture.platform_id).toBe('stripe');
    expect(stripePaymentFixture.event_type).toBe('payment_completed');
  });

  it('should have amount in cents', () => {
    const amount = stripePaymentFixture.properties.amount;
    expect(amount).toBe(9999);
    // amount is in cents: 9999 cents = $99.99
    const dollars = amount / 100;
    expect(dollars).toBe(99.99);
  });

  it('should have payment metadata', () => {
    const props = stripePaymentFixture.properties;
    expect(props.id).toBe('pay_test_001');
    expect(props.description).toBe('Test payment for proof fixtures');
    expect(props.status).toBe('succeeded');
    expect(props.customerId).toBe('cus_test_001');
    expect(props.receipt_email).toBe('stripe@example.com');
    expect(props.receipt_number).toBe('re_1234567890');
    expect(props.fees).toBe(321);
    expect(props.net).toBe(9678);
  });

  it('should have identity linkage', () => {
    const envelope = stripePaymentFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_stripe_001');
    expect(envelope.identity.user_id).toBe('user_005');
  });

  it('should validate against EventEnvelope shape', () => {
    const envelope = stripePaymentFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.event_type).toBe('payment_completed');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(typeof envelope.timestamp).toBe('string');
    expect(envelope.properties).toBeDefined();
  });
});
