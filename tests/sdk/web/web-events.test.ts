/**
 * @vitest-environment jsdom
 */
/**
 * FPS-052 — Web SDK Events
 * Verifies web SDK track/identify/conversion event emission.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture, conversionEventFixture } from '@aether/proof-fixtures';
import { AetherSDK } from '@aether/web';
// Top-level DOM shims before SDK evaluation
if (typeof globalThis.screen === 'undefined') (globalThis as any).screen = { width: 1920, height: 1080, colorDepth: 24 } as any;
if (typeof globalThis.window !== 'undefined' && !(globalThis.window as any).screen) (globalThis.window as any).screen = (globalThis as any).screen;


describe('FPS-052: Web SDK Events', () => {
  it('should track a page_view event', () => {
    const sdk = new AetherSDK();
    expect(() => {
      sdk.track('page_view', { path: '/demo', referrer: 'https://example.com' });
    }).not.toThrow();
  });

  it('should track a custom event', () => {
    const sdk = new AetherSDK();
    expect(() => {
      sdk.track('button_click', { button: 'signup', section: 'header' });
    }).not.toThrow();
  });

  it('should identify a user via hydrateIdentity', () => {
    const sdk = new AetherSDK();
    expect(() => {
      // The web SDK uses hydrateIdentity for identity, not identify().
      sdk.hydrateIdentity({ email: 'web@example.com', plan: 'pro' } as any);
    }).not.toThrow();
  });

  it('should record a conversion event', () => {
    const sdk = new AetherSDK();
    expect(() => {
      sdk.conversion('purchase', 99.99, { currency: 'USD' });
    }).not.toThrow();
  });

  it('should use track event fixture with full EventEnvelope shape', () => {
    const props = trackEventFixture.properties as Record<string, unknown>;
    expect(trackEventFixture.tenant_id).toBe('aether-proof-tenant');
    expect(trackEventFixture.event_type).toBe('page');
    expect(props.url).toBe('https://example.com/demo');
    expect(props.path).toBe('/demo');
    expect(props.referrer).toBe('https://google.com');
    expect(props.title).toBe('Demo Page');
  });

  it('should use identify event fixture with traits', () => {
    const props = identifyEventFixture.properties as Record<string, unknown>;
    expect(identifyEventFixture.event_type).toBe('identify');
    expect(identifyEventFixture.identity.user_id).toBe('user_002');
    const traits = props.traits as Record<string, unknown>;
    expect(traits.email).toBe('test@example.com');
    expect(traits.plan).toBe('premium');
    expect(traits.name).toBe('Test User');
  });

  it('should use conversion event fixture with order details', () => {
    const props = conversionEventFixture.properties as Record<string, unknown>;
    expect(conversionEventFixture.event_type).toBe('order_completed');
    expect(props.order_id).toBe('shop_ord_001');
    expect(props.revenue).toBe(75.00);
    expect(props.currency).toBe('usd');
    const products = props.products as unknown[];
    expect(Array.isArray(products)).toBe(true);
    expect(products.length).toBe(1);
  });

  it('should call sdk.pageView without error', () => {
    const sdk = new AetherSDK();
    expect(() => {
      sdk.pageView('/demo', { referrer: 'https://example.com' });
    }).not.toThrow();
  });

  it('should call sdk.reset without error', () => {
    const sdk = new AetherSDK();
    expect(() => sdk.reset()).not.toThrow();
  });
});
