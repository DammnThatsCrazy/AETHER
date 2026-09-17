/** @description FPS-132 — Shopify Product fixture contract.
 * Inline fixtures from @aether/proof-fixtures (not disk-loaded). */
import { describe, it, expect } from 'vitest';
import { shopifyProductFixture } from '@aether/proof-fixtures';
import { EventEnvelope } from '@aether/proof-contracts';

describe('FPS-132: Shopify Product', () => {
  it('should have fixture metadata', () => {
    expect(shopifyProductFixture._fixture_version).toBe(1);
    expect(shopifyProductFixture.tenant_id).toBe('aether-proof-tenant');
    expect(shopifyProductFixture.platform_id).toBe('shopify');
    expect(shopifyProductFixture.event_type).toBe('product_viewed');
  });

  it('should have product metadata', () => {
    const props = shopifyProductFixture.properties;
    expect(props.id).toBe('shop_prod_001');
    expect(props.title).toBe('Demo Widget');
    expect(props.vendor).toBe('AetherDemo');
    expect(props.productType).toBe('widgets');
    expect(props.tags).toEqual(['widget', 'demo', 'featured']);
    const variants = props.variants;
    expect(Array.isArray(variants)).toBe(true);
    expect(variants.length).toBe(1);
    expect(variants[0].id).toBe('shop_var_001');
    expect(props.price).toBe(25.00);
    expect(props.compareAtPrice).toBe(35.00);
  });

  it('should have identity linkage', () => {
    const envelope = shopifyProductFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_shop_prod_001');
    expect(envelope.identity.user_id).toBe('user_006');
  });

  it('should validate against EventEnvelope shape', () => {
    const envelope = shopifyProductFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('product_viewed');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(typeof envelope.timestamp).toBe('string');
    expect(envelope.properties).toBeDefined();
  });
});
