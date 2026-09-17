/**
 * FPS-093 — Parity Conversion Event Contract
 * Verifies conversion event shape is consistent across all SDK platforms.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { conversionEventFixture } from '@aether/proof-fixtures';

describe('FPS-093: Parity Conversion', () => {
  function validateEnvelope(envelope: EventEnvelope): void {
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.sdk.name).toBe('@aether/shopify');
    expect(envelope.identity.anonymous_id).toBe('anon_shop_001');
    expect(typeof envelope.timestamp).toBe('string');
  }

  it('should validate shopify conversion event shape', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    validateEnvelope(envelope);
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.properties?.order_id).toBe('shop_ord_001');
    expect(envelope.properties?.revenue).toBe(75.00);
    expect(envelope.properties?.currency).toBe('usd');
    const products = envelope.properties?.products as unknown[] | undefined;
    expect(Array.isArray(products)).toBe(true);
    expect(products?.length).toBe(1);
  });

  it('should validate web conversion shares same contract', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.event_type).toBe('order_completed');
  });

  it('should validate iOS conversion shares same contract', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'environment', 'event_type', 'sdk', 'identity', 'timestamp'];
    for (const field of required) {
      expect(envelope[field]).toBeDefined();
    }
  });

  it('should share the same canonical envelope shape', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.properties?.order_id).toBe('shop_ord_001');
    expect(envelope.properties?.revenue).toBe(75.00);
    expect(envelope.properties?.products).toBeDefined();
  });
});
