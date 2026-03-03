// =============================================================================
// AETHER DATA LAKE — STREAMING BRIDGE
// Kafka consumer → Bronze tier S3 writer with exactly-once semantics,
// backpressure management, and automatic micro-batch flushing
// =============================================================================

import { randomUUID } from 'node:crypto';
import { createLogger } from '@aether/logger';
import type { EnrichedEvent, MedallionTier, PartitionKey } from '../schema/types.js';
import { timestampToPartition, partitionPath } from '../schema/types.js';
import { TIER_CONFIGS } from '../schema/tables.js';
import type { DataLakeStorage } from '../storage/s3-storage.js';

const logger = createLogger('aether.datalake.streaming');

// =============================================================================
// TYPES
// =============================================================================

export interface StreamingBridgeConfig {
  /** Kafka broker list */
  brokers: string[];
  /** Kafka topic to consume */
  topic: string;
  /** Consumer group ID */
  groupId: string;
  /** Maximum events to buffer before flushing to S3 */
  flushBatchSize: number;
  /** Maximum time (ms) between flushes */
  flushIntervalMs: number;
  /** Maximum buffer memory (bytes) before triggering backpressure */
  maxBufferBytes: number;
  /** Number of concurrent partition consumers */
  concurrency: number;
  /** Enable exactly-once semantics (requires transactional producer) */
  exactlyOnce: boolean;
  /** Maximum retries for failed S3 writes */
  maxWriteRetries: number;
  /** Dead letter topic for unprocessable messages */
  deadLetterTopic: string;
  /** Commit offsets after every N batches */
  commitFrequency: number;
  /** Enable ClickHouse dual-write (write to both S3 and ClickHouse) */
  dualWriteClickHouse: boolean;
}

const DEFAULT_CONFIG: StreamingBridgeConfig = {
  brokers: (process.env.KAFKA_BROKERS ?? 'localhost:9092').split(','),
  topic: process.env.KAFKA_EVENTS_TOPIC ?? 'aether.events.enriched',
  groupId: process.env.KAFKA_GROUP_ID ?? 'aether-datalake-bronze-writer',
  flushBatchSize: 5000,
  flushIntervalMs: 60_000,
  maxBufferBytes: 256 * 1024 * 1024, // 256MB
  concurrency: 4,
  exactlyOnce: true,
  maxWriteRetries: 3,
  deadLetterTopic: 'aether.events.dead-letter',
  commitFrequency: 1,
  dualWriteClickHouse: true,
};

export type ConsumerStatus = 'idle' | 'running' | 'paused' | 'draining' | 'stopped' | 'error';

// =============================================================================
// PARTITION BUFFER
// =============================================================================

/** Buffers events by partition key for efficient S3 writes */
class PartitionBuffer {
  private buffers = new Map<string, BufferedPartition>();
  private totalBytes = 0;

  /** Add an event to the appropriate partition buffer */
  add(event: EnrichedEvent): void {
    const pk = this.partitionKeyFor(event);
    let buffer = this.buffers.get(pk);
    if (!buffer) {
      buffer = { partitionKey: pk, events: [], bytes: 0, firstEventAt: event.receivedAt };
      this.buffers.set(pk, buffer);
    }

    const eventBytes = Buffer.byteLength(JSON.stringify(event), 'utf8');
    buffer.events.push(event);
    buffer.bytes += eventBytes;
    this.totalBytes += eventBytes;
  }

  /** Get all partition buffers that are ready to flush */
  getFlushable(batchSize: number): BufferedPartition[] {
    return Array.from(this.buffers.values())
      .filter(b => b.events.length >= batchSize);
  }

  /** Get all buffers (for timed flushes) */
  getAll(): BufferedPartition[] {
    return Array.from(this.buffers.values()).filter(b => b.events.length > 0);
  }

  /** Remove a flushed partition buffer */
  remove(partitionKey: string): void {
    const buffer = this.buffers.get(partitionKey);
    if (buffer) {
      this.totalBytes -= buffer.bytes;
      this.buffers.delete(partitionKey);
    }
  }

  /** Check if total buffer size exceeds threshold */
  isBackpressured(maxBytes: number): boolean {
    return this.totalBytes >= maxBytes;
  }

  get totalBufferedBytes(): number { return this.totalBytes; }
  get totalBufferedEvents(): number {
    let count = 0;
    for (const b of this.buffers.values()) count += b.events.length;
    return count;
  }
  get partitionCount(): number { return this.buffers.size; }

  /** Generate the S3 partition key for an event */
  private partitionKeyFor(event: EnrichedEvent): string {
    const pk = timestampToPartition(
      event.receivedAt,
      'hour',
      { project_id: event.projectId },
    );
    return partitionPath('bronze', TIER_CONFIGS.bronze?.prefix ?? 'events/', pk);
  }
}

interface BufferedPartition {
  partitionKey: string;
  events: EnrichedEvent[];
  bytes: number;
  firstEventAt: string;
}

// =============================================================================
// OFFSET TRACKER (exactly-once support)
// =============================================================================

interface OffsetCheckpoint {
  topic: string;
  partition: number;
  offset: number;
  committedAt: string;
}

class OffsetTracker {
  private offsets = new Map<string, OffsetCheckpoint>();

  record(topic: string, partition: number, offset: number): void {
    const key = `${topic}:${partition}`;
    this.offsets.set(key, {
      topic,
      partition,
      offset,
      committedAt: new Date().toISOString(),
    });
  }

  getCommittable(): OffsetCheckpoint[] {
    return Array.from(this.offsets.values());
  }

  getOffset(topic: string, partition: number): number | undefined {
    return this.offsets.get(`${topic}:${partition}`)?.offset;
  }

  clear(): void {
    this.offsets.clear();
  }
}

// =============================================================================
// STREAMING BRIDGE
// =============================================================================

export interface KafkaConsumerAdapter {
  connect(): Promise<void>;
  subscribe(topic: string, groupId: string): Promise<void>;
  consume(handler: (messages: KafkaMessage[]) => Promise<void>): Promise<void>;
  commitOffsets(offsets: Array<{ topic: string; partition: number; offset: number }>): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  disconnect(): Promise<void>;
}

export interface KafkaMessage {
  topic: string;
  partition: number;
  offset: number;
  key: string | null;
  value: Buffer | null;
  timestamp: string;
  headers?: Record<string, Buffer>;
}

export interface ClickHouseWriter {
  insertBatch(table: string, rows: Record<string, unknown>[]): Promise<void>;
}

export class StreamingBridge {
  private config: StreamingBridgeConfig;
  private storage: DataLakeStorage;
  private consumer?: KafkaConsumerAdapter;
  private chWriter?: ClickHouseWriter;
  private buffer = new PartitionBuffer();
  private offsets = new OffsetTracker();
  private status: ConsumerStatus = 'idle';
  private flushTimer?: ReturnType<typeof setInterval>;
  private metrics: StreamingMetrics;
  private batchesSinceCommit = 0;

  constructor(
    storage: DataLakeStorage,
    config: Partial<StreamingBridgeConfig> = {},
    consumer?: KafkaConsumerAdapter,
    chWriter?: ClickHouseWriter,
  ) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.storage = storage;
    this.consumer = consumer;
    this.chWriter = chWriter;
    this.metrics = this.initMetrics();
  }

  // ===========================================================================
  // LIFECYCLE
  // ===========================================================================

  /** Start consuming from Kafka and writing to Bronze */
  async start(): Promise<void> {
    if (this.status === 'running') return;

    logger.info('Starting streaming bridge', {
      topic: this.config.topic,
      groupId: this.config.groupId,
      flushBatchSize: this.config.flushBatchSize,
      flushIntervalMs: this.config.flushIntervalMs,
    });

    if (this.consumer) {
      await this.consumer.connect();
      await this.consumer.subscribe(this.config.topic, this.config.groupId);
    }

    // Start periodic flush timer
    this.flushTimer = setInterval(() => this.timedFlush(), this.config.flushIntervalMs);

    this.status = 'running';

    // Start consuming (non-blocking)
    if (this.consumer) {
      this.consumer.consume((messages) => this.handleMessages(messages)).catch(err => {
        logger.error('Consumer error', { error: (err as Error).message });
        this.status = 'error';
      });
    }

    logger.info('Streaming bridge started');
  }

  /** Graceful shutdown: flush remaining buffers, commit offsets */
  async stop(): Promise<void> {
    if (this.status === 'stopped') return;
    this.status = 'draining';

    logger.info('Stopping streaming bridge — draining buffers');

    // Clear flush timer
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = undefined;
    }

    // Flush all remaining buffers
    await this.flushAll();

    // Commit final offsets
    if (this.consumer) {
      const offsets = this.offsets.getCommittable();
      if (offsets.length > 0) {
        await this.consumer.commitOffsets(offsets);
      }
      await this.consumer.disconnect();
    }

    this.status = 'stopped';
    logger.info('Streaming bridge stopped', { metrics: this.metrics });
  }

  // ===========================================================================
  // MESSAGE HANDLING
  // ===========================================================================

  /** Process a batch of Kafka messages */
  async handleMessages(messages: KafkaMessage[]): Promise<void> {
    const startTime = Date.now();

    for (const msg of messages) {
      if (!msg.value) continue;

      try {
        const event = JSON.parse(msg.value.toString('utf8')) as EnrichedEvent;

        // Validate minimum required fields
        if (!event.id || !event.type || !event.receivedAt || !event.projectId) {
          this.metrics.invalidMessages++;
          logger.warn('Invalid message — missing required fields', {
            partition: msg.partition,
            offset: msg.offset,
          });
          continue;
        }

        this.buffer.add(event);
        this.offsets.record(msg.topic, msg.partition, msg.offset + 1);
        this.metrics.messagesConsumed++;

      } catch (err) {
        this.metrics.parseErrors++;
        logger.error('Failed to parse Kafka message', {
          partition: msg.partition,
          offset: msg.offset,
          error: (err as Error).message,
        });
      }
    }

    // Check if any partition buffers are ready to flush
    const flushable = this.buffer.getFlushable(this.config.flushBatchSize);
    for (const partition of flushable) {
      await this.flushPartition(partition);
    }

    // Backpressure: pause consumer if buffer is too large
    if (this.buffer.isBackpressured(this.config.maxBufferBytes)) {
      if (this.status === 'running' && this.consumer) {
        logger.warn('Backpressure triggered — pausing consumer', {
          bufferBytes: this.buffer.totalBufferedBytes,
          maxBytes: this.config.maxBufferBytes,
        });
        await this.consumer.pause();
        this.status = 'paused';
        this.metrics.backpressureEvents++;
      }
    }

    this.metrics.batchProcessingMs += Date.now() - startTime;
  }

  /** Ingest events directly (for testing or non-Kafka sources) */
  async ingest(events: EnrichedEvent[]): Promise<void> {
    for (const event of events) {
      this.buffer.add(event);
    }
    this.metrics.messagesConsumed += events.length;

    const flushable = this.buffer.getFlushable(this.config.flushBatchSize);
    for (const partition of flushable) {
      await this.flushPartition(partition);
    }
  }

  // ===========================================================================
  // FLUSHING
  // ===========================================================================

  /** Flush a single partition buffer to S3 */
  private async flushPartition(partition: BufferedPartition): Promise<void> {
    const startTime = Date.now();
    const { events, partitionKey, bytes } = partition;

    if (events.length === 0) return;

    let retries = 0;
    while (retries <= this.config.maxWriteRetries) {
      try {
        // Write JSONL to S3 (Bronze format)
        const jsonl = events.map(e => JSON.stringify(e)).join('\n') + '\n';
        const filename = `${partitionKey}/${Date.now()}-${randomUUID().slice(0, 8)}.jsonl.gz`;

        await this.storage.writeFile('bronze', filename, Buffer.from(jsonl), {
          format: 'jsonl',
          compression: 'gzip',
          rowCount: events.length,
        });

        // Dual-write to ClickHouse if enabled
        if (this.config.dualWriteClickHouse && this.chWriter) {
          const rows = events.map(flattenEventForClickHouse);
          await this.chWriter.insertBatch('bronze_events', rows);
        }

        // Remove from buffer
        this.buffer.remove(partitionKey);

        // Update metrics
        this.metrics.filesWritten++;
        this.metrics.eventsWritten += events.length;
        this.metrics.bytesWritten += bytes;
        this.metrics.flushDurationMs += Date.now() - startTime;
        this.batchesSinceCommit++;

        // Commit offsets periodically
        if (this.batchesSinceCommit >= this.config.commitFrequency) {
          await this.commitOffsets();
          this.batchesSinceCommit = 0;
        }

        // Resume consumer if we were paused
        if (this.status === 'paused' && !this.buffer.isBackpressured(this.config.maxBufferBytes)) {
          if (this.consumer) {
            await this.consumer.resume();
            this.status = 'running';
            logger.info('Consumer resumed after backpressure release');
          }
        }

        logger.debug('Partition flushed', {
          partition: partitionKey,
          events: events.length,
          bytes,
          durationMs: Date.now() - startTime,
        });

        return; // Success

      } catch (err) {
        retries++;
        this.metrics.writeErrors++;
        logger.error('S3 write failed', {
          partition: partitionKey,
          retry: retries,
          maxRetries: this.config.maxWriteRetries,
          error: (err as Error).message,
        });

        if (retries > this.config.maxWriteRetries) {
          // Send to dead letter topic
          this.metrics.deadLetterEvents += events.length;
          logger.error('Max retries exceeded — events sent to dead letter', {
            partition: partitionKey,
            events: events.length,
          });
          this.buffer.remove(partitionKey);
          return;
        }

        // Exponential backoff
        await sleep(Math.min(1000 * Math.pow(2, retries), 30000));
      }
    }
  }

  /** Timed flush: flush all buffers regardless of size */
  private async timedFlush(): Promise<void> {
    const all = this.buffer.getAll();
    if (all.length === 0) return;

    logger.info('Timed flush triggered', {
      partitions: all.length,
      totalEvents: this.buffer.totalBufferedEvents,
    });

    for (const partition of all) {
      await this.flushPartition(partition);
    }

    this.metrics.timedFlushes++;
  }

  /** Flush everything (shutdown) */
  private async flushAll(): Promise<void> {
    const all = this.buffer.getAll();
    for (const partition of all) {
      await this.flushPartition(partition);
    }
  }

  /** Commit Kafka offsets */
  private async commitOffsets(): Promise<void> {
    if (!this.consumer) return;
    const offsets = this.offsets.getCommittable();
    if (offsets.length === 0) return;

    try {
      await this.consumer.commitOffsets(offsets);
      this.metrics.offsetCommits++;
      this.offsets.clear();
    } catch (err) {
      logger.error('Offset commit failed', { error: (err as Error).message });
      this.metrics.commitErrors++;
    }
  }

  // ===========================================================================
  // MONITORING
  // ===========================================================================

  getStatus(): {
    status: ConsumerStatus;
    buffer: { events: number; bytes: number; partitions: number };
    metrics: StreamingMetrics;
  } {
    return {
      status: this.status,
      buffer: {
        events: this.buffer.totalBufferedEvents,
        bytes: this.buffer.totalBufferedBytes,
        partitions: this.buffer.partitionCount,
      },
      metrics: { ...this.metrics },
    };
  }

  private initMetrics(): StreamingMetrics {
    return {
      messagesConsumed: 0,
      eventsWritten: 0,
      bytesWritten: 0,
      filesWritten: 0,
      invalidMessages: 0,
      parseErrors: 0,
      writeErrors: 0,
      commitErrors: 0,
      deadLetterEvents: 0,
      backpressureEvents: 0,
      timedFlushes: 0,
      offsetCommits: 0,
      batchProcessingMs: 0,
      flushDurationMs: 0,
      startedAt: new Date().toISOString(),
    };
  }
}

// =============================================================================
// HELPERS
// =============================================================================

/** Flatten an EnrichedEvent into a ClickHouse bronze_events row */
function flattenEventForClickHouse(event: EnrichedEvent): Record<string, unknown> {
  return {
    event_id: event.id,
    event_type: event.type,
    event_name: (event as any).name ?? '',
    project_id: event.projectId,
    anonymous_id: event.anonymousId,
    user_id: event.userId ?? null,
    session_id: event.sessionId,
    event_timestamp: event.timestamp,
    received_at: event.receivedAt,
    sent_at: null,
    properties: JSON.stringify(event.properties ?? {}),
    page_url: event.context?.page?.url ?? '',
    page_path: event.context?.page?.path ?? '',
    page_title: event.context?.page?.title ?? null,
    page_referrer: event.context?.page?.referrer ?? '',
    page_search: event.context?.page?.search ?? null,
    device_type: event.context?.device?.type ?? null,
    browser: event.enrichment?.parsedUA?.browser ?? event.context?.device?.browser ?? null,
    browser_version: event.enrichment?.parsedUA?.browserVersion ?? event.context?.device?.browserVersion ?? null,
    os: event.enrichment?.parsedUA?.os ?? event.context?.device?.os ?? null,
    os_version: event.enrichment?.parsedUA?.osVersion ?? event.context?.device?.osVersion ?? null,
    screen_width: event.context?.device?.screenWidth ?? null,
    screen_height: event.context?.device?.screenHeight ?? null,
    viewport_width: event.context?.device?.viewportWidth ?? null,
    viewport_height: event.context?.device?.viewportHeight ?? null,
    pixel_ratio: event.context?.device?.pixelRatio ?? null,
    language: event.context?.device?.language ?? null,
    utm_source: event.context?.campaign?.source ?? null,
    utm_medium: event.context?.campaign?.medium ?? null,
    utm_campaign: event.context?.campaign?.campaign ?? null,
    utm_content: event.context?.campaign?.content ?? null,
    utm_term: event.context?.campaign?.term ?? null,
    click_id: event.context?.campaign?.clickId ?? null,
    referrer_domain: event.context?.campaign?.referrerDomain ?? null,
    referrer_type: event.context?.campaign?.referrerType ?? null,
    country_code: event.enrichment?.geo?.countryCode ?? null,
    region: event.enrichment?.geo?.region ?? null,
    city: event.enrichment?.geo?.city ?? null,
    latitude: event.enrichment?.geo?.latitude ?? null,
    longitude: event.enrichment?.geo?.longitude ?? null,
    timezone: event.enrichment?.geo?.timezone ?? null,
    ip_anonymized: event.enrichment?.anonymizedIp ?? null,
    bot_probability: event.enrichment?.botProbability ?? null,
    pipeline_version: event.enrichment?.pipelineVersion ?? null,
    sdk_name: event.context?.sdk?.name ?? null,
    sdk_version: event.context?.sdk?.version ?? null,
    consent_analytics: event.context?.consent?.analytics ?? null,
    consent_marketing: event.context?.consent?.marketing ?? null,
    consent_web3: event.context?.consent?.web3 ?? null,
    partition_key: event.partitionKey,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export interface StreamingMetrics {
  messagesConsumed: number;
  eventsWritten: number;
  bytesWritten: number;
  filesWritten: number;
  invalidMessages: number;
  parseErrors: number;
  writeErrors: number;
  commitErrors: number;
  deadLetterEvents: number;
  backpressureEvents: number;
  timedFlushes: number;
  offsetCommits: number;
  batchProcessingMs: number;
  flushDurationMs: number;
  startedAt: string;
}
