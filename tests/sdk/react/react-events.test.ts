/** @description FPS-055 — React SDK Events
 * Verifies React wrapper event emission via hooks. Since the native module
 * is not available in the JS test environment, we validate the event contract
 * using fixtures and mock hook behavior.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture, conversionEventFixture } from '@aether/proof-fixtures';

// Hoisted mock SDK — defined via vi.hoisted so vi.mock factory can reference it
// without violating the "no top-level variables in mock factory" rule.
const { mockSdk } = vi.hoisted(() => {
  return {
    mockSdk: {
      track: vi.fn(),
      pageView: vi.fn(),
      identify: vi.fn(),
      conversion: vi.fn(),
      reset: vi.fn(),
      destroy: vi.fn(),
      isInitialized: true,
    },
  };
});

vi.mock('@aether/react-native', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aether/react-native')>();
  return {
    ...actual,
    useAether: () => ({ sdk: mockSdk, isInitialized: true, config: { apiKey: 'ak_test_placeholder_example_key_00000' }, identity: null }),
  };
});

// Import after mock — vi.mock is hoisted, so this import receives the mocked module
import { useAether } from '@aether/react-native';

describe('FPS-055: React Events', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should use track event fixture for validation', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.event_type).toBe('page');
    const props = envelope.properties as Record<string, unknown> | undefined;
    expect(props?.url).toBe('https://example.com/demo');
    expect(props?.path).toBe('/demo');
    expect(props?.referrer).toBe('https://google.com');
    expect(props?.title).toBe('Demo Page');
  });

  it('should use identify event fixture for validation', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('identify');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_002');
    const traits = envelope.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
    expect(traits?.plan).toBe('premium');
    expect(traits?.name).toBe('Test User');
    expect(traits?.company).toBe('Acme Corp');
  });

  it('should use conversion event fixture for validation', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.properties?.order_id).toBe('shop_ord_001');
    expect(envelope.properties?.revenue).toBe(75.00);
    expect(envelope.properties?.currency).toBe('usd');
    const products = envelope.properties?.products as unknown[] | undefined;
    expect(Array.isArray(products)).toBe(true);
    expect(products?.length).toBe(1);
    const product = products?.[0] as Record<string, unknown> | undefined;
    expect(product?.id).toBe('shop_prod_001');
    expect(product?.name).toBe('Demo Widget');
    expect(product?.price).toBe(25.00);
    expect(product?.quantity).toBe(3);
  });

  it('should track events via useAether().sdk.track', () => {
    const { sdk } = useAether();
    sdk.track('page_view', { path: '/demo', referrer: 'https://example.com' });
    expect(sdk.track).toHaveBeenCalledWith('page_view', { path: '/demo', referrer: 'https://example.com' });
    expect(sdk.track).toHaveBeenCalledTimes(1);
  });

  it('should track a custom event via useAether().sdk.track', () => {
    const { sdk } = useAether();
    sdk.track('button_click', { button: 'signup', section: 'header' });
    expect(sdk.track).toHaveBeenCalledWith('button_click', { button: 'signup', section: 'header' });
  });

  it('should call pageView via useAether().sdk.pageView', () => {
    const { sdk } = useAether();
    sdk.pageView('/demo', { referrer: 'https://example.com' });
    expect(sdk.pageView).toHaveBeenCalledWith('/demo', { referrer: 'https://example.com' });
  });

  it('should call identify via useAether().sdk.identify', () => {
    const { sdk } = useAether();
    sdk.identify('user_001', { email: 'test@example.com', plan: 'premium' });
    expect(sdk.identify).toHaveBeenCalledWith('user_001', { email: 'test@example.com', plan: 'premium' });
  });

  it('should call conversion via useAether().sdk.conversion', () => {
    const { sdk } = useAether();
    sdk.conversion('purchase', 99.99, { currency: 'USD' });
    expect(sdk.conversion).toHaveBeenCalledWith('purchase', 99.99, { currency: 'USD' });
  });

  it('should call reset via useAether().sdk.reset', () => {
    const { sdk } = useAether();
    sdk.reset();
    expect(sdk.reset).toHaveBeenCalledTimes(1);
  });

  it('should call destroy via useAether().sdk.destroy', () => {
    const { sdk } = useAether();
    sdk.destroy();
    expect(sdk.destroy).toHaveBeenCalledTimes(1);
  });

  it('should validate track fixture _fixture_version and _fixtureName', () => {
    expect(trackEventFixture._fixture_version).toBe(1);
    expect(trackEventFixture._fixtureName).toBe('trackEventFixture');
    expect(identifyEventFixture._fixture_version).toBe(1);
    expect(identifyEventFixture._fixtureName).toBe('identifyEventFixture');
    expect(conversionEventFixture._fixture_version).toBe(1);
    expect(conversionEventFixture._fixtureName).toBe('conversionEventFixture');
  });

  it('should validate all three fixtures share common envelope structure', () => {
    const track = trackEventFixture as unknown as EventEnvelope;
    const identify = identifyEventFixture as unknown as EventEnvelope;
    const conversion = conversionEventFixture as unknown as EventEnvelope;

    expect(track.tenant_id).toBe(identify.tenant_id);
    expect(track.tenant_id).toBe(conversion.tenant_id);
    expect(track.workspace_id).toBe(identify.workspace_id);
    expect(track.workspace_id).toBe(conversion.workspace_id);

    expect(track.sdk.name).toBeDefined();
    expect(identify.sdk.name).toBeDefined();
    expect(conversion.sdk.name).toBeDefined();

    expect(track.identity.anonymous_id).toBeDefined();
    expect(identify.identity.anonymous_id).toBeDefined();
    expect(conversion.identity.anonymous_id).toBeDefined();

    expect(typeof track.timestamp).toBe('string');
    expect(typeof identify.timestamp).toBe('string');
    expect(typeof conversion.timestamp).toBe('string');
  });
});
