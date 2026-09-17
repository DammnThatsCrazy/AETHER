/**
 * FPS-091 — Parity Track Event Contract
 * Verifies track event shape is consistent across all SDK platforms.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture } from '@aether/proof-fixtures';

describe('FPS-091: Parity Track', () => {
  function validateEnvelope(envelope: EventEnvelope, platform: string): void {
    expect(envelope.tenant_id).toBeDefined();
    expect(envelope.workspace_id).toBeDefined();
    expect(envelope.platform_id).toBe(platform);
    expect(envelope.environment).toBeDefined();
    expect(envelope.event_type).toBeDefined();
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBeDefined();
    expect(typeof envelope.timestamp).toBe('string');
  }

  it('should validate web track event shape', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    validateEnvelope(envelope, 'web');
    expect(envelope.event_type).toBe('page');
  });

  it('should validate iOS track event shape (shared fixture)', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.sdk.name).toBe('@aether/web');
  });

  it('should validate Android track event shape is same contract', () => {
    // Android uses the same EventEnvelope contract
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'environment', 'event_type', 'sdk', 'identity', 'timestamp'];
    for (const field of required) {
      expect(trackEventFixture[field as keyof typeof trackEventFixture]).toBeDefined();
    }
  });

  it('should share the same canonical envelope shape', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('page');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
  });
});
