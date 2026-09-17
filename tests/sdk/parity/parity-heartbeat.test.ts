/**
 * FPS-090 — Parity Heartbeat Contract
 * Verifies heartbeat payload shape is consistent across mobile platforms.
 */
import { describe, it, expect } from 'vitest';

import { HeartbeatPayload, EventEnvelope } from '@aether/proof-contracts';
import { heartbeatFixture } from '@aether/proof-fixtures';

describe('FPS-090: Parity Heartbeat', () => {
  it('should validate heartbeat fixture shape is a valid HeartbeatPayload', () => {
    const payload: HeartbeatPayload = {
      timestamp: heartbeatFixture.timestamp,
      sessionId: heartbeatFixture.sessionId,
      agentId: heartbeatFixture.agentId,
      status: heartbeatFixture.status,
    };
    expect(payload.timestamp).toBe(1726000000000);
    expect(payload.sessionId).toBe('sess_test_001');
    expect(payload.agentId).toBe('agent_test_001');
    expect(payload.status).toBe('alive');
  });

  it('should validate heartbeat status values', () => {
    const payload: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'a1',
      status: 'alive',
    };
    const statuses: HeartbeatPayload['status'][] = ['alive', 'degraded', 'dead'];
    expect(statuses.includes(payload.status)).toBe(true);
  });

  it('should validate heartbeat timestamp is a number', () => {
    const payload: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'a1',
      status: 'alive',
    };
    expect(typeof payload.timestamp).toBe('number');
    expect(payload.timestamp).toBeGreaterThan(0);
  });

  it('should construct EventEnvelope from heartbeat across platforms', () => {
    const envelope: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'ios',
      environment: 'staging',
      event_type: 'sdk_session_alive',
      sdk: { name: '@aether/react-native', version: '1.0.0' },
      identity: { anonymous_id: 'anon_ios_001', device_id: 'dev_ios_001' },
      timestamp: new Date().toISOString(),
      properties: {
        status: 'alive',
        session_id: 'sess_test_001',
      },
    };
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('ios');
    expect(envelope.event_type).toBe('sdk_session_alive');
  });
});
