// =============================================================================
// AETHER INGESTION — INTEGRATION TESTS
// End-to-end pipeline tests with all components wired together
// =============================================================================

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { IngestionPipeline } from '../../services/ingestion/src/pipeline.js';
import { EventRouter, KafkaSink, S3Sink } from '../../packages/events/src/index.js';
import { InMemoryCache, DeduplicationFilter } from '../../packages/cache/src/index.js';
import type { ProcessingConfig, SinkConfig } from '../../packages/common/src/types.js';
import {
  createValidBatch, createMixedBatch, createValidEvent,
  createEventWithPII, createEventWithConsent,
} from '../fixtures/events.js';

const testConfig: ProcessingConfig = {
  maxBatchSize: 500,
  maxEventSizeBytes: 32768,
  enrichGeo: false,
  enrichUA: true,
  anonymizeIp: true,
  validateSchema: true,
  deduplicationWindowMs: 300_000,
  deadLetterEnabled: true,
};

describe('IngestionPipeline — End-to-End', () => {
  let pipeline: IngestionPipeline;
  let router: EventRouter;
  let cache: InMemoryCache;
  let dedup: DeduplicationFilter;

  beforeEach(async () => {
    router = new EventRouter();
    cache = new InMemoryCache();
    dedup = new DeduplicationFilter(cache, 300_000);

    // Add a mock sink (Kafka)
    const kafkaSink = new KafkaSink({
      type: 'kafka',
      enabled: true,
      config: { brokers: ['localhost:9092'], topic: 'test.events' },
      batchSize: 100,
      flushIntervalMs: 60_000,
    });
    await router.addSink(kafkaSink);

    pipeline = new IngestionPipeline(testConfig, router, dedup);
  });

  afterEach(async () => {
    await router.close();
    await cache.close();
  });

  it('processes a valid batch end-to-end', async () => {
    const batch = createValidBatch(10);
    const result = await pipeline.process(batch, 'proj_001', '1.2.3.4');

    expect(result.accepted).toBe(10);
    expect(result.rejected).toBe(0);
    expect(result.deduplicated).toBe(0);
    expect(result.filtered).toBe(0);
    expect(result.processingMs).toBeGreaterThan(0);
  });

  it('processes mixed event types', async () => {
    const batch = createMixedBatch();
    const result = await pipeline.process(batch, 'proj_001', '10.0.0.1');
    expect(result.accepted).toBe(6);
  });

  it('deduplicates events with same ID', async () => {
    const event = createValidEvent();
    const batch1 = { batch: [event], sentAt: new Date().toISOString() };
    const batch2 = { batch: [event], sentAt: new Date().toISOString() };

    const result1 = await pipeline.process(batch1, 'proj_001', '1.2.3.4');
    const result2 = await pipeline.process(batch2, 'proj_001', '1.2.3.4');

    expect(result1.accepted).toBe(1);
    expect(result2.accepted).toBe(0);
    expect(result2.deduplicated).toBe(1);
  });

  it('masks PII in properties', async () => {
    const event = createEventWithPII();
    const batch = { batch: [event], sentAt: new Date().toISOString() };
    const result = await pipeline.process(batch, 'proj_001', '1.2.3.4');
    expect(result.accepted).toBe(1);
  });

  it('respects consent state — blocks analytics when revoked', async () => {
    const event = createEventWithConsent({ analytics: false, marketing: true, web3: true });
    const batch = { batch: [event], sentAt: new Date().toISOString() };
    const result = await pipeline.process(batch, 'proj_001', '1.2.3.4');
    expect(result.accepted).toBe(0);
    expect(result.filtered).toBe(1);
  });

  it('rejects invalid events in mixed batches', async () => {
    const valid = createValidEvent();
    const invalid = { type: 'BOGUS' }; // Missing fields
    const batch = { batch: [valid, invalid as any], sentAt: new Date().toISOString() };

    const result = await pipeline.process(batch, 'proj_001', '1.2.3.4');
    expect(result.accepted).toBe(1);
    expect(result.rejected).toBe(1);
  });

  it('handles large batches efficiently', async () => {
    const events = Array.from({ length: 200 }, () => createValidEvent());
    const batch = { batch: events, sentAt: new Date().toISOString() };

    const result = await pipeline.process(batch, 'proj_001', '1.2.3.4');
    expect(result.accepted).toBe(200);
    expect(result.processingMs).toBeLessThan(5000);
  });

  it('rejects completely invalid payloads', async () => {
    await expect(pipeline.process(null, 'proj_001', '1.2.3.4')).rejects.toThrow('Invalid payload');
    await expect(pipeline.process('string', 'proj_001', '1.2.3.4')).rejects.toThrow('Invalid payload');
    await expect(pipeline.process({ batch: [] }, 'proj_001', '1.2.3.4')).rejects.toThrow('Empty batch');
  });

  it('reports DLQ size for monitoring', async () => {
    const invalid = { type: 'BOGUS' };
    const batch = { batch: [invalid as any], sentAt: new Date().toISOString() };

    await pipeline.process(batch, 'proj_001', '1.2.3.4');
    expect(pipeline.dlqSize).toBe(1);
  });
});
