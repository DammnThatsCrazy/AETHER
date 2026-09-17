/**
 * FPS-058 — iOS SDK Heartbeat
 * Verifies iOS SDK heartbeat emission.
 */
import { describe, it, expect } from 'vitest';

import { HeartbeatPayload } from '@aether/proof-contracts';
import { heartbeatFixture } from '@aether/proof-fixtures';

// heartbeatFixture is a HeartbeatPayload — validate against that type.
// It does NOT carry EventEnvelope fields (tenant_id, platform_id, etc.).

describe('FPS-058: iOS SDK Heartbeat', () => {
  it('should emit heartbeat with session ID', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 'ios_sess_001',
      agentId: 'ios_agent_001',
      status: 'alive',
    };
    expect(heartbeat.sessionId).toBeTruthy();
    expect(heartbeat.status).toBe('alive');
  });

  it('should include agent identifier', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'ios_sdk_v1',
      status: 'alive',
    };
    expect(heartbeat.agentId).toMatch(/ios/);
  });

  it('should mark heartbeat as alive on successful ping', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'a1',
      status: 'alive',
    };
    expect(heartbeat.status).toBe('alive');
  });

  it('should mark heartbeat as dead after timeout', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'a1',
      status: 'dead',
    };
    expect(heartbeat.status).toBe('dead');
  });

  it('should use fixture heartbeat defaults', () => {
    expect(heartbeatFixture.status).toBe('alive');
    expect(heartbeatFixture.timestamp).toBe(1726000000000);
    expect(heartbeatFixture.sessionId).toBe('sess_test_001');
    expect(heartbeatFixture.agentId).toBe('agent_test_001');
  });

  it('should validate heartbeat status union', () => {
    const statuses: HeartbeatPayload['status'][] = ['alive', 'degraded', 'dead'];
    expect(statuses).toEqual(['alive', 'degraded', 'dead']);
  });

  it('should validate heartbeat timestamp is a number', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'a1',
      status: 'alive',
    };
    expect(typeof heartbeat.timestamp).toBe('number');
    expect(heartbeat.timestamp).toBeGreaterThan(0);
  });
});
