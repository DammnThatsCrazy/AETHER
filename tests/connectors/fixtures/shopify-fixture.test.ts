/**
 * FPS-112 — Shopify Connector Fixture
 * Verifies Shopify raw and normalized fixture validation.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { shopifyCustomerFixture, shopifyOrderFixture, shopifyProductFixture } from '@aether/proof-fixtures';

describe('FPS-112: Shopify Fixture', () => {
  it('should validate shopify customer fixture', () => {
    expect(shopifyCustomerFixture.event_type).toBe('customer_created');
    expect(shopifyCustomerFixture.platform_id).toBe('shopify');
    expect(shopifyCustomerFixture.tenant_id).toBe('aether-proof-tenant');
    const props = shopifyCustomerFixture.properties as Record<string, unknown>;
    expect(props.id).toBe('shop_cus_001');
    expect(props.email).toBe('shopify@example.com');
    expect(props.firstName).toBe('Jane');
    expect(props.lastName).toBe('Doe');
    expect(props.ordersCount).toBe(3);
    expect(props.totalSpent).toBe(250.00);
    expect(props.currency).toBe('usd');
    expect(props.phone).toBe('+1-555-0200');
  });

  it('should validate shopify customer against EventEnvelope shape', () => {
    const envelope = shopifyCustomerFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('customer_created');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(envelope.identity.anonymous_id).toBe('anon_shop_cus_001');
    expect(envelope.identity.user_id).toBe('user_006');
  });

  it('should validate shopify order fixture', () => {
    expect(shopifyOrderFixture.event_type).toBe('order_completed');
    expect(shopifyOrderFixture.platform_id).toBe('shopify');
    expect(shopifyOrderFixture.tenant_id).toBe('aether-proof-tenant');
    const props = shopifyOrderFixture.properties as Record<string, unknown>;
    expect(props.id).toBe('shop_ord_001');
    expect(props.orderNumber).toBe('#1001');
    expect(props.totalPrice).toBe(75.00);
    expect(props.currency).toBe('usd');
    expect(props.status).toBe('closed');
    expect(props.financialStatus).toBe('paid');
  });

  it('should validate shopify order against EventEnvelope shape', () => {
    const envelope = shopifyOrderFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(envelope.identity.anonymous_id).toBe('anon_shop_ord_001');
    expect(envelope.identity.user_id).toBe('user_006');
  });

  it('should validate shopify product fixture', () => {
    expect(shopifyProductFixture.event_type).toBe('product_viewed');
    expect(shopifyProductFixture.platform_id).toBe('shopify');
    expect(shopifyProductFixture.tenant_id).toBe('aether-proof-tenant');
    const props = shopifyProductFixture.properties as Record<string, unknown>;
    expect(props.id).toBe('shop_prod_001');
    expect(props.title).toBe('Demo Widget');
    expect(props.vendor).toBe('AetherDemo');
    expect(props.productType).toBe('widgets');
    expect(props.price).toBe(25.00);
    expect(props.sku).toBe('DW-001');
  });

  it('should validate shopify product against EventEnvelope shape', () => {
    const envelope = shopifyProductFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('product_viewed');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(envelope.identity.anonymous_id).toBe('anon_shop_prod_001');
    expect(envelope.identity.user_id).toBe('user_006');
  });
});
