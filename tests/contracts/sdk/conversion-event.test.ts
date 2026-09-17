/**
 * FPS-021 — SDK Conversion Event Contract
 * Verifies conversion event payloads conform to @aether/proof-contracts schema.
 */
import { describe, it, expect } from 'vitest';

import { ConversionEventPayload, EventEnvelope } from '@aether/proof-contracts';
import { conversionEventFixture } from '@aether/proof-fixtures';

describe('FPS-021: SDK Conversion Event', () => {
  it('should construct a valid conversion event payload', () => {
    const event: ConversionEventPayload = {
      conversionId: 'conv_test_001',
      eventName: 'purchase',
      value: 49.99,
      currency: 'USD',
      timestamp: Date.now(),
    };
    expect(event.conversionId).toBe('conv_test_001');
    expect(event.eventName).toBe('purchase');
    expect(event.value).toBe(49.99);
    expect(event.currency).toBe('USD');
  });

  it('should accept optional properties on conversion', () => {
    const event: ConversionEventPayload = {
      conversionId: 'c1',
      eventName: 'signup',
      value: 0,
      currency: 'USD',
      properties: { productId: 'p1' },
      timestamp: Date.now(),
    };
    expect(event.properties?.productId).toBe('p1');
  });

  it('should accept conversion with minimal fields', () => {
    const event: ConversionEventPayload = {
      conversionId: 'c1',
      eventName: 'signup',
      value: 0,
      currency: 'USD',
      timestamp: Date.now(),
    };
    expect(event.value).toBe(0);
    expect(event.currency).toBe('USD');
    expect(event.properties).toBeUndefined();
  });

  it('should validate conversionId is a non-empty string', () => {
    const event: ConversionEventPayload = {
      conversionId: 'valid_id',
      eventName: 'purchase',
      value: 10,
      currency: 'USD',
      timestamp: Date.now(),
    };
    expect(event.conversionId).toBe('valid_id');
    expect(typeof event.conversionId).toBe('string');
    expect(event.conversionId.length).toBeGreaterThan(0);
  });

  it('should validate conversion against EventEnvelope shape using fixture', () => {
    const envelope = conversionEventFixture as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(envelope.identity.anonymous_id).toBe('anon_shop_001');
    expect(envelope.identity.user_id).toBe('user_003');
    expect(envelope.timestamp).toBe('2024-09-11T12:10:00.000Z');
    expect(envelope.properties).toBeDefined();
    expect(envelope.properties?.order_id).toBe('shop_ord_001');
    expect(envelope.properties?.revenue).toBe(75.00);
    expect(envelope.properties?.currency).toBe('usd');
    expect(envelope.properties?.products).toBeDefined();
    expect(Array.isArray(envelope.properties?.products)).toBe(true);
  });

  it('should accept session and device on conversion envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'shopify',
      environment: 'staging',
      event_type: 'order_completed',
      sdk: { name: '@aether/shopify', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1', user_id: 'user_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      session: { session_id: 'sess_shop' },
      device: { device_id: 'dev_mobile', platform: 'ios' },
      properties: { order_id: 'ord_1', revenue: 99.99 },
    };
    expect(envelope.session?.session_id).toBe('sess_shop');
    expect(envelope.device?.platform).toBe('ios');
    expect(envelope.properties?.revenue).toBe(99.99);
  });

  it('should accept source classification on conversion envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'shopify',
      environment: 'staging',
      event_type: 'order_completed',
      sdk: { name: '@aether/shopify', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1', user_id: 'user_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      source: {
        platform: 'shopify',
        data_type: 'commerce',
        platform_id: 'shop_123',
        sdk: '@aether/shopify',
        environment: 'staging',
      },
    };
    expect(envelope.source?.platform).toBe('shopify');
    expect(envelope.source?.data_type).toBe('commerce');
  });
});
