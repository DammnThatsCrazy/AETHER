// =============================================================================
// AETHER BACKEND — EVENT BUS & SINK ROUTER
// Fan-out enriched events to multiple downstream sinks concurrently
// =============================================================================

import { createLogger } from '@aether/logger';
import type { EnrichedEvent, SinkConfig } from '@aether/common';
import { chunk, backoffDelay, sleep } from '@aether/common';

const logger = createLogger('aether.events');

// =============================================================================
// SINK INTERFACE
// =============================================================================

export interface EventSink {
  readonly name: string;
  readonly type: string;
  initialize(): Promise<void>;
  write(events: EnrichedEvent[]): Promise<void>;
  flush(): Promise<void>;
  healthCheck(): Promise<{ healthy: boolean; latencyMs: number }>;
  close(): Promise<void>;
}

// =============================================================================
// BUFFERED SINK — accumulates events and flushes in batches
// =============================================================================

export abstract class BufferedSink implements EventSink {
  abstract readonly name: string;
  abstract readonly type: string;

  protected buffer: EnrichedEvent[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private isFlushing = false;
  private isClosing = false;

  constructor(
    protected batchSize: number = 100,
    protected flushIntervalMs: number = 5000,
    protected maxRetries: number = 3,
  ) {}

  async initialize(): Promise<void> {
    this.flushTimer = setInterval(() => this.flush(), this.flushIntervalMs);
    logger.info(`Sink ${this.name} initialized`, { batchSize: this.batchSize, flushIntervalMs: this.flushIntervalMs });
  }

  async write(events: EnrichedEvent[]): Promise<void> {
    this.buffer.push(...events);

    if (this.buffer.length >= this.batchSize) {
      await this.flush();
    }
  }

  async flush(): Promise<void> {
    if (this.isFlushing || this.buffer.length === 0) return;
    this.isFlushing = true;

    const batch = this.buffer.splice(0, this.batchSize);

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        await this.writeBatch(batch);
        this.isFlushing = false;
        return;
      } catch (error) {
        if (attempt === this.maxRetries) {
          logger.error(`Sink ${this.name} failed after ${this.maxRetries} retries`, error as Error, {
            droppedEvents: batch.length,
          });
          await this.onFailure(batch, error as Error);
          this.isFlushing = false;
          return;
        }
        const delay = backoffDelay(attempt);
        logger.warn(`Sink ${this.name} retry ${attempt + 1}/${this.maxRetries}`, { delayMs: delay });
        await sleep(delay);
      }
    }

    this.isFlushing = false;
  }

  async close(): Promise<void> {
    this.isClosing = true;
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    if (this.buffer.length > 0) {
      await this.flush();
    }
    logger.info(`Sink ${this.name} closed`);
  }

  /** Subclasses implement the actual write */
  protected abstract writeBatch(events: EnrichedEvent[]): Promise<void>;

  /** Called when all retries are exhausted */
  protected async onFailure(events: EnrichedEvent[], error: Error): Promise<void> {
    // Default: log and drop. Override for DLQ behavior.
  }

  abstract healthCheck(): Promise<{ healthy: boolean; latencyMs: number }>;
}

// =============================================================================
// KAFKA SINK
// =============================================================================

export class KafkaSink extends BufferedSink {
  readonly name = 'kafka';
  readonly type = 'kafka';
  private topic: string;
  private brokers: string[];

  constructor(config: SinkConfig) {
    super(config.batchSize ?? 100, config.flushIntervalMs ?? 1000, config.retryAttempts ?? 3);
    const c = config.config as Record<string, any>;
    this.brokers = c.brokers ?? ['localhost:9092'];
    this.topic = c.topic ?? 'aether.events.raw';
  }

  async initialize(): Promise<void> {
    await super.initialize();
    logger.info('Kafka sink ready', { brokers: this.brokers, topic: this.topic });
  }

  protected async writeBatch(events: EnrichedEvent[]): Promise<void> {
    // Production: use kafkajs Producer.send()
    // For now: structured log output (enables Fluentd/Vector ingestion)
    const messages = events.map(e => ({
      key: e.partitionKey,
      value: JSON.stringify(e),
      headers: {
        'event-type': e.type,
        'project-id': e.projectId,
        'received-at': e.receivedAt,
      },
    }));

    logger.debug(`Kafka: writing ${messages.length} messages to ${this.topic}`);
    // await producer.send({ topic: this.topic, messages });
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    // Production: await admin.describeCluster()
    return { healthy: true, latencyMs: Date.now() - start };
  }
}

// =============================================================================
// S3 SINK (JSONL with hourly partitioning)
// =============================================================================

export class S3Sink extends BufferedSink {
  readonly name = 's3';
  readonly type = 's3';
  private bucket: string;
  private prefix: string;

  constructor(config: SinkConfig) {
    super(config.batchSize ?? 5000, config.flushIntervalMs ?? 60000, config.retryAttempts ?? 3);
    const c = config.config as Record<string, any>;
    this.bucket = c.bucket ?? 'aether-events-raw';
    this.prefix = c.prefix ?? 'events/';
  }

  protected async writeBatch(events: EnrichedEvent[]): Promise<void> {
    const now = new Date();
    const partition = [
      now.getUTCFullYear(),
      String(now.getUTCMonth() + 1).padStart(2, '0'),
      String(now.getUTCDate()).padStart(2, '0'),
      String(now.getUTCHours()).padStart(2, '0'),
    ].join('/');

    const key = `${this.prefix}${partition}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.jsonl.gz`;
    const body = events.map(e => JSON.stringify(e)).join('\n');

    logger.debug(`S3: writing ${events.length} events to s3://${this.bucket}/${key}`);
    // Production: await s3Client.putObject({ Bucket, Key, Body: gzip(body), ContentEncoding: 'gzip' })
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    return { healthy: true, latencyMs: Date.now() - start };
  }
}

// =============================================================================
// CLICKHOUSE SINK
// =============================================================================

export class ClickHouseSink extends BufferedSink {
  readonly name = 'clickhouse';
  readonly type = 'clickhouse';
  private host: string;
  private database: string;
  private table: string;

  constructor(config: SinkConfig) {
    super(config.batchSize ?? 1000, config.flushIntervalMs ?? 5000, config.retryAttempts ?? 3);
    const c = config.config as Record<string, any>;
    this.host = c.host ?? 'localhost';
    this.database = c.database ?? 'aether';
    this.table = c.table ?? 'events';
  }

  protected async writeBatch(events: EnrichedEvent[]): Promise<void> {
    const rows = events.map(e => ({
      id: e.id,
      type: e.type,
      event_name: e.event ?? e.properties?.event ?? '',
      project_id: e.projectId,
      anonymous_id: e.anonymousId,
      user_id: e.userId ?? '',
      session_id: e.sessionId,
      timestamp: e.timestamp,
      received_at: e.receivedAt,
      properties: JSON.stringify(e.properties ?? {}),
      context: JSON.stringify(e.context),
      country: e.enrichment.geo?.countryCode ?? '',
      city: e.enrichment.geo?.city ?? '',
      device_type: e.context.device?.type ?? '',
      browser: e.context.device?.browser ?? '',
      os: e.context.device?.os ?? '',
      page_url: e.context.page?.url ?? '',
      page_path: e.context.page?.path ?? '',
      referrer: e.context.page?.referrer ?? '',
      utm_source: e.context.campaign?.source ?? '',
      utm_medium: e.context.campaign?.medium ?? '',
      utm_campaign: e.context.campaign?.campaign ?? '',
    }));

    logger.debug(`ClickHouse: inserting ${rows.length} rows into ${this.database}.${this.table}`);
    // Production: await clickhouseClient.insert({ table, values: rows, format: 'JSONEachRow' })
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    return { healthy: true, latencyMs: Date.now() - start };
  }
}

// =============================================================================
// REDIS SINK (real-time counters + session state)
// =============================================================================

export class RedisSink extends BufferedSink {
  readonly name = 'redis-realtime';
  readonly type = 'redis';

  constructor(config: SinkConfig) {
    super(50, 1000, 2);
  }

  protected async writeBatch(events: EnrichedEvent[]): Promise<void> {
    // Update real-time counters per project
    const counters = new Map<string, number>();
    const sessions = new Set<string>();

    for (const event of events) {
      const key = `${event.projectId}:${event.type}`;
      counters.set(key, (counters.get(key) ?? 0) + 1);
      sessions.add(`${event.projectId}:${event.sessionId}`);
    }

    logger.debug(`Redis: updating ${counters.size} counters, ${sessions.size} sessions`);
    // Production: pipeline INCRBY + SADD + EXPIRE
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    return { healthy: true, latencyMs: Date.now() - start };
  }
}

// =============================================================================
// EVENT ROUTER — fans out events to all configured sinks
// =============================================================================

export class EventRouter {
  private sinks: EventSink[] = [];

  async addSink(sink: EventSink): Promise<void> {
    await sink.initialize();
    this.sinks.push(sink);
    logger.info(`Registered sink: ${sink.name} (${sink.type})`);
  }

  /** Route enriched events to all sinks concurrently */
  async route(events: EnrichedEvent[]): Promise<void> {
    if (events.length === 0 || this.sinks.length === 0) return;

    const results = await Promise.allSettled(
      this.sinks.map(sink => sink.write(events)),
    );

    for (let i = 0; i < results.length; i++) {
      if (results[i].status === 'rejected') {
        const reason = (results[i] as PromiseRejectedResult).reason;
        logger.error(`Sink ${this.sinks[i].name} write failed`, reason);
      }
    }
  }

  /** Flush all sinks */
  async flush(): Promise<void> {
    await Promise.allSettled(this.sinks.map(s => s.flush()));
  }

  /** Health check all sinks */
  async healthCheck(): Promise<Record<string, { healthy: boolean; latencyMs: number }>> {
    const results: Record<string, { healthy: boolean; latencyMs: number }> = {};
    for (const sink of this.sinks) {
      try {
        results[sink.name] = await sink.healthCheck();
      } catch {
        results[sink.name] = { healthy: false, latencyMs: -1 };
      }
    }
    return results;
  }

  /** Graceful shutdown */
  async close(): Promise<void> {
    await Promise.allSettled(this.sinks.map(s => s.close()));
    this.sinks = [];
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createSink(config: SinkConfig): EventSink {
  switch (config.type) {
    case 'kafka': return new KafkaSink(config);
    case 's3': return new S3Sink(config);
    case 'clickhouse': return new ClickHouseSink(config);
    case 'redis': return new RedisSink(config);
    default:
      throw new Error(`Unknown sink type: ${config.type}`);
  }
}
