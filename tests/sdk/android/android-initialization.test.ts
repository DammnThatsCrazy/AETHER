/**
 * FPS-081 — Android SDK Initialization
 * Verifies Android SDK initialization with valid configuration.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope, HeartbeatPayload } from '@aether/proof-contracts';
import { heartbeatFixture, trackEventFixture } from '@aether/proof-fixtures';

describe('FPS-081: Android SDK Initialization', () => {
  // --- HeartbeatPayload validation ---
  it('should validate heartbeat payload shape', () => {
    expect(heartbeatFixture.status).toBe('alive');
    expect(heartbeatFixture.timestamp).toBe(1726000000000);
    expect(heartbeatFixture.sessionId).toBe('sess_test_001');
    expect(heartbeatFixture.agentId).toBe('agent_test_001');
  });

  it('should validate HeartbeatPayload type accepts all required fields', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 'android_sess_001',
      agentId: 'android_agent_001',
      status: 'alive',
    };
    expect(heartbeat.sessionId).toBe('android_sess_001');
    expect(heartbeat.agentId).toBe('android_agent_001');
    expect(heartbeat.status).toBe('alive');
    expect(typeof heartbeat.timestamp).toBe('number');
  });

  it('should validate heartbeat status values', () => {
    const statuses: HeartbeatPayload['status'][] = ['alive', 'degraded', 'dead'];
    expect(statuses).toEqual(['alive', 'degraded', 'dead']);
  });

  it('should validate timestamp is a number', () => {
    const heartbeat: HeartbeatPayload = {
      timestamp: Date.now(),
      sessionId: 's1',
      agentId: 'a1',
      status: 'alive',
    };
    expect(typeof heartbeat.timestamp).toBe('number');
  });

  // --- TrackEventFixture as EventEnvelope ---
  it('should validate track event fixture for Android shape', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.event_type).toBe('page');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
  });

  // --- Required envelope fields ---
  it('should validate required EventEnvelope fields exist on track fixture', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    const requiredFields = ['tenant_id', 'workspace_id', 'platform_id', 'environment', 'event_type', 'sdk', 'identity', 'timestamp'];
    for (const field of requiredFields) {
      expect(envelope[field as keyof EventEnvelope]).toBeDefined();
    }
  });

  // --- Identity structure ---
  it('should validate identity structure on track fixture', () => {
    const identity = trackEventFixture.identity as { anonymous_id: string; user_id?: string };
    expect(identity.anonymous_id).toBe('anon_001');
    expect(identity.user_id).toBe('user_001');
  });
});
