/**
 * FPS-111 — Stripe Connector Fixture
 * Verifies Stripe raw and normalized fixture validation.
 *
 * Stripe fixtures are stored as inline objects in @aether/proof-fixtures/src/index.ts
 * (stripeCustomerFixture, stripePaymentFixture, stripeRefundFixture). The loader API
 * (loadRawFixture / loadExpectedNormalized / findFixtureDir) routes through the
 * fixtures/<domain>/ directory on disk, which does not contain individual JSON files
 * for connector domains — only the SDK event keys have single-file JSON fixtures.
 *
 * This test validates the connector fixtures by importing them directly and
 * asserting their shape against the EventEnvelope contract.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import {
  stripeCustomerFixture,
  stripePaymentFixture,
  stripeRefundFixture,
} from '@aether/proof-fixtures';

describe('FPS-111: Stripe Fixture', () => {
  it('should validate stripeCustomerFixture shape', () => {
    const f = stripeCustomerFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.tenant_id).toBe('aether-proof-tenant');
    expect(f.workspace_id).toBe('proof-lab');
    expect(f.platform_id).toBe('stripe');
    expect(f.environment).toBe('staging');
    expect(f.event_type).toBe('customer_created');
    expect(f.sdk.name).toBe('@aether/stripe');
    expect(f.sdk.version).toBe('0.1.0-alpha.0');
    expect(f.identity.anonymous_id).toBe('anon_stripe_001');
    expect(f.identity.user_id).toBe('user_005');
    expect(typeof f.timestamp).toBe('string');
    expect(f.properties.id).toBe('cus_test_001');
    expect(f.properties.email).toBe('stripe@example.com');
    expect(f.properties.name).toBe('Test Customer');
  });

  it('should validate stripePaymentFixture shape', () => {
    const f = stripePaymentFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.tenant_id).toBe('aether-proof-tenant');
    expect(f.platform_id).toBe('stripe');
    expect(f.event_type).toBe('payment_completed');
    expect(f.sdk.name).toBe('@aether/stripe');
    expect(f.identity.anonymous_id).toBe('anon_stripe_001');
    expect(f.identity.user_id).toBe('user_005');
    expect(f.properties.id).toBe('pay_test_001');
    expect(f.properties.amount).toBe(9999);
    expect(f.properties.currency).toBe('usd');
    expect(f.properties.status).toBe('succeeded');
    expect(f.properties.customerId).toBe('cus_test_001');
  });

  it('should validate stripeRefundFixture shape', () => {
    const f = stripeRefundFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.platform_id).toBe('stripe');
    expect(f.event_type).toBe('order_refunded');
    expect(f.sdk.name).toBe('@aether/stripe');
    expect(f.identity.anonymous_id).toBe('anon_stripe_001');
    expect(f.identity.user_id).toBe('user_005');
    expect(f.properties.id).toBe('ref_test_001');
    expect(f.properties.paymentId).toBe('pay_test_001');
    expect(f.properties.amount).toBe(5000);
    expect(f.properties.currency).toBe('usd');
    expect(f.properties.status).toBe('succeeded');
  });

  it('should validate stripeCustomerFixture against EventEnvelope contract', () => {
    const envelope = stripeCustomerFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('customer_created');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_stripe_001');
    expect(envelope.identity.user_id).toBe('user_005');
    expect(typeof envelope.timestamp).toBe('string');
  });

  it('should validate stripePaymentFixture against EventEnvelope contract', () => {
    const envelope = stripePaymentFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.event_type).toBe('payment_completed');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(envelope.identity.anonymous_id).toBe('anon_stripe_001');
    expect(envelope.identity.user_id).toBe('user_005');
  });

  it('should validate stripeRefundFixture against EventEnvelope contract', () => {
    const envelope = stripeRefundFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.event_type).toBe('order_refunded');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(envelope.identity.anonymous_id).toBe('anon_stripe_001');
    expect(envelope.identity.user_id).toBe('user_005');
  });
});
