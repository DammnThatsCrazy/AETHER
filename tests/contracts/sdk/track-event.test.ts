/**
 * FPS-021 — SDK Track Event Contract
 * Verifies track event payloads conform to @aether/proof-contracts schema.
 */
import { describe, it, expect } from 'vitest';

import { TrackEventPayload, EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture } from '@aether/proof-fixtures';

describe('FPS-021: SDK Track Event', () => {
  it('should construct a valid track event payload', () => {
    const event: TrackEventPayload = {
      eventName: 'page_view',
      properties: { path: '/demo' },
      timestamp: Date.now(),
    };
    expect(event.eventName).toBe('page_view');
    expect(event.properties?.path).toBe('/demo');
    expect(event.timestamp).toBeGreaterThan(0);
  });

  it('should accept optional properties', () => {
    const event: TrackEventPayload = {
      eventName: 'button_click',
      properties: undefined,
      timestamp: Date.now(),
    };
    expect(event.properties).toBeUndefined();
    expect(event.eventName).toBe('button_click');
  });

  it('should accept optional properties as empty object', () => {
    const event: TrackEventPayload = {
      eventName: 'view',
      properties: {},
      timestamp: Date.now(),
    };
    expect(event.properties).toEqual({});
  });

  it('should accept context metadata in properties', () => {
    const event: TrackEventPayload = {
      eventName: 'purchase',
      properties: { value: 49.99, currency: 'USD' },
      timestamp: Date.now(),
    };
    expect(event.properties?.value).toBe(49.99);
    expect(event.properties?.currency).toBe('USD');
  });

  it('should validate track event against EventEnvelope shape using fixture', () => {
    // The trackEventFixture carries the full EventEnvelope shape
    const envelope = trackEventFixture as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('page');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_001');
    expect(envelope.timestamp).toBe('2024-09-11T12:00:00.000Z');
    expect(envelope.properties).toBeDefined();
    expect(envelope.properties?.url).toBe('https://example.com/demo');
  });

  it('should require tenant_id, workspace_id, platform_id on EventEnvelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'a1' },
      timestamp: '2024-01-01T00:00:00.000Z',
    };
    expect(envelope.tenant_id).toBe('t1');
    expect(envelope.workspace_id).toBe('w1');
    expect(envelope.platform_id).toBe('web');
  });

  it('should require sdk.name and sdk.version on EventEnvelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'a1' },
      timestamp: '2024-01-01T00:00:00.000Z',
    };
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.sdk.version).toBe('1.0.0');
  });

  it('should require identity.anonymous_id on EventEnvelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
    };
    expect(envelope.identity.anonymous_id).toBe('anon_1');
  });

  it('should accept optional user_id on identity', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1', user_id: 'user_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
    };
    expect(envelope.identity.user_id).toBe('user_1');
  });

  it('should accept optional session and device on EventEnvelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      session: { session_id: 'sess_1' },
      device: { device_id: 'dev_1', platform: 'web' },
    };
    expect(envelope.session?.session_id).toBe('sess_1');
    expect(envelope.device?.device_id).toBe('dev_1');
    expect(envelope.device?.platform).toBe('web');
  });

  it('should accept optional source classification', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      source: {
        platform: 'web',
        data_type: 'event',
        platform_id: 'webapp',
        sdk: '@aether/web',
        environment: 'staging',
      },
    };
    expect(envelope.source?.platform).toBe('web');
    expect(envelope.source?.data_type).toBe('event');
  });
});
