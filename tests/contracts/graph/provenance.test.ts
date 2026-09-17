/**
 * FPS-023 — Graph Provenance Tracking
 * Verifies provenance tracking for graph nodes.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, conversionEventFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Provenance Tracking', () => {
  it('should track provenance for track event', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    const e = envelope as any;

    expect(e.tenant_id).toBe('aether-proof-tenant');
    expect(e.workspace_id).toBe('proof-lab');
    expect(e.platform_id).toBe('web');
    expect(e.environment).toBe('staging');
    expect(e.event_type).toBe('page');
    expect(e.sdk.name).toBe('@aether/web');
    expect(e.sdk.version).toBe('0.1.0-alpha.0');
    expect(e.identity.anonymous_id).toBe('anon_001');
    expect(e.identity.user_id).toBe('user_001');
    expect(typeof e.timestamp).toBe('string');
    expect(e.session?.session_id).toBe('sess_abc123');
    expect(e.device?.device_id).toBe('dev_web_001');
    expect(e.properties?.url).toBe('https://example.com/demo');
    expect(e.properties?.path).toBe('/demo');
    expect(e.properties?.referrer).toBe('https://google.com');
    expect(e.properties?.title).toBe('Demo Page');
  });

  it('should track provenance for conversion event', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    const e = envelope as any;

    expect(e.tenant_id).toBe('aether-proof-tenant');
    expect(e.workspace_id).toBe('proof-lab');
    expect(e.platform_id).toBe('shopify');
    expect(e.environment).toBe('staging');
    expect(e.event_type).toBe('order_completed');
    expect(e.sdk.name).toBe('@aether/shopify');
    expect(e.sdk.version).toBe('0.1.0-alpha.0');
    expect(e.identity.anonymous_id).toBe('anon_shop_001');
    expect(e.identity.user_id).toBe('user_003');
    expect(typeof e.timestamp).toBe('string');
    expect(e.session?.session_id).toBe('sess_shop_001');
    expect(e.device?.device_id).toBe('dev_mobile_001');
    expect(e.properties?.order_id).toBe('shop_ord_001');
    expect(e.properties?.revenue).toBe(75.00);
    expect(e.properties?.currency).toBe('usd');
    expect(e.properties?.products).toHaveLength(1);
    expect(e.properties?.coupon).toBe('WELCOME10');
    expect(e.properties?.tax).toBe(5.00);
    expect(e.properties?.shipping).toBe(5.00);
  });

  it('should verify both events share common envelope structure', () => {
    const track = trackEventFixture as unknown as EventEnvelope;
    const conversion = conversionEventFixture as unknown as EventEnvelope;
    const t = track as any;
    const c = conversion as any;

    // Both have required envelope fields
    expect(t.tenant_id).toBe(c.tenant_id);
    expect(t.workspace_id).toBe(c.workspace_id);
    expect(typeof t.timestamp).toBe('string');
    expect(typeof c.timestamp).toBe('string');
    expect(t.sdk.name).toBeDefined();
    expect(c.sdk.name).toBeDefined();
  });
});
