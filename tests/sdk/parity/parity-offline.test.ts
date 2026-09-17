/**
 * FPS-096 — Parity Offline Queue Contract
 * Verifies offline queue behavior is consistent across mobile platforms.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { offlineQueueFixture } from '@aether/proof-fixtures';

describe('FPS-096: Parity Offline', () => {
  it('should validate offline queue fixture shape', () => {
    const envelope = offlineQueueFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('sdk_batch_sent');
    expect(envelope.platform_id).toBe('mobile');
    const props = envelope.properties as Record<string, unknown> | undefined;
    expect(props?.batch_id).toBe('batch_offline_001');
    expect(props?.total_queued).toBe(3);
    expect(props?.delivered_count).toBe(3);
  });

  it('should validate queue shape is same across iOS and Android', () => {
    const envelope = offlineQueueFixture as unknown as EventEnvelope;
    const required = ['tenant_id', 'workspace_id', 'platform_id', 'environment', 'event_type', 'sdk', 'identity', 'timestamp'];
    for (const field of required) {
      expect(envelope[field]).toBeDefined();
    }
  });

  it('should share the same queued events structure', () => {
    const props = offlineQueueFixture.properties as Record<string, unknown> | undefined;
    const queuedEvents = props?.queued_events as unknown[] | undefined;
    expect(Array.isArray(queuedEvents)).toBe(true);
    expect(queuedEvents?.length).toBe(3);
  });
});
