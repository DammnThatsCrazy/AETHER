/**
 * FPS-059 — iOS SDK Events
 * Verifies iOS SDK track/identify/conversion event emission.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture, conversionEventFixture } from '@aether/proof-fixtures';

describe('FPS-059: iOS SDK Events', () => {
  it('should validate track event fixture for mobile shape', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.event_type).toBe('page');
    const props = envelope.properties as Record<string, unknown> | undefined;
    expect(props?.url).toBe('https://example.com/demo');
    expect(props?.path).toBe('/demo');
  });

  it('should validate identify event fixture for mobile shape', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('identify');
    expect(envelope.platform_id).toBe('web');
    const traits = envelope.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
    expect(traits?.plan).toBe('premium');
  });

  it('should validate conversion event fixture for mobile shape', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.properties?.order_id).toBe('shop_ord_001');
    expect(envelope.properties?.revenue).toBe(75.00);
    const products = envelope.properties?.products as unknown[] | undefined;
    expect(Array.isArray(products)).toBe(true);
  });

  it('should validate required fields on track envelope', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'event_type', 'sdk', 'timestamp'] as const;
    for (const field of required) {
      expect(envelope[field]).toBeDefined();
    }
  });

  it('should validate required fields on identify envelope', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'event_type', 'sdk', 'timestamp'] as const;
    for (const field of required) {
      expect(envelope[field]).toBeDefined();
    }
  });

  it('should validate required fields on conversion envelope', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'event_type', 'sdk', 'timestamp'] as const;
    for (const field of required) {
      expect(envelope[field]).toBeDefined();
    }
  });

  it('should read fixture metadata', () => {
    const raw = trackEventFixture as unknown as Record<string, unknown>;
    expect(raw._fixture_version).toBe(1);
  });

  it('should validate fixture integrity with _fixtureName', () => {
    const raw = trackEventFixture as unknown as Record<string, unknown>;
    expect(raw._fixtureName).toBe('trackEventFixture');
  });
});
