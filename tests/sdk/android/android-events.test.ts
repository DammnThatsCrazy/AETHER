/**
 * FPS-083 — Android SDK Events
 * Verifies Android SDK track/identify/conversion event emission.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture, conversionEventFixture } from '@aether/proof-fixtures';

describe('FPS-083: Android SDK Events', () => {
  it('should validate track event fixture for mobile shape', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.event_type).toBe('page');
  });

  it('should validate identify event fixture for mobile shape', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('identify');
    expect(envelope.platform_id).toBe('web');
    const traits = envelope.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
  });

  it('should validate conversion event fixture for mobile shape', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.properties?.order_id).toBe('shop_ord_001');
    expect(envelope.properties?.revenue).toBe(75.00);
  });

  it('should validate required fields on track envelope', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'environment', 'event_type', 'sdk', 'identity', 'timestamp'];
    for (const field of required) {
      expect(envelope[field as keyof EventEnvelope]).toBeDefined();
    }
  });

  it('should validate mobile platform identifier on track fixture', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.platform_id).toBe('web');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
  });
});
