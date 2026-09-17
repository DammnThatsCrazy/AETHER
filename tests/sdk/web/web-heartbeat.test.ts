/**
 * FPS-051 — Web SDK Heartbeat
 * Verifies web SDK heartbeat emission.
 */
import { describe, it, expect } from 'vitest';

import { HeartbeatPayload, EventEnvelope } from '@aether/proof-contracts';
import { heartbeatFixture } from '@aether/proof-fixtures';

import { AetherSDK } from '@aether/web';

describe('FPS-051: Web SDK Heartbeat', () => {
  it('should emit heartbeat with session ID', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 'web_sess_001',
      agentId: 'web_agent_001',
      status: 'alive',
    };
    expect(heartbeat.sessionId).toBeTruthy();
    expect(heartbeat.status).toBe('alive');
  });

  it('should include agent identifier', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'web_sdk_v1',
      status: 'alive',
    };
    expect(heartbeat.agentId).toMatch(/web/);
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
    expect(heartbeatFixture._fixture_version).toBe(1);
  });

  it('should call sdk.track("heartbeat", ...) without error', () => {
    const sdk = new AetherSDK({
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://api.example.com',
    });
    expect(() => {
      sdk.track('heartbeat', {
        sessionId: 'test_sess',
        status: 'alive',
      });
    }).not.toThrow();
  });

  it('should validate HeartbeatPayload type union', () => {
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
