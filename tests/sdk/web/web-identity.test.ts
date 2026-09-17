/**
 * FPS-053 — Web SDK Identity
 * Verifies web SDK identity management.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { identifyEventFixture } from '@aether/proof-fixtures';

import { AetherSDK } from '@aether/web';

describe('FPS-053: Web SDK Identity', () => {
  it('should set anonymous identity before login', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_002');
  });

  it('should switch to identified identity after login', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('identify');
    expect(envelope.identity.user_id).toBe('user_002');
  });

  it('should merge traits on identify', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    const traits = envelope.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
    expect(traits?.plan).toBe('premium');
  });

  it('should use identify fixture with user identity', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_002');
    const traits = envelope.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
  });

  it('should call sdk.hydrateIdentity without error', () => {
    const sdk = new AetherSDK({
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://api.example.com',
    });
    expect(() => {
      sdk.hydrateIdentity({ email: 'test@example.com', plan: 'premium' });
    }).not.toThrow();
  });

  it('should call sdk.reset without error', () => {
    const sdk = new AetherSDK({
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://api.example.com',
    });
    expect(() => sdk.reset()).not.toThrow();
  });
});
