/** @description FPS-130 — Shopify Customer fixture contract.
 * Inline fixtures from @aether/proof-fixtures (not disk-loaded). */
import { describe, it, expect } from 'vitest';
import { shopifyCustomerFixture } from '@aether/proof-fixtures';
import { EventEnvelope } from '@aether/proof-contracts';

describe('FPS-130: Shopify Customer', () => {
  it('should have fixture metadata', () => {
    expect(shopifyCustomerFixture._fixture_version).toBe(1);
    expect(shopifyCustomerFixture.tenant_id).toBe('aether-proof-tenant');
    expect(shopifyCustomerFixture.platform_id).toBe('shopify');
    expect(shopifyCustomerFixture.event_type).toBe('customer_created');
  });

  it('should map customer ID to graph profile key', () => {
    const id = shopifyCustomerFixture.properties.id;
    expect(id).toBe('shop_cus_001');
    const profileKey = `profile_shopify_${id}`;
    expect(profileKey).toBe('profile_shopify_shop_cus_001');
  });

  it('should have customer attributes', () => {
    const props = shopifyCustomerFixture.properties;
    expect(props.email).toBe('shopify@example.com');
    expect(props.firstName).toBe('Jane');
    expect(props.lastName).toBe('Doe');
    expect(props.ordersCount).toBe(3);
    expect(props.totalSpent).toBe(250.00);
    expect(props.acceptsMarketing).toBe(true);
    expect(props.lastOrderName).toBe('#1003');
    expect(props.lastOrderId).toBe('shop_ord_003');
  });

  it('should have identity linkage', () => {
    const envelope = shopifyCustomerFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_shop_cus_001');
    expect(envelope.identity.user_id).toBe('user_006');
  });

  it('should validate against EventEnvelope shape', () => {
    const envelope = shopifyCustomerFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('customer_created');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(typeof envelope.timestamp).toBe('string');
    expect(envelope.properties).toBeDefined();
  });
});
