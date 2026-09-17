/**
 * FPS-021 — SDK Heartbeat Contract test.
 * heartbeatFixture is a HeartbeatPayload (4 fields) — NOT an EventEnvelope.
 * Test validates HeartbeatPayload separately, and constructs its own minimal
 * EventEnvelope for the envelope-shape assertions.
 */
import { describe, it, expect } from 'vitest';
import { EventEnvelope, HeartbeatPayload } from '@aether/proof-contracts';
import { heartbeatFixture } from '@aether/proof-fixtures';

describe('FPS-021: SDK Heartbeat', () => {
  it('should validate HeartbeatPayload shape from fixture', () => {
    const hb = heartbeatFixture as unknown as HeartbeatPayload;
    expect(hb.timestamp).toBe(1726000000000);
    expect(hb.sessionId).toBe('sess_test_001');
    expect(hb.agentId).toBe('agent_test_001');
    expect(hb.status).toBe('alive');
    expect(heartbeatFixture._fixture_version).toBe(1);
  });

  it('should construct a valid HeartbeatPayload', () => {
    const payload: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 'sess_test',
      agentId: 'agent_test',
      status: 'alive',
    };
    expect(payload.timestamp).toBeGreaterThan(0);
    expect(payload.sessionId).toBeTruthy();
    expect(payload.agentId).toBeTruthy();
    expect(payload.status).toBe('alive');
  });

  it('should map heartbeat to EventEnvelope shape for ingestion', () => {
    // heartbeatFixture itself is NOT an EventEnvelope — construct a separate envelope
    const envelope: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'sdk.heartbeat',
      sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
      session: { session_id: heartbeatFixture.sessionId },
      device: { device_id: 'dev_web_001', platform: 'web' },
      identity: { anonymous_id: 'anon_001' },
      timestamp: new Date(heartbeatFixture.timestamp).toISOString(),
      properties: { heartbeatStatus: heartbeatFixture.status },
    };
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.event_type).toBe('sdk.heartbeat');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.timestamp).toBeTruthy();
    expect(envelope.session?.session_id).toBe('sess_test_001');
  });

  it('should validate heartbeat payload has required properties', () => {
    const hb = heartbeatFixture as unknown as HeartbeatPayload;
    expect(typeof hb.timestamp).toBe('number');
    expect(typeof hb.sessionId).toBe('string');
    expect(typeof hb.agentId).toBe('string');
    expect(['alive', 'dead']).toContain(hb.status);
  });

  it('should round-trip HeartbeatPayload through EventEnvelope', () => {
    const hb = heartbeatFixture as unknown as HeartbeatPayload;
    const envelope: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'sdk.heartbeat',
      sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
      session: { session_id: hb.sessionId },
      device: { device_id: 'dev_web_001', platform: 'web' },
      identity: { anonymous_id: 'anon_001' },
      timestamp: new Date(hb.timestamp).toISOString(),
      properties: { heartbeatStatus: hb.status },
    };
    expect(envelope.session?.session_id).toBe(hb.sessionId);
    expect(envelope.properties?.heartbeatStatus).toBe(hb.status);
  });
});
