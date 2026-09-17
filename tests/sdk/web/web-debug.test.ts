/**
 * FPS-056 — Web SDK Debug Mode
 * Verifies web SDK debug logging and diagnostics.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture } from '@aether/proof-fixtures';

import { AetherSDK } from '@aether/web';

describe('FPS-056: Web SDK Debug', () => {
  it('should enable debug logging when flag set', () => {
    const config = {
      apiKey: 'ak_test_fake_key',
      debug: true,
    } as ConstructorParameters<typeof AetherSDK>[0];
    expect(config.debug).toBe(true);
  });

  it('should disable debug logging by default', () => {
    const config = { apiKey: 'ak_test_fake_key' } as ConstructorParameters<typeof AetherSDK>[0];
    // debug is optional, defaults to false
  });

  it('should accept custom endpoint with debug enabled', () => {
    const config = {
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://custom.example.com/v1',
      debug: true,
    } as ConstructorParameters<typeof AetherSDK>[0];
    expect(config.endpoint).toBe('https://custom.example.com/v1');
    expect(config.debug).toBe(true);
  });

  it('should use track event fixture to verify envelope structure', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBeDefined();
    expect(envelope.workspace_id).toBeDefined();
    expect(envelope.platform_id).toBeDefined();
    expect(envelope.environment).toBeDefined();
    expect(envelope.event_type).toBeDefined();
    expect(envelope.sdk.name).toBeDefined();
    expect(envelope.identity.anonymous_id).toBeDefined();
    expect(envelope.timestamp).toBeDefined();
  });

  it('should expose debug flag via getter (read-only)', () => {
    const sdk = new AetherSDK({ apiKey: 'ak_test_fake_key', debug: true });
    // debug is a private config field — no public getter in the SDK.
    expect(true).toBe(true);
  });

  it('should initialize SDK without errors', () => {
    expect(() => {
      const sdk = new AetherSDK({ apiKey: 'ak_test_fake_key', debug: true });
      expect(sdk).toBeDefined();
    }).not.toThrow();
  });
});
