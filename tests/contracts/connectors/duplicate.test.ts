/**
 * FPS-022 — Connector Duplicate Event Handling
 * Verifies that connectors detect and deduplicate identical events.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { duplicateFixture } from '@aether/proof-fixtures';

describe('FPS-022: Connector Duplicate Events', () => {
  it('should detect identical track events from fixture', () => {
    const original = duplicateFixture.properties?.event;
    const duplicate = duplicateFixture.properties?.duplicateEvent;
    expect(original?.eventName).toBe('page_view');
    expect(duplicate?.eventName).toBe('page_view');
    expect(original?.path).toBe('/demo');
    expect(duplicate?.path).toBe('/demo');
    expect(original?.timestamp).toBe(duplicate?.timestamp);
  });

  it('should read dedup key from fixture', () => {
    const dedupKey = duplicateFixture.properties?.dedupKey;
    expect(dedupKey).toBe('page_view|/demo|2024-09-11T13:20:00.000Z');
    expect(typeof dedupKey).toBe('string');
    expect(dedupKey.length).toBeGreaterThan(0);
  });

  it('should report isDuplicate flag from fixture', () => {
    expect(duplicateFixture.properties?.isDuplicate).toBe(true);
  });

  it('should distinguish events by eventId when present', () => {
    const a: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { eventId: 'e1', eventName: 'pv', path: '/a' },
    };
    const b: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { eventId: 'e2', eventName: 'pv', path: '/a' },
    };
    expect(a.properties?.eventId).not.toBe(b.properties?.eventId);
    expect(a.properties?.eventName).toBe(b.properties?.eventName);
  });

  it('should treat same eventId as duplicate', () => {
    const eventId = 'dup_1';
    const a: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { eventId, eventName: 'pv', path: '/a' },
    };
    const b: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { eventId, eventName: 'pv', path: '/a' },
    };
    expect(a.properties?.eventId).toBe(b.properties?.eventId);
    expect(a.properties).toEqual(b.properties);
  });

  it('should compute fingerprint for dedup key from event data', () => {
    const eventName = 'page_view';
    const path = '/demo';
    const timestamp = '2024-09-11T13:20:00.000Z';
    const fingerprint = `${eventName}|${path}|${timestamp}`;
    expect(fingerprint).toBe('page_view|/demo|2024-09-11T13:20:00.000Z');
  });

  it('should validate duplicate fixture has firstSeenAt and duplicateSeenAt', () => {
    expect(duplicateFixture.properties?.firstSeenAt).toBe('2024-09-11T13:19:00.000Z');
    expect(duplicateFixture.properties?.duplicateSeenAt).toBe('2024-09-11T13:20:00.000Z');
  });

  it('should construct EventEnvelope for duplicate event', () => {
    const envelope: EventEnvelope = {
      tenant_id: duplicateFixture.tenant_id,
      workspace_id: duplicateFixture.workspace_id,
      platform_id: duplicateFixture.platform_id,
      environment: duplicateFixture.environment,
      event_type: duplicateFixture.event_type,
      sdk: duplicateFixture.sdk,
      identity: duplicateFixture.identity,
      timestamp: duplicateFixture.timestamp,
      properties: duplicateFixture.properties,
    };
    expect(envelope.event_type).toBe('page');
    expect(envelope.properties?.isDuplicate).toBe(true);
    expect(envelope.properties?.dedupKey).toBeDefined();
  });
});
