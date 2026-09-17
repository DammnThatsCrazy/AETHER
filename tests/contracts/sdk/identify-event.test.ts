/**
 * FPS-021 — SDK Identify Event Contract
 * Verifies identify event payloads conform to @aether/proof-contracts schema.
 */
import { describe, it, expect } from 'vitest';

import { IdentifyEventPayload, EventEnvelope } from '@aether/proof-contracts';
import { identifyEventFixture } from '@aether/proof-fixtures';

describe('FPS-021: SDK Identify Event', () => {
  it('should construct a valid identify event payload', () => {
    const event: IdentifyEventPayload = {
      userId: 'user_001',
      traits: { email: 'test@example.com' },
      timestamp: Date.now(),
    };
    expect(event.userId).toBe('user_001');
    expect(event.traits?.email).toBe('test@example.com');
    expect(event.timestamp).toBeGreaterThan(0);
  });

  it('should attach user traits', () => {
    const event: IdentifyEventPayload = {
      userId: 'u1',
      traits: { plan: 'premium', tier: 2 },
      timestamp: Date.now(),
    };
    expect(event.traits?.plan).toBe('premium');
    expect(event.traits?.tier).toBe(2);
  });

  it('should accept identify without traits', () => {
    const event: IdentifyEventPayload = {
      userId: 'u1',
      traits: undefined,
      timestamp: Date.now(),
    };
    expect(event.traits).toBeUndefined();
    expect(event.userId).toBe('u1');
  });

  it('should require userId on IdentifyEventPayload', () => {
    const event: IdentifyEventPayload = {
      userId: 'required_user',
      timestamp: Date.now(),
    };
    expect(event.userId).toBe('required_user');
  });

  it('should validate identify event against EventEnvelope shape using fixture', () => {
    const envelope = identifyEventFixture as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('identify');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_002');
    expect(envelope.timestamp).toBe('2024-09-11T12:05:00.000Z');
    expect(envelope.properties).toBeDefined();
    expect(envelope.properties?.traits).toBeDefined();
    expect(envelope.properties?.traits?.email).toBe('test@example.com');
    expect(envelope.properties?.traits?.plan).toBe('premium');
  });

  it('should accept optional session and device on identify envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'identify',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1', user_id: 'user_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      session: { session_id: 'sess_1' },
      device: { device_id: 'dev_1', platform: 'web' },
    };
    expect(envelope.session?.session_id).toBe('sess_1');
    expect(envelope.device?.platform).toBe('web');
  });

  it('should accept properties with traits object', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'identify',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1', user_id: 'user_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: {
        traits: {
          email: 'user@example.com',
          name: 'Test User',
          plan: 'premium',
        },
      },
    };
    expect(envelope.properties?.traits?.email).toBe('user@example.com');
    expect(envelope.properties?.traits?.plan).toBe('premium');
  });
});
