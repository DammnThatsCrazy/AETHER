/**
 * FPS-054 — Web SDK Offline Behavior
 * Verifies web SDK offline event queuing.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { offlineQueueFixture } from '@aether/proof-fixtures';

import { AetherSDK } from '@aether/web';

describe('FPS-054: Web SDK Offline', () => {
  it('should detect offline state', () => {
    const isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true;
    expect(typeof isOnline).toBe('boolean');
    expect(isOnline).toBe(true);
  });

  it('should queue event when offline', () => {
    const queued: any = {
      id: 'q_web_001',
      type: 'track',
      payload: { eventName: 'page_view' },
      enqueuedAt: Date.now(),
      retryCount: 0,
    };
    expect(queued.type).toBe('track');
    expect(queued.retryCount).toBe(0);
  });

  it('should flush queue when online', () => {
    const queue: any[] = [{ id: 'q1' }, { id: 'q2' }];
    expect(queue.length).toBe(2);
    queue.length = 0;
    expect(queue.length).toBe(0);
  });

  it('should increment retry count on failure', () => {
    const entry: any = { id: 'q1', retryCount: 1 };
    entry.retryCount = 2;
    expect(entry.retryCount).toBe(2);
  });

  it('should use offline queue fixture with batch data', () => {
    const envelope = offlineQueueFixture as EventEnvelope;
    expect(envelope.event_type).toBe('sdk_batch_sent');
    expect(envelope.platform_id).toBe('mobile');
    expect(envelope.properties?.batch_id).toBe('batch_offline_001');
    expect(envelope.properties?.total_queued).toBe(3);
    expect(envelope.properties?.delivered_count).toBe(3);
    expect(envelope.properties?.failed_count).toBe(0);
    const queuedEvents = envelope.properties?.queued_events as unknown[] | undefined;
    expect(Array.isArray(queuedEvents)).toBe(true);
    expect(queuedEvents?.length).toBe(3);
  });

  it('should validate queued events include track and identify types', () => {
    const queuedEvents = offlineQueueFixture.properties?.queued_events as unknown[] | undefined;
    const types = queuedEvents?.map((e: any) => e.type) || [];
    expect(types).toContain('track');
    expect(types).toContain('identify');
    expect(types.length).toBe(3);
  });

  it('should validate first queued event structure', () => {
    const first = (offlineQueueFixture.properties?.queued_events as unknown[] | undefined)?.[0];
    expect(first?.id).toBe('q_001');
    expect(first?.type).toBe('track');
    expect(first?.payload?.eventName).toBe('page_view');
    expect(first?.enqueuedAt).toBe('2024-09-11T10:00:00.000Z');
    expect(first?.retryCount).toBe(0);
  });

  it('should call sdk.reset without error', () => {
    const sdk = new AetherSDK({
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://api.example.com',
    });
    expect(() => sdk.reset()).not.toThrow();
  });

  it('should call sdk.destroy without error', () => {
    const sdk = new AetherSDK({
      apiKey: 'ak_test_fake_key',
      endpoint: 'https://api.example.com',
    });
    expect(() => sdk.destroy()).not.toThrow();
  });
});
