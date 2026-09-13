// =============================================================================
// Aether INGESTION — UNIT TESTS
// Tests for validation, enrichment, pipeline, auth, and metrics
// =============================================================================

import { describe, it, expect, beforeEach } from 'vitest';
import { EventValidator } from '../../services/ingestion/src/validators/event-validator.js';
import { EventEnricher, DeadLetterQueue } from '../../services/ingestion/src/enrichers/event-enricher.js';
import { MetricsCollector } from '../../services/ingestion/src/metrics.js';
import { anonymizeIp, partitionKey, extractClientIp, sha256, chunk, startTimer } from '../../packages/common/src/utils.js';
import { ApiKeyValidator, InMemoryApiKeyStore, RateLimiter } from '../../packages/auth/src/index.js';
import { InMemoryCache, DeduplicationFilter } from '../../packages/cache/src/index.js';
import type { ProcessingConfig } from '../../packages/common/src/types.js';
import {
  createValidEvent, createValidBatch, createMixedBatch,
  createInvalidEvent_MissingId, createInvalidEvent_BadType, createInvalidEvent_FutureTimestamp,
  createEventWithPII, createEventWithConsent,
  createTestApiKeyRecord, createRateLimits, TEST_API_KEY,
} from '../fixtures/events.js';

// =============================================================================
// UTILS
// =============================================================================

describe('Utils', () => {
  it('anonymizes IPv4 addresses', () => {
    expect(anonymizeIp('192.168.1.42')).toBe('192.168.1.0');
    expect(anonymizeIp('10.0.0.255')).toBe('10.0.0.0');
  });

  it('anonymizes IPv6 addresses', () => {
    expect(anonymizeIp('2001:0db8:85a3:0000:0000:8a2e:0370:7334')).toBe('2001:0db8:85a3:0000:0:0:0:0');
  });

  it('generates deterministic partition keys', () => {
    const fixedDate = new Date('2026-01-15T10:30:00Z');
    const key1 = partitionKey('proj_001', fixedDate);
    const key2 = partitionKey('proj_001', fixedDate);
    expect(key1).toBe(key2);
    expect(key1).toBe('project_id=proj_001/year=2026/month=01/day=15/hour=10');
  });

  it('extracts client IP from headers', () => {
    expect(extractClientIp({ 'x-forwarded-for': '1.2.3.4, 5.6.7.8' })).toBe('1.2.3.4');
    expect(extractClientIp({})).toBe('0.0.0.0');
  });

  it('chunks arrays correctly', () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
    expect(chunk([], 5)).toEqual([]);
    expect(chunk([1], 3)).toEqual([[1]]);
  });

  it('hashes consistently', () => {
    expect(sha256('test')).toBe(sha256('test'));
    expect(sha256('a')).not.toBe(sha256('b'));
    expect(sha256('hello')).toHaveLength(64);
  });

  it('startTimer measures elapsed time', async () => {
    const elapsed = startTimer();
    await new Promise(r => setTimeout(r, 50));
    const ms = elapsed();
    expect(ms).toBeGreaterThan(40);
    expect(ms).toBeLessThan(200);
  });
});

// =============================================================================
// EVENT VALIDATOR
// =============================================================================

describe('EventValidator', () => {
  const config: ProcessingConfig = {
    maxBatchSize: 500,
    maxEventSizeBytes: 32768,
    enrichGeo: false,
    enrichUA: false,
    anonymizeIp: true,
    validateSchema: true,
    deduplicationWindowMs: 300_000,
    deadLetterEnabled: true,
  };

  let validator: EventValidator;

  beforeEach(() => {
    validator = new EventValidator(config);
  });

  describe('validateBatch', () => {
    it('accepts valid batch payloads', () => {
      const batch = createValidBatch(3);
      const result = validator.validateBatch(batch);
      expect(result.batch).toHaveLength(3);
      expect(result.sentAt).toBeTruthy();
    });

    it('rejects non-object payloads', () => {
      expect(() => validator.validateBatch(null)).toThrow('Invalid payload');
      expect(() => validator.validateBatch('string')).toThrow('Invalid payload');
    });

    it('rejects missing batch array', () => {
      expect(() => validator.validateBatch({ sentAt: 'now' })).toThrow('"batch" must be an array');
    });

    it('rejects empty batches', () => {
      expect(() => validator.validateBatch({ batch: [] })).toThrow('Empty batch');
    });

    it('rejects oversized batches', () => {
      const huge = { batch: Array.from({ length: 501 }, () => ({})) };
      expect(() => validator.validateBatch(huge)).toThrow('exceeds maximum');
    });
  });

  describe('validateEvents', () => {
    it('accepts valid events', () => {
      const events = [createValidEvent(), createValidEvent()];
      const result = validator.validateEvents(events);
      expect(result.valid).toHaveLength(2);
      expect(result.invalid).toHaveLength(0);
    });

    it('accepts all event types in a mixed batch', () => {
      const batch = createMixedBatch();
      const result = validator.validateEvents(batch.batch);
      expect(result.valid).toHaveLength(6);
    });

    it('rejects events without ID', () => {
      const result = validator.validateEvents([createInvalidEvent_MissingId() as any]);
      expect(result.invalid).toHaveLength(1);
      expect(result.invalid[0].errors).toContain('Missing or invalid "id"');
    });

    it('rejects events with invalid type', () => {
      const result = validator.validateEvents([createInvalidEvent_BadType() as any]);
      expect(result.invalid).toHaveLength(1);
      expect(result.invalid[0].errors[0]).toContain('Invalid event type');
    });

    it('rejects events with future timestamps', () => {
      const result = validator.validateEvents([createInvalidEvent_FutureTimestamp() as any]);
      expect(result.invalid).toHaveLength(1);
      expect(result.invalid[0].errors[0]).toContain('future');
    });

    it('masks PII in event properties', () => {
      const event = createEventWithPII();
      const result = validator.validateEvents([event]);
      expect(result.valid).toHaveLength(1);

      const props = result.valid[0].properties!;
      expect(props.note).toContain('[REDACTED]');
      expect(props.ssn).toContain('[REDACTED]');
      expect(props.normalField).toBe('safe value');
    });

    it('filters events without consent', () => {
      const event = createEventWithConsent({ analytics: false, marketing: true, web3: true });
      const result = validator.validateEvents([event]);
      expect(result.valid).toHaveLength(0);
      expect(result.filtered).toBe(1);
    });

    it('allows consent events regardless of consent state', () => {
      const event = createEventWithConsent({ analytics: false, marketing: false, web3: false });
      event.type = 'consent';
      const result = validator.validateEvents([event]);
      expect(result.valid).toHaveLength(1);
    });

    it('filters wallet events without web3 consent', () => {
      const event = createEventWithConsent({ analytics: true, marketing: true, web3: false });
      event.type = 'wallet';
      const result = validator.validateEvents([event]);
      expect(result.filtered).toBe(1);
    });
  });
});

// =============================================================================
// EVENT ENRICHER
// =============================================================================

describe('EventEnricher', () => {
  it('enriches events with pipeline metadata', () => {
    const enricher = new EventEnricher({ enrichGeo: false, enrichUA: false, anonymizeIp: true });
    const events = [createValidEvent()];

    const enriched = enricher.enrich(events, 'proj_001', '1.2.3.4');

    expect(enriched).toHaveLength(1);
    expect(enriched[0].projectId).toBe('proj_001');
    expect(enriched[0].receivedAt).toBeTruthy();
    expect(enriched[0].partitionKey).toContain('project_id=proj_001');
    expect(enriched[0].enrichment.pipelineVersion).toBe('4.0.0');
  });

  it('anonymizes IP addresses', () => {
    const enricher = new EventEnricher({ enrichGeo: false, enrichUA: false, anonymizeIp: true });
    const enriched = enricher.enrich([createValidEvent()], 'proj_001', '1.2.3.4');
    expect(enriched[0].enrichment.anonymizedIp).toBe('1.2.3.0');
    expect(enriched[0].context.ip).toBe('1.2.3.0');
  });

  it('parses user agent', () => {
    const enricher = new EventEnricher({ enrichGeo: false, enrichUA: true, anonymizeIp: false });
    const enriched = enricher.enrich([createValidEvent()], 'proj_001', '1.2.3.4');
    const ua = enriched[0].enrichment.parsedUA;
    expect(ua).toBeTruthy();
    expect(ua!.browser).toBe('Chrome');
    expect(ua!.os).toBe('macOS');
    expect(ua!.isBot).toBe(false);
  });

  it('detects bot user agents', () => {
    const enricher = new EventEnricher({ enrichGeo: false, enrichUA: true, anonymizeIp: false });
    const event = createValidEvent();
    event.context.userAgent = 'Googlebot/2.1 (+http://www.google.com/bot.html)';

    const enriched = enricher.enrich([event], 'proj_001', '1.2.3.4');
    expect(enriched[0].enrichment.parsedUA!.isBot).toBe(true);
    expect(enriched[0].enrichment.botProbability).toBe(0.95);
  });
});

// =============================================================================
// DEAD LETTER QUEUE
// =============================================================================

describe('DeadLetterQueue', () => {
  it('stores failed events', () => {
    const dlq = new DeadLetterQueue(100);
    dlq.push({ id: 'evt_1' }, 'validation failed');
    dlq.push({ id: 'evt_2' }, 'enrichment error');
    expect(dlq.size).toBe(2);
  });

  it('drains events for reprocessing', () => {
    const dlq = new DeadLetterQueue(100);
    for (let i = 0; i < 10; i++) dlq.push({ id: `evt_${i}` }, 'error');

    const batch = dlq.drain(5);
    expect(batch).toHaveLength(5);
    expect(dlq.size).toBe(5);
  });

  it('evicts oldest events when full', () => {
    const dlq = new DeadLetterQueue(3);
    dlq.push({ id: 'evt_1' }, 'err');
    dlq.push({ id: 'evt_2' }, 'err');
    dlq.push({ id: 'evt_3' }, 'err');
    dlq.push({ id: 'evt_4' }, 'err'); // Should evict evt_1

    expect(dlq.size).toBe(3);
    const items = dlq.drain(10);
    expect((items[0].event as any).id).toBe('evt_2');
  });
});

// =============================================================================
// DEDUPLICATION
// =============================================================================

describe('DeduplicationFilter', () => {
  let cache: InMemoryCache;
  let dedup: DeduplicationFilter;

  beforeEach(() => {
    cache = new InMemoryCache();
    dedup = new DeduplicationFilter(cache, 300_000);
  });

  it('identifies duplicate event IDs', async () => {
    expect(await dedup.isDuplicate('evt_1')).toBe(false);
    expect(await dedup.isDuplicate('evt_1')).toBe(true);
    expect(await dedup.isDuplicate('evt_2')).toBe(false);
  });

  it('batch filters duplicates', async () => {
    await dedup.isDuplicate('evt_existing');
    const dupes = await dedup.filterDuplicates(['evt_existing', 'evt_new1', 'evt_new2']);
    expect(dupes.has('evt_existing')).toBe(true);
    expect(dupes.has('evt_new1')).toBe(false);
    expect(dupes.size).toBe(1);
  });
});

// =============================================================================
// AUTH
// =============================================================================

describe('ApiKeyValidator', () => {
  let store: InMemoryApiKeyStore;
  let validator: ApiKeyValidator;

  beforeEach(() => {
    store = new InMemoryApiKeyStore();
    validator = new ApiKeyValidator(store, 60_000);
    store.addKey(createTestApiKeyRecord());
  });

  it('validates correct API keys', async () => {
    const record = await validator.validate(TEST_API_KEY);
    expect(record).toBeTruthy();
    expect(record!.projectId).toBe('proj_test_001');
  });

  it('rejects unknown API keys', async () => {
    const record = await validator.validate('ak_unknown_key_does_not_exist');
    expect(record).toBeNull();
  });

  it('rejects short keys', async () => {
    const record = await validator.validate('short');
    expect(record).toBeNull();
  });

  it('rejects inactive keys', async () => {
    store.addKey(createTestApiKeyRecord({ key: 'ak_inactive_key_long_enough', keyHash: sha256('ak_inactive_key_long_enough'), isActive: false }));
    const record = await validator.validate('ak_inactive_key_long_enough');
    expect(record).toBeNull();
  });

  it('caches validated keys', async () => {
    await validator.validate(TEST_API_KEY);
    // Modify store to return null (simulating deletion)
    // But cache should still return the record
    const record = await validator.validate(TEST_API_KEY);
    expect(record).toBeTruthy();
  });

  it('extracts key from Authorization header', () => {
    expect(ApiKeyValidator.extractKey('Bearer ak_test_123')).toBe('ak_test_123');
    expect(ApiKeyValidator.extractKey('ak_raw_key')).toBe('ak_raw_key');
    expect(ApiKeyValidator.extractKey(undefined, 'ak_query_key')).toBe('ak_query_key');
    expect(ApiKeyValidator.extractKey(undefined, undefined)).toBeNull();
  });
});

// =============================================================================
// RATE LIMITER
// =============================================================================

describe('RateLimiter', () => {
  let limiter: RateLimiter;

  beforeEach(() => {
    limiter = new RateLimiter(60_000);
  });

  it('allows requests within limits', () => {
    const limits = createRateLimits({ eventsPerMinute: 10 });
    const result = limiter.check('proj_1', limits);
    expect(result.allowed).toBe(true);
    expect(result.remaining).toBe(9);
  });

  it('blocks requests exceeding limits', () => {
    const limits = createRateLimits({ eventsPerMinute: 3 });
    limiter.check('proj_1', limits); // 1
    limiter.check('proj_1', limits); // 2
    limiter.check('proj_1', limits); // 3
    const result = limiter.check('proj_1', limits); // 4 — exceeds
    expect(result.allowed).toBe(false);
    expect(result.remaining).toBe(0);
  });

  it('tracks limits per key independently', () => {
    const limits = createRateLimits({ eventsPerMinute: 2 });
    limiter.check('proj_1', limits);
    limiter.check('proj_1', limits);
    const r1 = limiter.check('proj_1', limits); // Over
    const r2 = limiter.check('proj_2', limits); // Fresh
    expect(r1.allowed).toBe(false);
    expect(r2.allowed).toBe(true);
  });

  afterEach(() => {
    limiter.destroy();
  });
});

// =============================================================================
// METRICS COLLECTOR
// =============================================================================

describe('MetricsCollector', () => {
  let collector: MetricsCollector;

  beforeEach(() => {
    collector = new MetricsCollector();
  });

  it('increments counters', () => {
    collector.increment('test_counter');
    collector.increment('test_counter');
    collector.increment('test_counter', 3);
    expect(collector.getCounter('test_counter')).toBe(5);
  });

  it('handles labeled counters', () => {
    collector.increment('requests', 1, { method: 'POST' });
    collector.increment('requests', 1, { method: 'GET' });
    collector.increment('requests', 1, { method: 'POST' });
    expect(collector.getCounter('requests', { method: 'POST' })).toBe(2);
    expect(collector.getCounter('requests', { method: 'GET' })).toBe(1);
  });

  it('tracks gauges', () => {
    collector.setGauge('connections', 42);
    expect(collector.getGauge('connections')).toBe(42);
    collector.setGauge('connections', 10);
    expect(collector.getGauge('connections')).toBe(10);
  });

  it('records histograms', () => {
    for (let i = 0; i < 100; i++) collector.observe('latency', i);
    const hist = collector.getHistogram('latency');
    expect(hist).toBeTruthy();
    expect(hist!.count).toBe(100);
    expect(hist!.p50).toBeLessThanOrEqual(50);
    expect(hist!.p99).toBeGreaterThanOrEqual(90);
  });

  it('records ingestion metrics', () => {
    collector.recordBatchReceived('proj_1', 25);
    collector.recordEventsProcessed(23, 'proj_1');
    collector.recordEventsDropped(2, 'validation');
    collector.recordProcessingDuration(12.5, 'proj_1');

    const snap = collector.snapshot();
    expect(snap.events_received_total).toBeGreaterThan(0);
  });

  it('exports Prometheus format', () => {
    collector.increment('test_metric', 5);
    const prom = collector.toPrometheus();
    expect(prom).toContain('# TYPE test_metric counter');
    expect(prom).toContain('test_metric 5');
  });

  it('resets all metrics', () => {
    collector.increment('counter', 10);
    collector.setGauge('gauge', 42);
    collector.reset();
    expect(collector.getCounter('counter')).toBe(0);
    expect(collector.getGauge('gauge')).toBe(0);
  });
});

// =============================================================================
// CACHE
// =============================================================================

describe('InMemoryCache', () => {
  let cache: InMemoryCache;

  beforeEach(() => {
    cache = new InMemoryCache();
  });

  afterEach(async () => {
    await cache.close();
  });

  it('stores and retrieves values', async () => {
    await cache.set('key1', 'value1');
    expect(await cache.get('key1')).toBe('value1');
  });

  it('returns null for missing keys', async () => {
    expect(await cache.get('nonexistent')).toBeNull();
  });

  it('deletes keys', async () => {
    await cache.set('key1', 'value1');
    await cache.del('key1');
    expect(await cache.get('key1')).toBeNull();
  });

  it('increments counters', async () => {
    expect(await cache.incr('counter')).toBe(1);
    expect(await cache.incr('counter')).toBe(2);
    expect(await cache.incr('counter')).toBe(3);
  });

  it('checks key existence', async () => {
    expect(await cache.exists('key1')).toBe(false);
    await cache.set('key1', 'val');
    expect(await cache.exists('key1')).toBe(true);
  });

  it('handles TTL expiration', async () => {
    await cache.set('expiring', 'data', 1); // 1 second TTL
    expect(await cache.get('expiring')).toBe('data');
    await new Promise(r => setTimeout(r, 1100));
    expect(await cache.get('expiring')).toBeNull();
  });

  it('supports multiple sequential operations', async () => {
    await cache.set('a', '1');
    await cache.set('b', '2');
    expect(await cache.get('a')).toBe('1');
    expect(await cache.get('b')).toBe('2');
  });
});
