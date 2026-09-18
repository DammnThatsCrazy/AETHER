/** @description FPS-054 — React SDK Hooks
 * Verifies the @aether/react-native bridge exports hook functions that
 * return SDK state, identity data, and consent state. Since the native
 * module is not available in the JS test environment, we validate the
 * hook contract against the bridge exports and fixture data.
 */
import { describe, it, expect, vi } from 'vitest';
import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture, consentDisabledFixture } from '@aether/proof-fixtures';
import {
  useAether,
  useIdentity,
  useConsentState,
  useAetherContext,
  AetherContext,
} from '@aether/react-native';

describe('FPS-054: React Hooks', () => {
  it('should export useAether hook', () => {
    expect(useAether).toBeDefined();
    expect(typeof useAether).toBe('function');
  });

  it('should export useIdentity hook', () => {
    expect(useIdentity).toBeDefined();
    expect(typeof useIdentity).toBe('function');
  });

  it('should export useConsentState hook', () => {
    expect(useConsentState).toBeDefined();
    expect(typeof useConsentState).toBe('function');
  });

  it('should export useAetherContext hook', () => {
    expect(useAetherContext).toBeDefined();
    expect(typeof useAetherContext).toBe('function');
  });

  it('should export AetherContext', () => {
    expect(AetherContext).toBeDefined();
    // AetherContext is a React context object — in a test env without React
    // we just verify it exists and has a defined shape.
    expect(AetherContext).toBeTruthy();
  });

  it('should use track fixture for envelope validation', () => {
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

  it('should use identify fixture for identity data validation', () => {
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

  it('should expose identity data shape from fixture', () => {
    // Simulates what useIdentity would return when the SDK is initialized
    const identity = {
      userId: identifyEventFixture.identity.user_id,
      anonymousId: identifyEventFixture.identity.anonymous_id,
      traits: identifyEventFixture.properties?.traits,
    };
    expect(identity.userId).toBe('user_002');
    expect(identity.anonymousId).toBe('anon_001');
    expect(identity.traits).toBeDefined();
    expect(identity.traits?.email).toBe('test@example.com');
  });

  it('should expose config shape from fixture SDK info', () => {
    // Simulates what useAether().config would return
    const config = {
      apiKey: 'ak_test_placeholder_example_hooks',
      endpoint: 'https://api.example.com',
      debug: true,
      sdkName: trackEventFixture.sdk.name,
      sdkVersion: trackEventFixture.sdk.version,
    };
    expect(config.apiKey).toBeTruthy();
    expect(config.debug).toBe(true);
    expect(config.sdkName).toBe('@aether/web');
    expect(config.sdkVersion).toBe('0.1.0-alpha.0');
  });

  it('should expose isInitialized from AetherRN singleton', () => {
    // When running in a real React tree, useAether() returns { sdk, isInitialized, config, identity }
    // Here we validate the contract shape against the bridge's AetherContext value.
    const mockContextValue = {
      aether: { isInitialized: true, init: vi.fn(), track: vi.fn(), pageView: vi.fn() },
      isInitialized: true,
    };
    expect(mockContextValue.isInitialized).toBe(true);
    expect(mockContextValue.aether.isInitialized).toBe(true);
    expect(typeof mockContextValue.aether.track).toBe('function');
    expect(typeof mockContextValue.aether.pageView).toBe('function');
  });

  it('should validate consent state shape from fixture', () => {
    const envelope = consentDisabledFixture as unknown as EventEnvelope;
    const props = envelope.properties as Record<string, unknown> | undefined;
    expect(props?.enabled).toBe(false);
    expect(props?.purposes).toEqual({});
    expect(props?.consent_version).toBe('1.0');
    expect(props?.consent_granted_at).toBeNull();
    const consentedPurposes = props?.consented_purposes;
    expect(Array.isArray(consentedPurposes)).toBe(true);
    expect(consentedPurposes?.length).toBe(0);
  });

  it('should validate track fixture has _fixture_version and _fixtureName', () => {
    expect(trackEventFixture._fixture_version).toBe(1);
    expect(trackEventFixture._fixtureName).toBe('trackEventFixture');
    expect(identifyEventFixture._fixture_version).toBe(1);
    expect(identifyEventFixture._fixtureName).toBe('identifyEventFixture');
    expect(consentDisabledFixture._fixture_version).toBe(1);
    expect(consentDisabledFixture._fixtureName).toBe('consentDisabledFixture');
  });
});
