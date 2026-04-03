// =============================================================================
// AETHER BACKEND — EVENT BUS & SINK ROUTER
// Fan-out enriched events to multiple downstream sinks concurrently
// =============================================================================

import * as http from 'node:http';
import * as https from 'node:https';
import * as net from 'node:net';
import * as zlib from 'node:zlib';
import { Buffer } from 'node:buffer';

import { createLogger } from '@aether/logger';
import type { EnrichedEvent, SinkConfig } from '@aether/common';
import { backoffDelay, sleep } from '@aether/common';

const logger = createLogger('aether.events');

// =============================================================================
// HTTP HELPERS
// =============================================================================

interface HttpRequestOptions {
  url: string;
  method?: string;
  headers?: Record<string, string>;
  body?: Buffer | string;
  timeoutMs?: number;
}

interface HttpResponse {
  statusCode: number;
  headers: http.IncomingHttpHeaders;
  body: string;
}

function httpRequest(opts: HttpRequestOptions): Promise<HttpResponse> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(opts.url);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : http;

    const reqOpts: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method: opts.method ?? 'GET',
      headers: opts.headers ?? {},
      timeout: opts.timeoutMs ?? 30_000,
    };

    const req = lib.request(reqOpts, (res) => {
      const chunks: Buffer[] = [];
      res.on('data', (chunk: Buffer) => chunks.push(chunk));
      res.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf-8');
        resolve({
          statusCode: res.statusCode ?? 0,
          headers: res.headers,
          body,
        });
      });
      res.on('error', reject);
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy(new Error(`HTTP request timed out after ${opts.timeoutMs ?? 30_000}ms`));
    });

    if (opts.body) {
      req.write(opts.body);
    }
    req.end();
  });
}

function gzipCompress(data: string): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    zlib.gzip(Buffer.from(data, 'utf-8'), (err, result) => {
      if (err) reject(err);
      else resolve(result);
    });
  });
}

// =============================================================================
// RESP (Redis Serialization Protocol) HELPERS
// =============================================================================

function encodeRESP(args: string[]): string {
  let out = `*${args.length}\r\n`;
  for (const arg of args) {
    const buf = Buffer.from(arg, 'utf-8');
    out += `$${buf.length}\r\n${arg}\r\n`;
  }
  return out;
}

function sendRESPCommands(
  host: string,
  port: number,
  commands: string[][],
  password?: string,
  timeoutMs: number = 10_000,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = new net.Socket();
    const chunks: Buffer[] = [];
    let settled = false;

    const finish = (err?: Error) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      if (err) reject(err);
      else resolve(Buffer.concat(chunks).toString('utf-8'));
    };

    socket.setTimeout(timeoutMs);
    socket.on('timeout', () => finish(new Error(`Redis TCP timeout after ${timeoutMs}ms`)));
    socket.on('error', (err) => finish(err));
    socket.on('data', (chunk: Buffer) => chunks.push(chunk));

    socket.connect(port, host, () => {
      let payload = '';
      if (password) {
        payload += encodeRESP(['AUTH', password]);
      }
      for (const cmd of commands) {
        payload += encodeRESP(cmd);
      }
      socket.write(payload);
      // Give Redis time to respond, then close
      setTimeout(() => finish(), 500);
    });
  });
}

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
  protected async onFailure(_events: EnrichedEvent[], _error: Error): Promise<void> {
    // Default: log and drop. Override for DLQ behavior.
  }

  abstract healthCheck(): Promise<{ healthy: boolean; latencyMs: number }>;
}

// =============================================================================
// KAFKA SINK
// Produces messages via Confluent Kafka REST Proxy (HTTP interface).
// Config: restProxyUrl (default http://kafka:8082), topic
// =============================================================================

export class KafkaSink extends BufferedSink {
  readonly name = 'kafka';
  readonly type = 'kafka';
  private topic: string;
  private brokers: string[];
  private restProxyUrl: string;

  constructor(config: SinkConfig) {
    super(config.batchSize ?? 100, config.flushIntervalMs ?? 1000, config.retryAttempts ?? 3);
    const c = config.config as Record<string, any>;
    this.brokers = c.brokers ?? ['localhost:9092'];
    this.topic = c.topic ?? 'aether.events.raw';
    this.restProxyUrl = (c.restProxyUrl as string ?? 'http://kafka:8082').replace(/\/+$/, '');
  }

  async initialize(): Promise<void> {
    await super.initialize();

    // Verify REST Proxy is reachable
    try {
      const res = await httpRequest({
        url: `${this.restProxyUrl}/topics`,
        method: 'GET',
        timeoutMs: 5_000,
      });
      if (res.statusCode >= 400) {
        logger.warn('Kafka REST Proxy returned non-OK on init', { statusCode: res.statusCode });
      }
    } catch (err) {
      logger.warn('Kafka REST Proxy not reachable on init, will retry on writes', { error: (err as Error).message });
    }

    logger.info('Kafka sink ready', { brokers: this.brokers, topic: this.topic, restProxyUrl: this.restProxyUrl });
  }

  protected async writeBatch(events: EnrichedEvent[]): Promise<void> {
    // Build Confluent REST Proxy v2 JSON payload
    const records = events.map(e => ({
      key: { type: 'STRING' as const, data: e.partitionKey },
      value: { type: 'JSON' as const, data: e },
      headers: [
        { name: 'event-type', value: Buffer.from(e.type).toString('base64') },
        { name: 'project-id', value: Buffer.from(e.projectId).toString('base64') },
        { name: 'received-at', value: Buffer.from(e.receivedAt).toString('base64') },
      ],
    }));

    const body = JSON.stringify({
      records: records.map(r => ({
        key: r.key.data,
        value: r.value.data,
        headers: r.headers.map(h => ({ name: h.name, value: h.value })),
      })),
    });

    const res = await httpRequest({
      url: `${this.restProxyUrl}/topics/${encodeURIComponent(this.topic)}`,
      method: 'POST',
      headers: {
        'Content-Type': 'application/vnd.kafka.json.v2+json',
        'Accept': 'application/vnd.kafka.v2+json',
      },
      body,
      timeoutMs: 30_000,
    });

    if (res.statusCode >= 400) {
      throw new Error(
        `Kafka REST Proxy returned HTTP ${res.statusCode} for topic ${this.topic}: ${res.body.slice(0, 500)}`,
      );
    }

    logger.debug(`Kafka: wrote ${events.length} messages to ${this.topic}`, { statusCode: res.statusCode });
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    try {
      const res = await httpRequest({
        url: `${this.restProxyUrl}/topics/${encodeURIComponent(this.topic)}`,
        method: 'GET',
        headers: { 'Accept': 'application/vnd.kafka.v2+json' },
        timeoutMs: 5_000,
      });
      const latencyMs = Date.now() - start;
      return { healthy: res.statusCode < 400, latencyMs };
    } catch {
      return { healthy: false, latencyMs: Date.now() - start };
    }
  }

  async close(): Promise<void> {
    await super.close();
    logger.info('Kafka sink closed');
  }
}

// =============================================================================
// S3 SINK (JSONL with hourly partitioning)
// Writes gzipped JSONL to an S3-compatible object store via HTTP PUT.
// Config: endpoint (default http://s3:9000), bucket, prefix, region
// Compatible with AWS S3, MinIO, and any S3-compatible store.
// =============================================================================

export class S3Sink extends BufferedSink {
  readonly name = 's3';
  readonly type = 's3';
  private bucket: string;
  private prefix: string;
  private endpoint: string;
  private region: string;

  constructor(config: SinkConfig) {
    super(config.batchSize ?? 5000, config.flushIntervalMs ?? 60000, config.retryAttempts ?? 3);
    const c = config.config as Record<string, any>;
    this.bucket = c.bucket ?? 'aether-events-raw';
    this.prefix = c.prefix ?? 'events/';
    this.endpoint = (c.endpoint as string ?? 'http://s3:9000').replace(/\/+$/, '');
    this.region = c.region ?? 'us-east-1';
  }

  async initialize(): Promise<void> {
    await super.initialize();

    // Verify bucket is accessible
    try {
      const res = await httpRequest({
        url: `${this.endpoint}/${this.bucket}`,
        method: 'HEAD',
        timeoutMs: 5_000,
      });
      if (res.statusCode >= 400 && res.statusCode !== 403) {
        logger.warn('S3 bucket HEAD check returned non-OK on init', { statusCode: res.statusCode });
      }
    } catch (err) {
      logger.warn('S3 endpoint not reachable on init, will retry on writes', { error: (err as Error).message });
    }

    logger.info('S3 sink ready', { endpoint: this.endpoint, bucket: this.bucket, prefix: this.prefix });
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
    const jsonl = events.map(e => JSON.stringify(e)).join('\n');
    const compressed = await gzipCompress(jsonl);

    // Build the S3 PUT URL: /{bucket}/{key}
    const objectUrl = `${this.endpoint}/${this.bucket}/${key}`;
    const dateStr = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
    const dateDay = dateStr.slice(0, 8);

    const res = await httpRequest({
      url: objectUrl,
      method: 'PUT',
      headers: {
        'Content-Type': 'application/gzip',
        'Content-Encoding': 'gzip',
        'Content-Length': String(compressed.length),
        'x-amz-date': dateStr,
        'x-amz-content-sha256': 'UNSIGNED-PAYLOAD',
        'x-amz-storage-class': 'STANDARD',
      },
      body: compressed,
      timeoutMs: 60_000,
    });

    if (res.statusCode >= 400) {
      throw new Error(
        `S3 PUT returned HTTP ${res.statusCode} for key ${key}: ${res.body.slice(0, 500)}`,
      );
    }

    logger.debug(`S3: wrote ${events.length} events to s3://${this.bucket}/${key}`, {
      statusCode: res.statusCode,
      compressedBytes: compressed.length,
      rawBytes: Buffer.byteLength(jsonl, 'utf-8'),
    });
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    try {
      // HEAD the bucket to verify connectivity
      const res = await httpRequest({
        url: `${this.endpoint}/${this.bucket}`,
        method: 'HEAD',
        timeoutMs: 5_000,
      });
      const latencyMs = Date.now() - start;
      // 200 = accessible, 403 = exists but no ListBucket permission (still healthy)
      return { healthy: res.statusCode === 200 || res.statusCode === 403, latencyMs };
    } catch {
      return { healthy: false, latencyMs: Date.now() - start };
    }
  }

  async close(): Promise<void> {
    await super.close();
    logger.info('S3 sink closed');
  }
}

// =============================================================================
// CLICKHOUSE SINK
// Uses ClickHouse native HTTP interface (port 8123) to INSERT in JSONEachRow format.
// Config: host, port, database, table, user, password, protocol
// =============================================================================

export class ClickHouseSink extends BufferedSink {
  readonly name = 'clickhouse';
  readonly type = 'clickhouse';
  private host: string;
  private port: number;
  private database: string;
  private table: string;
  private user: string;
  private password: string;
  private protocol: string;

  constructor(config: SinkConfig) {
    super(config.batchSize ?? 1000, config.flushIntervalMs ?? 5000, config.retryAttempts ?? 3);
    const c = config.config as Record<string, any>;
    this.host = c.host ?? 'localhost';
    this.port = c.port ?? 8123;
    this.database = c.database ?? 'aether';
    this.table = c.table ?? 'events';
    this.user = c.user ?? 'default';
    this.password = c.password ?? '';
    this.protocol = c.protocol ?? 'http';
  }

  async initialize(): Promise<void> {
    await super.initialize();

    // Ping ClickHouse to verify connectivity
    try {
      const res = await httpRequest({
        url: `${this.protocol}://${this.host}:${this.port}/ping`,
        method: 'GET',
        timeoutMs: 5_000,
      });
      if (res.statusCode !== 200) {
        logger.warn('ClickHouse ping returned non-200 on init', { statusCode: res.statusCode, body: res.body });
      }
    } catch (err) {
      logger.warn('ClickHouse not reachable on init, will retry on writes', { error: (err as Error).message });
    }

    logger.info('ClickHouse sink ready', {
      host: this.host,
      port: this.port,
      database: this.database,
      table: this.table,
    });
  }

  protected async writeBatch(events: EnrichedEvent[]): Promise<void> {
    const rows = events.map(e => JSON.stringify({
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

    const ndjson = rows.join('\n');

    // ClickHouse HTTP interface: POST /?query=INSERT INTO db.table FORMAT JSONEachRow
    const insertQuery = `INSERT INTO ${this.database}.${this.table} FORMAT JSONEachRow`;
    const queryParam = encodeURIComponent(insertQuery);
    const url = `${this.protocol}://${this.host}:${this.port}/?query=${queryParam}`;

    const headers: Record<string, string> = {
      'Content-Type': 'application/x-ndjson',
    };

    // ClickHouse supports basic auth via headers
    if (this.user) {
      headers['X-ClickHouse-User'] = this.user;
    }
    if (this.password) {
      headers['X-ClickHouse-Key'] = this.password;
    }

    const res = await httpRequest({
      url,
      method: 'POST',
      headers,
      body: ndjson,
      timeoutMs: 30_000,
    });

    if (res.statusCode >= 400) {
      throw new Error(
        `ClickHouse INSERT returned HTTP ${res.statusCode} for ${this.database}.${this.table}: ${res.body.slice(0, 500)}`,
      );
    }

    logger.debug(`ClickHouse: inserted ${rows.length} rows into ${this.database}.${this.table}`, {
      statusCode: res.statusCode,
    });
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    try {
      // ClickHouse /ping endpoint returns "Ok.\n" on success
      const res = await httpRequest({
        url: `${this.protocol}://${this.host}:${this.port}/ping`,
        method: 'GET',
        timeoutMs: 5_000,
      });
      const latencyMs = Date.now() - start;
      return { healthy: res.statusCode === 200, latencyMs };
    } catch {
      return { healthy: false, latencyMs: Date.now() - start };
    }
  }

  async close(): Promise<void> {
    await super.close();
    logger.info('ClickHouse sink closed');
  }
}

// =============================================================================
// REDIS SINK (real-time counters + session state)
// Uses RESP protocol over TCP (node:net) to send INCRBY, SADD, EXPIRE commands.
// Config: host, port, password, db, ttlSeconds
// =============================================================================

export class RedisSink extends BufferedSink {
  readonly name = 'redis-realtime';
  readonly type = 'redis';
  private host: string;
  private port: number;
  private password?: string;
  private db: number;
  private ttlSeconds: number;

  constructor(config: SinkConfig) {
    super(50, 1000, 2);
    const c = config.config as Record<string, any>;
    this.host = c.host ?? 'localhost';
    this.port = c.port ?? 6379;
    this.password = c.password;
    this.db = c.db ?? 0;
    this.ttlSeconds = c.ttlSeconds ?? 86400; // 24 hours default
  }

  async initialize(): Promise<void> {
    await super.initialize();

    // Verify Redis connectivity with PING
    try {
      const commands: string[][] = [];
      if (this.db !== 0) {
        commands.push(['SELECT', String(this.db)]);
      }
      commands.push(['PING']);
      const response = await sendRESPCommands(this.host, this.port, commands, this.password, 5_000);
      if (!response.includes('+PONG') && !response.includes('+OK')) {
        logger.warn('Redis PING did not return expected response on init', { response: response.slice(0, 200) });
      }
    } catch (err) {
      logger.warn('Redis not reachable on init, will retry on writes', { error: (err as Error).message });
    }

    logger.info('Redis sink ready', { host: this.host, port: this.port, db: this.db });
  }

  protected async writeBatch(events: EnrichedEvent[]): Promise<void> {
    const counters = new Map<string, number>();
    const sessions = new Set<string>();

    for (const event of events) {
      const key = `${event.projectId}:${event.type}`;
      counters.set(key, (counters.get(key) ?? 0) + 1);
      sessions.add(`${event.projectId}:${event.sessionId}`);
    }

    // Build pipeline of RESP commands
    const commands: string[][] = [];

    if (this.db !== 0) {
      commands.push(['SELECT', String(this.db)]);
    }

    // Minute-granularity counter keys for real-time dashboards
    const minuteKey = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '');

    for (const [key, count] of counters) {
      const redisKey = `aether:counter:${key}:${minuteKey}`;
      commands.push(['INCRBY', redisKey, String(count)]);
      commands.push(['EXPIRE', redisKey, String(this.ttlSeconds)]);
    }

    // Track active sessions in a set with TTL
    const sessionSetKey = `aether:sessions:${minuteKey}`;
    for (const session of sessions) {
      commands.push(['SADD', sessionSetKey, session]);
    }
    if (sessions.size > 0) {
      commands.push(['EXPIRE', sessionSetKey, String(this.ttlSeconds)]);
    }

    const response = await sendRESPCommands(this.host, this.port, commands, this.password, 10_000);

    // Check for RESP error responses (lines starting with -)
    const lines = response.split('\r\n');
    const errors = lines.filter(l => l.startsWith('-'));
    if (errors.length > 0) {
      throw new Error(`Redis pipeline returned ${errors.length} error(s): ${errors.slice(0, 3).join('; ')}`);
    }

    logger.debug(`Redis: updated ${counters.size} counters, ${sessions.size} sessions`, {
      commandCount: commands.length,
    });
  }

  async healthCheck(): Promise<{ healthy: boolean; latencyMs: number }> {
    const start = Date.now();
    try {
      const response = await sendRESPCommands(this.host, this.port, [['PING']], this.password, 5_000);
      const latencyMs = Date.now() - start;
      return { healthy: response.includes('+PONG'), latencyMs };
    } catch {
      return { healthy: false, latencyMs: Date.now() - start };
    }
  }

  async close(): Promise<void> {
    await super.close();
    logger.info('Redis sink closed');
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
