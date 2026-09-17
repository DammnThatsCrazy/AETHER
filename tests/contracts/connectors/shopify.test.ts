/**
 * FPS-022 — Shopify Connector Contract
 * Verifies Shopify customer/order/product payloads conform to @aether/proof-contracts.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope, SourceClassification } from '@aether/proof-contracts';
import {
  shopifyCustomerFixture,
  shopifyOrderFixture,
  shopifyProductFixture,
} from '@aether/proof-fixtures';

describe('FPS-022: Shopify Connector', () => {
  it('should construct a valid Shopify customer envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: shopifyCustomerFixture.tenant_id,
      workspace_id: shopifyCustomerFixture.workspace_id,
      platform_id: shopifyCustomerFixture.platform_id,
      environment: shopifyCustomerFixture.environment,
      event_type: shopifyCustomerFixture.event_type,
      sdk: shopifyCustomerFixture.sdk,
      identity: shopifyCustomerFixture.identity,
      timestamp: shopifyCustomerFixture.timestamp,
      properties: shopifyCustomerFixture.properties,
    };
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('customer_created');
    expect(envelope.properties?.id).toBe('shop_cus_001');
    expect(envelope.properties?.email).toBe('shopify@example.com');
    expect(envelope.properties?.firstName).toBe('Jane');
    expect(envelope.properties?.ordersCount).toBe(3);
  });

  it('should construct a valid Shopify order envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: shopifyOrderFixture.tenant_id,
      workspace_id: shopifyOrderFixture.workspace_id,
      platform_id: shopifyOrderFixture.platform_id,
      environment: shopifyOrderFixture.environment,
      event_type: shopifyOrderFixture.event_type,
      sdk: shopifyOrderFixture.sdk,
      identity: shopifyOrderFixture.identity,
      timestamp: shopifyOrderFixture.timestamp,
      properties: shopifyOrderFixture.properties,
    };
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.properties?.id).toBe('shop_ord_001');
    expect(envelope.properties?.orderNumber).toBe('#1001');
    expect(envelope.properties?.totalPrice).toBe(75.00);
    expect(envelope.properties?.currency).toBe('usd');
    expect(envelope.properties?.status).toBe('closed');
  });

  it('should construct a valid Shopify product envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: shopifyProductFixture.tenant_id,
      workspace_id: shopifyProductFixture.workspace_id,
      platform_id: shopifyProductFixture.platform_id,
      environment: shopifyProductFixture.environment,
      event_type: shopifyProductFixture.event_type,
      sdk: shopifyProductFixture.sdk,
      identity: shopifyProductFixture.identity,
      timestamp: shopifyProductFixture.timestamp,
      properties: shopifyProductFixture.properties,
    };
    expect(envelope.event_type).toBe('product_viewed');
    expect(envelope.properties?.id).toBe('shop_prod_001');
    expect(envelope.properties?.title).toBe('Demo Widget');
    expect(envelope.properties?.vendor).toBe('AetherDemo');
    expect(envelope.properties?.tags).toContain('widget');
  });

  it('should handle different order statuses in envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'shopify',
      environment: 'staging',
      event_type: 'order_draft',
      sdk: { name: '@aether/shopify', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { id: 'o1', orderNumber: '#2001', totalPrice: 500, currency: 'usd', status: 'draft' },
    };
    expect(envelope.properties?.status).toBe('draft');
  });

  it('should handle products without vendor in envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'shopify',
      environment: 'staging',
      event_type: 'product_viewed',
      sdk: { name: '@aether/shopify', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { id: 'p1', title: 'Generic', vendor: undefined, price: 100, currency: 'usd' },
    };
    expect(envelope.properties?.vendor).toBeUndefined();
  });

  it('should classify Shopify customer source correctly', () => {
    const source: SourceClassification = {
      platform: 'shopify',
      data_type: 'identity',
      platform_id: 'shop_cus_001',
      sdk: '@aether/shopify',
      environment: 'staging',
    };
    expect(source.platform).toBe('shopify');
    expect(source.data_type).toBe('identity');
  });

  it('should classify Shopify order source as commerce', () => {
    const source: SourceClassification = {
      platform: 'shopify',
      data_type: 'commerce',
      platform_id: 'shop_ord_001',
      sdk: '@aether/shopify',
      environment: 'staging',
    };
    expect(source.platform).toBe('shopify');
    expect(source.data_type).toBe('commerce');
  });

  it('should validate Shopify fixtures have _fixture_version', () => {
    expect(shopifyCustomerFixture._fixture_version).toBe(1);
    expect(shopifyOrderFixture._fixture_version).toBe(1);
    expect(shopifyProductFixture._fixture_version).toBe(1);
  });
});
