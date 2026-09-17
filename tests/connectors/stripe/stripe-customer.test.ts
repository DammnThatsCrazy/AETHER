/** @description FPS-120 — Stripe Customer fixture contract.
 * Inline fixtures from @aether/proof-fixtures (not disk-loaded) because
 * connector fixtures are defined as named exports in index.ts, not JSON files. */
import { describe, it, expect } from 'vitest';
import { stripeCustomerFixture } from '@aether/proof-fixtures';
import { EventEnvelope } from '@aether/proof-contracts';

describe('FPS-120: Stripe Customer', () => {
  it('should have fixture metadata', () => {
    expect(stripeCustomerFixture._fixture_version).toBe(1);
    expect(stripeCustomerFixture.tenant_id).toBe('aether-proof-tenant');
    expect(stripeCustomerFixture.platform_id).toBe('stripe');
    expect(stripeCustomerFixture.event_type).toBe('customer_created');
  });

  it('should map customer ID to graph profile key', () => {
    const id = stripeCustomerFixture.properties.id;
    expect(id).toBe('cus_test_001');
    const profileKey = `profile_stripe_${id}`;
    expect(profileKey).toBe('profile_stripe_cus_test_001');
  });

  it('should have email and identity linkage', () => {
    const envelope = stripeCustomerFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_stripe_001');
    expect(envelope.identity.user_id).toBe('user_005');
    expect(stripeCustomerFixture.properties.email).toBe('stripe@example.com');
  });

  it('should validate against EventEnvelope shape', () => {
    const envelope = stripeCustomerFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.event_type).toBe('customer_created');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(typeof envelope.timestamp).toBe('string');
    expect(envelope.properties).toBeDefined();
  });
});
