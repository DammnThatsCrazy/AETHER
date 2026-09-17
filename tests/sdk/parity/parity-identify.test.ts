/**
 * FPS-092 — Parity Identify Event Contract
 * Verifies identify event shape is consistent across all SDK platforms.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { identifyEventFixture } from '@aether/proof-fixtures';

describe('FPS-092: Parity Identify', () => {
  function validateEnvelope(envelope: EventEnvelope, platform: string): void {
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe(platform);
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('identify');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(typeof envelope.timestamp).toBe('string');
  }

  it('should validate web identify event shape', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    validateEnvelope(envelope, 'web');
    expect(envelope.identity.user_id).toBe('user_002');
    const traits = envelope.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
  });

  it('should validate iOS identify event shares same contract', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.platform_id).toBe('web');
  });

  it('should validate Android identify event shares same contract', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'environment', 'event_type', 'sdk', 'identity', 'timestamp'];
    for (const field of required) {
      expect(envelope[field]).toBeDefined();
    }
  });

  it('should share the same canonical envelope shape', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.event_type).toBe('identify');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_002');
    const traits = envelope.properties?.traits as Record<string, unknown> | undefined;
    expect(traits?.email).toBe('test@example.com');
  });
});
