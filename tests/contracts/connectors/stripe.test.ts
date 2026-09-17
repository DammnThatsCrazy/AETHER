/**
 * FPS-022 — Stripe Connector Contract
 * Verifies Stripe customer/payment/refund payloads conform to @aether/proof-contracts.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope, SourceClassification } from '@aether/proof-contracts';
import {
  stripeCustomerFixture,
  stripePaymentFixture,
  stripeRefundFixture,
} from '@aether/proof-fixtures';

describe('FPS-022: Stripe Connector', () => {
  it('should construct a valid Stripe customer envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: stripeCustomerFixture.tenant_id,
      workspace_id: stripeCustomerFixture.workspace_id,
      platform_id: stripeCustomerFixture.platform_id,
      environment: 'staging',
      event_type: stripeCustomerFixture.event_type,
      sdk: stripeCustomerFixture.sdk,
      identity: stripeCustomerFixture.identity,
      timestamp: stripeCustomerFixture.timestamp,
      properties: stripeCustomerFixture.properties,
    };
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.event_type).toBe('customer_created');
    expect(envelope.properties?.id).toBe('cus_test_001');
    expect(envelope.properties?.email).toBe('stripe@example.com');
  });

  it('should construct a valid Stripe payment envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: stripePaymentFixture.tenant_id,
      workspace_id: stripePaymentFixture.workspace_id,
      platform_id: stripePaymentFixture.platform_id,
      environment: 'staging',
      event_type: stripePaymentFixture.event_type,
      sdk: stripePaymentFixture.sdk,
      identity: stripePaymentFixture.identity,
      timestamp: stripePaymentFixture.timestamp,
      properties: stripePaymentFixture.properties,
    };
    expect(envelope.event_type).toBe('payment_completed');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.properties?.id).toBe('pay_test_001');
    expect(envelope.properties?.amount).toBe(9999);
    expect(envelope.properties?.currency).toBe('usd');
    expect(envelope.properties?.status).toBe('succeeded');
  });

  it('should construct a valid Stripe refund envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: stripeRefundFixture.tenant_id,
      workspace_id: stripeRefundFixture.workspace_id,
      platform_id: stripeRefundFixture.platform_id,
      environment: stripeRefundFixture.environment,
      event_type: stripeRefundFixture.event_type,
      sdk: stripeRefundFixture.sdk,
      identity: stripeRefundFixture.identity,
      timestamp: stripeRefundFixture.timestamp,
      properties: stripeRefundFixture.properties,
    };
    expect(envelope.event_type).toBe('order_refunded');
    expect(envelope.properties?.id).toBe('ref_test_001');
    expect(envelope.properties?.paymentId).toBe('pay_test_001');
    expect(envelope.properties?.amount).toBe(5000);
    expect(envelope.properties?.reason).toBe('requested_by_customer');
  });

  it('should handle pending payment status in envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'stripe',
      environment: 'staging',
      event_type: 'payment_pending',
      sdk: { name: '@aether/stripe', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { id: 'p1', amount: 1000, currency: 'usd', status: 'pending' },
    };
    expect(envelope.properties?.status).toBe('pending');
  });

  it('should handle failed payment status in envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'stripe',
      environment: 'staging',
      event_type: 'payment_failed',
      sdk: { name: '@aether/stripe', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { id: 'p1', amount: 1000, currency: 'usd', status: 'failed' },
    };
    expect(envelope.properties?.status).toBe('failed');
  });

  it('should classify Stripe customer source correctly', () => {
    const source: SourceClassification = {
      platform: 'stripe',
      data_type: 'commerce',
      platform_id: 'cus_test_001',
      sdk: '@aether/stripe',
      environment: 'staging',
    };
    expect(source.platform).toBe('stripe');
    expect(source.data_type).toBe('commerce');
    expect(source.sdk).toBe('@aether/stripe');
  });

  it('should classify Stripe payment source correctly', () => {
    const source: SourceClassification = {
      platform: 'stripe',
      data_type: 'conversion',
      platform_id: 'pay_test_001',
      sdk: '@aether/stripe',
      environment: 'staging',
    };
    expect(source.platform).toBe('stripe');
    expect(source.data_type).toBe('conversion');
  });

  it('should validate Stripe fixtures have _fixture_version', () => {
    expect(stripeCustomerFixture._fixture_version).toBe(1);
    expect(stripePaymentFixture._fixture_version).toBe(1);
    expect(stripeRefundFixture._fixture_version).toBe(1);
  });
});
