/** @description FPS-131 — Shopify Order fixture contract.
 * Inline fixtures from @aether/proof-fixtures (not disk-loaded). */
import { describe, it, expect } from 'vitest';
import { shopifyOrderFixture } from '@aether/proof-fixtures';
import { EventEnvelope } from '@aether/proof-contracts';

describe('FPS-131: Shopify Order', () => {
  it('should have fixture metadata', () => {
    expect(shopifyOrderFixture._fixture_version).toBe(1);
    expect(shopifyOrderFixture.tenant_id).toBe('aether-proof-tenant');
    expect(shopifyOrderFixture.platform_id).toBe('shopify');
    expect(shopifyOrderFixture.event_type).toBe('order_completed');
  });

  it('should have order amount', () => {
    const totalPrice = shopifyOrderFixture.properties.totalPrice;
    expect(totalPrice).toBe(75.00);
    expect(totalPrice).toBeGreaterThan(0);
    // Financial totals are tracked separately from the subtotal
    expect(shopifyOrderFixture.properties.totalDiscounted).toBe(5.00);
    expect(shopifyOrderFixture.properties.totalTax).toBe(5.00);
    expect(shopifyOrderFixture.properties.totalShipping).toBe(5.00);
  });

  it('should have order metadata', () => {
    const props = shopifyOrderFixture.properties;
    expect(props.id).toBe('shop_ord_001');
    expect(props.currency).toBe('usd');
    expect(props.status).toBe('closed');
    expect(props.financialStatus).toBe('paid');
    expect(props.fulfillmentStatus).toBe('fulfilled');
    expect(props.customerId).toBe('shop_cus_001');
  });

  it('should have identity linkage', () => {
    const envelope = shopifyOrderFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_shop_ord_001');
    expect(envelope.identity.user_id).toBe('user_006');
  });

  it('should validate against EventEnvelope shape', () => {
    const envelope = shopifyOrderFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(typeof envelope.timestamp).toBe('string');
    expect(envelope.properties).toBeDefined();
  });
});
