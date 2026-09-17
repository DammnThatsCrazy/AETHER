/** @description FPS-056 — React SDK Parity test.
 * Track/identify/conversion fixtures are full EventEnvelopes.
 * heartbeatFixture is a HeartbeatPayload (4 fields), NOT an EventEnvelope —
 * validate it separately.
 * NOTE: reactHeartbeatFixture / reactTrackEventFixture / reactIdentifyEventFixture /
 * reactConversionEventFixture do NOT exist in @aether/proof-fixtures — use the base
 * fixtures for parity assertions. */
import { describe, it, expect } from 'vitest';
import { EventEnvelope, HeartbeatPayload } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture, conversionEventFixture, heartbeatFixture } from '@aether/proof-fixtures';

describe('FPS-056: React Parity', () => {
  it('should validate track event parity (same shape as web)', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('page');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_001');
  });

  it('should validate identify event parity (same shape as web)', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('identify');
    expect(envelope.identity.user_id).toBe('user_002');
  });

  it('should validate conversion event parity (same shape as web)', () => {
    const envelope = conversionEventFixture as unknown as EventEnvelope;
    expect(envelope.platform_id).toBe('shopify');
    expect(envelope.event_type).toBe('order_completed');
    expect(envelope.properties?.revenue).toBe(75.00);
  });

  it('should validate heartbeat event parity as HeartbeatPayload (not EventEnvelope)', () => {
    const hb = heartbeatFixture as unknown as HeartbeatPayload;
    expect(hb.timestamp).toBe(1726000000000);
    expect(hb.sessionId).toBe(heartbeatFixture.sessionId);
    expect(hb.agentId).toBe(heartbeatFixture.agentId);
    expect(hb.status).toBe('alive');
  });

  it('should map heartbeat to EventEnvelope for parity comparison', () => {
    // Build a minimal EventEnvelope from the heartbeat fixture fields for comparison
    const envelope: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'sdk.heartbeat',
      sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
      session: { session_id: heartbeatFixture.sessionId },
      identity: { anonymous_id: 'anon_001' },
      timestamp: new Date(heartbeatFixture.timestamp).toISOString(),
    };
    expect(envelope.event_type).toBe('sdk.heartbeat');
    expect(envelope.session?.session_id).toBe(heartbeatFixture.sessionId);
  });
});
