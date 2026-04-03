/**
 * AETHER INGESTION SERVER
 * High-performance HTTP server for event ingestion.
 *
 * Endpoints:
 *   POST /v1/batch          - Ingest a batch of events
 *   POST /v1/track          - Single event shorthand
 *   POST /v1/identify       - Identity event shorthand
 *   GET  /health            - Health check
 *   GET  /metrics           - Prometheus-format metrics
 *   GET  /                  - Service info
 */

import { createServer, IncomingMessage, ServerResponse } from 'node:http';
import { createLogger } from '@aether/logger';
import {
  loadIngestionConfig,
  type BatchPayload,
  type BaseEvent,
  type IngestionConfig,
  type HealthStatus,
  type IngestionMetrics,
  type ApiKeyRecord,
  extractClientIp,
  startTimer,
  generateId,
  now,
  sha256,
  AetherError,
  ValidationError,
  AuthenticationError,
  RateLimitError,
  PayloadTooLargeError,
} from '@aether/common';
import { ApiKeyValidator, InMemoryApiKeyStore, RateLimiter } from '@aether/auth';
import { DeduplicationFilter, createCache, RealtimeCounters } from '@aether/cache';
import { EventRouter, createSink } from '@aether/events';
import { EventEnricher, DeadLetterQueue } from './event-enricher.js';
import { validateBatchPayload, validateEvent } from './validator.js';

const VERSION = '8.7.1';
const logger = createLogger('aether.ingestion');

// Maximum request body size: 1 MB
const MAX_BODY_SIZE = 1_048_576;

class IngestionServer {
  private config: IngestionConfig;
  private server: ReturnType<typeof createServer>;
  private apiKeyValidator: ApiKeyValidator;
  private rateLimiter: RateLimiter;
  private enricher: EventEnricher;
  private router: EventRouter;
  private dedup: DeduplicationFilter;
  private counters: RealtimeCounters;
  private dlq: DeadLetterQueue;
  private startTime = Date.now();
  private isShuttingDown = false;
  private processingTimes: number[] = [];
  private metrics: IngestionMetrics = {
    eventsReceived: 0,
    eventsProcessed: 0,
    eventsFailed: 0,
    eventsDropped: 0,
    batchesReceived: 0,
    avgBatchSize: 0,
    avgProcessingMs: 0,
    p99ProcessingMs: 0,
    activeConnections: 0,
    kafkaLag: 0,
    errorRate: 0,
  };

  constructor() {
    this.config = loadIngestionConfig();

    // Auth
    const keyStore = new InMemoryApiKeyStore();
    // Add a dev key for testing: "ak_dev_test_key_aether_12345"
    const devKeyRecord: ApiKeyRecord = {
      key: 'ak_dev_test_key_aether_12345',
      keyHash: '6a1cd7ac3b4bad7e2b9a682d00b920e514d3129a57115c2c414c393725bf96e9',
      projectId: 'proj_dev_001',
      projectName: 'Aether Development',
      organizationId: 'org_aether_dev',
      environment: 'development',
      permissions: {
        write: true,
        read: true,
        admin: false,
      },
      rateLimits: {
        eventsPerSecond: 100,
        eventsPerMinute: 5000,
        batchSizeLimit: 500,
        dailyEventLimit: 1_000_000,
      },
      createdAt: '2024-01-01T00:00:00.000Z',
      isActive: true,
    };
    keyStore.addKey(devKeyRecord);
    this.apiKeyValidator = new ApiKeyValidator(keyStore);

    // Rate limiting
    this.rateLimiter = new RateLimiter(this.config.rateLimiting.windowMs);

    // Cache + dedup + counters
    const cache = createCache(process.env.REDIS_URL);
    this.dedup = new DeduplicationFilter(cache, this.config.processing.deduplicationWindowMs);
    this.counters = new RealtimeCounters(cache);

    // Enrichment
    this.enricher = new EventEnricher(this.config.processing);

    // Sink router
    this.router = new EventRouter();

    // DLQ
    this.dlq = new DeadLetterQueue();

    // HTTP server
    this.server = createServer((req, res) => this.handleRequest(req, res));

    // Track active connections
    this.server.on('connection', () => {
      this.metrics.activeConnections++;
    });
    this.server.on('close', () => {
      this.metrics.activeConnections = 0;
    });
  }

  async start(): Promise<void> {
    // Initialize sinks
    for (const sinkConfig of this.config.sinks) {
      try {
        await this.router.addSink(createSink(sinkConfig));
      } catch (err) {
        logger.error(`Failed to initialize sink: ${sinkConfig.type}`, err as Error);
      }
    }

    // Graceful shutdown handlers
    process.on('SIGTERM', () => this.shutdown());
    process.on('SIGINT', () => this.shutdown());

    // Start listening
    return new Promise<void>((resolve) => {
      this.server.listen(this.config.port, this.config.host, () => {
        logger.info(`Aether Ingestion Server v${VERSION} listening`, {
          port: this.config.port,
          host: this.config.host,
          environment: this.config.environment,
          sinks: this.config.sinks.map((s) => s.type),
        });
        resolve();
      });
    });
  }

  // ---------------------------------------------------------------------------
  // REQUEST ROUTER
  // ---------------------------------------------------------------------------

  private async handleRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
    // CORS preflight
    if (req.method === 'OPTIONS') {
      this.setCorsHeaders(res);
      res.writeHead(204);
      res.end();
      return;
    }

    this.setCorsHeaders(res);

    const url = req.url ?? '/';
    const method = req.method ?? 'GET';

    try {
      // POST routes
      if (method === 'POST') {
        if (url === '/v1/batch') {
          await this.handleBatch(req, res);
          return;
        }
        if (url === '/v1/track') {
          await this.handleTrack(req, res);
          return;
        }
        if (url === '/v1/identify') {
          await this.handleIdentify(req, res);
          return;
        }
      }

      // GET routes
      if (method === 'GET') {
        if (url === '/health') {
          await this.handleHealth(req, res);
          return;
        }
        if (url === '/metrics') {
          this.handleMetrics(req, res);
          return;
        }
        if (url === '/') {
          this.handleServiceInfo(req, res);
          return;
        }
      }

      // 404
      this.sendJson(res, 404, {
        error: 'Not Found',
        code: 'NOT_FOUND',
        message: `${method} ${url} is not a valid endpoint`,
      });
    } catch (err) {
      this.handleError(res, err);
    }
  }

  // ---------------------------------------------------------------------------
  // POST /v1/batch
  // ---------------------------------------------------------------------------

  private async handleBatch(req: IncomingMessage, res: ServerResponse): Promise<void> {
    // 1. Read body
    const body = await this.readBody(req);

    // 2. Parse JSON
    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch {
      throw new ValidationError('Invalid JSON in request body');
    }

    // Delegate to core processing
    await this.processBatchPayload(req, res, parsed);
  }

  // ---------------------------------------------------------------------------
  // POST /v1/track  (single event shorthand)
  // ---------------------------------------------------------------------------

  private async handleTrack(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const body = await this.readBody(req);
    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch {
      throw new ValidationError('Invalid JSON in request body');
    }

    if (!parsed || typeof parsed !== 'object') {
      throw new ValidationError('Request body must be a JSON object');
    }

    const eventObj = parsed as Record<string, unknown>;

    // Default type to 'track' if not specified
    if (!eventObj.type) {
      eventObj.type = 'track';
    }

    // Ensure event has an id
    if (!eventObj.id) {
      eventObj.id = generateId();
    }

    // Ensure event has a timestamp
    if (!eventObj.timestamp) {
      eventObj.timestamp = now();
    }

    // Wrap in batch payload and delegate
    const batchPayload = {
      batch: [eventObj],
      sentAt: now(),
    };

    await this.processBatchPayload(req, res, batchPayload);
  }

  // ---------------------------------------------------------------------------
  // POST /v1/identify  (identity event shorthand)
  // ---------------------------------------------------------------------------

  private async handleIdentify(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const body = await this.readBody(req);
    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch {
      throw new ValidationError('Invalid JSON in request body');
    }

    if (!parsed || typeof parsed !== 'object') {
      throw new ValidationError('Request body must be a JSON object');
    }

    const eventObj = parsed as Record<string, unknown>;

    // Force type to 'identify'
    eventObj.type = 'identify';

    // Ensure event has an id
    if (!eventObj.id) {
      eventObj.id = generateId();
    }

    // Ensure event has a timestamp
    if (!eventObj.timestamp) {
      eventObj.timestamp = now();
    }

    // Wrap in batch payload and delegate
    const batchPayload = {
      batch: [eventObj],
      sentAt: now(),
    };

    await this.processBatchPayload(req, res, batchPayload);
  }

  // ---------------------------------------------------------------------------
  // CORE BATCH PROCESSING  (shared by /v1/batch, /v1/track, /v1/identify)
  // ---------------------------------------------------------------------------

  private async processBatchPayload(
    req: IncomingMessage,
    res: ServerResponse,
    parsed: unknown,
  ): Promise<void> {
    const timer = startTimer();

    // 1. Auth (validate API key from Authorization header)
    const authHeader = req.headers['authorization'] as string | undefined;
    const apiKey = ApiKeyValidator.extractKey(authHeader);
    if (!apiKey) {
      throw new AuthenticationError('Missing API key. Provide via Authorization: Bearer <key>');
    }

    const keyRecord = await this.apiKeyValidator.validate(apiKey);
    if (!keyRecord) {
      throw new AuthenticationError('Invalid or expired API key');
    }

    // 2. Rate limit check
    if (this.config.rateLimiting.enabled) {
      const rateLimitKey = this.config.rateLimiting.keyGenerator === 'ip'
        ? extractClientIp(req.headers as Record<string, string | string[] | undefined>)
        : keyRecord.projectId;

      const rateResult = this.rateLimiter.check(rateLimitKey, keyRecord.rateLimits);
      if (!rateResult.allowed) {
        res.setHeader('Retry-After', String(Math.ceil(rateResult.resetMs / 1000)));
        res.setHeader('X-RateLimit-Remaining', '0');
        res.setHeader('X-RateLimit-Reset', String(Math.ceil(rateResult.resetMs / 1000)));
        throw new RateLimitError(Math.ceil(rateResult.resetMs / 1000));
      }

      res.setHeader('X-RateLimit-Remaining', String(rateResult.remaining));
      res.setHeader('X-RateLimit-Reset', String(Math.ceil(rateResult.resetMs / 1000)));
    }

    // 3. Validate batch payload schema
    const batchPayload = validateBatchPayload(parsed);

    // 4. Validate individual events
    const validEvents: BaseEvent[] = [];
    const errors: Array<{ index: number; error: string }> = [];

    for (let i = 0; i < batchPayload.batch.length; i++) {
      try {
        const validEvent = validateEvent(batchPayload.batch[i], i);
        validEvents.push(validEvent);
      } catch (err) {
        if (err instanceof ValidationError) {
          errors.push({ index: i, error: err.message });
          if (this.config.processing.deadLetterEnabled) {
            this.dlq.push(batchPayload.batch[i], err.message);
          }
        } else {
          throw err;
        }
      }
    }

    this.metrics.eventsReceived += batchPayload.batch.length;
    this.metrics.batchesReceived++;
    this.metrics.eventsFailed += errors.length;

    // 5. Deduplicate
    const eventIds = validEvents.map((e) => e.id);
    const duplicates = await this.dedup.filterDuplicates(eventIds);
    const uniqueEvents = validEvents.filter((e) => !duplicates.has(e.id));
    const dedupDropped = validEvents.length - uniqueEvents.length;
    this.metrics.eventsDropped += dedupDropped;

    if (uniqueEvents.length === 0) {
      const durationMs = timer();
      this.recordProcessingTime(durationMs);
      this.sendJson(res, 200, {
        success: true,
        accepted: 0,
        duplicate: dedupDropped,
        errors: errors.length,
        processingMs: Math.round(durationMs * 100) / 100,
      });
      return;
    }

    // 6. Enrich events (GeoIP, UA, IP anonymization)
    const clientIp = extractClientIp(req.headers as Record<string, string | string[] | undefined>);
    const enrichedEvents = this.enricher.enrich(uniqueEvents, keyRecord.projectId, clientIp);

    // 7. Route to sinks
    try {
      await this.router.route(enrichedEvents);
      this.metrics.eventsProcessed += enrichedEvents.length;
    } catch (err) {
      logger.error('Failed to route events to sinks', err as Error);
      this.metrics.eventsFailed += enrichedEvents.length;
    }

    // 8. Update real-time counters (fire-and-forget)
    for (const event of enrichedEvents) {
      this.counters.incrementEventCount(keyRecord.projectId, event.type).catch(() => {});
    }

    // 9. Consume rate limit tokens for the batch
    if (this.config.rateLimiting.enabled) {
      const rateLimitKey = this.config.rateLimiting.keyGenerator === 'ip'
        ? clientIp
        : keyRecord.projectId;
      this.rateLimiter.consume(rateLimitKey, uniqueEvents.length);
    }

    const durationMs = timer();
    this.recordProcessingTime(durationMs);

    // Update batch size average
    const totalBatches = this.metrics.batchesReceived;
    this.metrics.avgBatchSize =
      (this.metrics.avgBatchSize * (totalBatches - 1) + batchPayload.batch.length) / totalBatches;

    // 10. Return 200 with accepted count
    this.sendJson(res, 200, {
      success: true,
      accepted: enrichedEvents.length,
      duplicate: dedupDropped,
      errors: errors.length > 0 ? errors : undefined,
      processingMs: Math.round(durationMs * 100) / 100,
    });
  }

  // ---------------------------------------------------------------------------
  // GET /health
  // ---------------------------------------------------------------------------

  private async handleHealth(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    const sinkHealth = await this.router.healthCheck();

    const checks: HealthStatus['checks'] = {};
    let overallHealthy = true;

    for (const [name, health] of Object.entries(sinkHealth)) {
      checks[name] = {
        status: health.healthy ? 'up' : 'down',
        latencyMs: health.latencyMs,
        lastCheck: now(),
      };
      if (!health.healthy) overallHealthy = false;
    }

    // Add ingestion server health
    checks['ingestion'] = {
      status: 'up',
      message: `Processing ${this.metrics.eventsProcessed} events`,
      lastCheck: now(),
    };

    const healthStatus: HealthStatus = {
      status: overallHealthy ? 'healthy' : 'degraded',
      version: VERSION,
      uptime: Math.floor((Date.now() - this.startTime) / 1000),
      timestamp: now(),
      checks,
    };

    this.sendJson(res, overallHealthy ? 200 : 503, healthStatus);
  }

  // ---------------------------------------------------------------------------
  // GET /metrics  (Prometheus text format)
  // ---------------------------------------------------------------------------

  private handleMetrics(_req: IncomingMessage, res: ServerResponse): void {
    const uptimeSeconds = Math.floor((Date.now() - this.startTime) / 1000);

    const lines = [
      '# HELP aether_ingestion_events_received_total Total events received',
      '# TYPE aether_ingestion_events_received_total counter',
      `aether_ingestion_events_received_total ${this.metrics.eventsReceived}`,
      '',
      '# HELP aether_ingestion_events_processed_total Total events successfully processed',
      '# TYPE aether_ingestion_events_processed_total counter',
      `aether_ingestion_events_processed_total ${this.metrics.eventsProcessed}`,
      '',
      '# HELP aether_ingestion_events_failed_total Total events that failed processing',
      '# TYPE aether_ingestion_events_failed_total counter',
      `aether_ingestion_events_failed_total ${this.metrics.eventsFailed}`,
      '',
      '# HELP aether_ingestion_events_dropped_total Total events dropped (duplicates)',
      '# TYPE aether_ingestion_events_dropped_total counter',
      `aether_ingestion_events_dropped_total ${this.metrics.eventsDropped}`,
      '',
      '# HELP aether_ingestion_batches_received_total Total batches received',
      '# TYPE aether_ingestion_batches_received_total counter',
      `aether_ingestion_batches_received_total ${this.metrics.batchesReceived}`,
      '',
      '# HELP aether_ingestion_avg_batch_size Average batch size',
      '# TYPE aether_ingestion_avg_batch_size gauge',
      `aether_ingestion_avg_batch_size ${Math.round(this.metrics.avgBatchSize * 100) / 100}`,
      '',
      '# HELP aether_ingestion_processing_duration_ms Average processing time in ms',
      '# TYPE aether_ingestion_processing_duration_ms gauge',
      `aether_ingestion_processing_duration_ms ${Math.round(this.metrics.avgProcessingMs * 100) / 100}`,
      '',
      '# HELP aether_ingestion_processing_p99_ms P99 processing time in ms',
      '# TYPE aether_ingestion_processing_p99_ms gauge',
      `aether_ingestion_processing_p99_ms ${Math.round(this.metrics.p99ProcessingMs * 100) / 100}`,
      '',
      '# HELP aether_ingestion_active_connections Current active connections',
      '# TYPE aether_ingestion_active_connections gauge',
      `aether_ingestion_active_connections ${this.metrics.activeConnections}`,
      '',
      '# HELP aether_ingestion_dlq_size Dead letter queue size',
      '# TYPE aether_ingestion_dlq_size gauge',
      `aether_ingestion_dlq_size ${this.dlq.size}`,
      '',
      '# HELP aether_ingestion_error_rate Error rate (failed / received)',
      '# TYPE aether_ingestion_error_rate gauge',
      `aether_ingestion_error_rate ${this.metrics.eventsReceived > 0 ? Math.round((this.metrics.eventsFailed / this.metrics.eventsReceived) * 10000) / 10000 : 0}`,
      '',
      '# HELP aether_ingestion_uptime_seconds Server uptime in seconds',
      '# TYPE aether_ingestion_uptime_seconds counter',
      `aether_ingestion_uptime_seconds ${uptimeSeconds}`,
      '',
    ];

    res.writeHead(200, {
      'Content-Type': 'text/plain; version=0.0.4; charset=utf-8',
    });
    res.end(lines.join('\n'));
  }

  // ---------------------------------------------------------------------------
  // GET / (service info)
  // ---------------------------------------------------------------------------

  private handleServiceInfo(_req: IncomingMessage, res: ServerResponse): void {
    this.sendJson(res, 200, {
      service: 'aether-ingestion',
      version: VERSION,
      status: 'running',
      uptime: Math.floor((Date.now() - this.startTime) / 1000),
      endpoints: {
        'POST /v1/batch': 'Ingest a batch of events',
        'POST /v1/track': 'Single track event shorthand',
        'POST /v1/identify': 'Single identify event shorthand',
        'GET /health': 'Health check',
        'GET /metrics': 'Prometheus-format metrics',
      },
    });
  }

  // ---------------------------------------------------------------------------
  // HELPERS
  // ---------------------------------------------------------------------------

  /** Read the request body with a size limit */
  private readBody(req: IncomingMessage): Promise<string> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      let totalSize = 0;

      req.on('data', (chunk: Buffer) => {
        totalSize += chunk.length;
        if (totalSize > MAX_BODY_SIZE) {
          req.destroy();
          reject(new PayloadTooLargeError(MAX_BODY_SIZE));
          return;
        }
        chunks.push(chunk);
      });

      req.on('end', () => {
        resolve(Buffer.concat(chunks).toString('utf-8'));
      });

      req.on('error', (err) => {
        reject(err);
      });
    });
  }

  /** Set CORS headers on the response */
  private setCorsHeaders(res: ServerResponse): void {
    const origins = this.config.cors.origins.join(', ');
    const isWildcard = origins.trim() === '*';
    res.setHeader('Access-Control-Allow-Origin', isWildcard ? '*' : origins);
    res.setHeader('Access-Control-Allow-Methods', this.config.cors.methods.join(', '));
    res.setHeader('Access-Control-Allow-Headers', this.config.cors.allowedHeaders.join(', '));
    res.setHeader('Access-Control-Max-Age', String(this.config.cors.maxAge));
    // CORS spec: credentials must not be 'true' with wildcard origin
    if (!isWildcard) {
      res.setHeader('Access-Control-Allow-Credentials', 'true');
    }
  }

  /** Send a JSON response */
  private sendJson(res: ServerResponse, statusCode: number, data: unknown): void {
    const body = JSON.stringify(data);
    res.writeHead(statusCode, {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body),
      'X-Aether-Version': VERSION,
      'X-Request-Id': generateId(),
    });
    res.end(body);
  }

  /** Centralized error handler */
  private handleError(res: ServerResponse, err: unknown): void {
    if (err instanceof AetherError) {
      this.sendJson(res, err.statusCode, {
        error: err.name,
        code: err.code,
        message: err.message,
        details: err.details,
      });
      return;
    }

    logger.error('Unhandled error in request handler', err as Error);
    this.sendJson(res, 500, {
      error: 'InternalServerError',
      code: 'INTERNAL_ERROR',
      message: 'An unexpected error occurred',
    });
  }

  /** Record a processing time for metrics */
  private recordProcessingTime(durationMs: number): void {
    this.processingTimes.push(durationMs);

    // Keep only last 1000 measurements
    if (this.processingTimes.length > 1000) {
      this.processingTimes.splice(0, this.processingTimes.length - 1000);
    }

    // Update avg
    const sum = this.processingTimes.reduce((a, b) => a + b, 0);
    this.metrics.avgProcessingMs = sum / this.processingTimes.length;

    // Update p99
    const sorted = [...this.processingTimes].sort((a, b) => a - b);
    const p99Index = Math.floor(sorted.length * 0.99);
    this.metrics.p99ProcessingMs = sorted[p99Index] ?? durationMs;

    // Update error rate
    this.metrics.errorRate =
      this.metrics.eventsReceived > 0
        ? this.metrics.eventsFailed / this.metrics.eventsReceived
        : 0;
  }

  /** Graceful shutdown */
  private async shutdown(): Promise<void> {
    if (this.isShuttingDown) return;
    this.isShuttingDown = true;

    logger.info('Shutting down Aether Ingestion Server...');

    // Stop accepting new connections
    this.server.close(() => {
      logger.info('HTTP server closed');
    });

    // Flush sinks
    try {
      await this.router.flush();
      logger.info('All sinks flushed');
    } catch (err) {
      logger.error('Error flushing sinks during shutdown', err as Error);
    }

    // Close sinks
    try {
      await this.router.close();
      logger.info('All sinks closed');
    } catch (err) {
      logger.error('Error closing sinks during shutdown', err as Error);
    }

    // Destroy rate limiter
    this.rateLimiter.destroy();

    logger.info('Aether Ingestion Server shutdown complete');
    process.exit(0);
  }
}

// =============================================================================
// ENTRY POINT
// =============================================================================

const server = new IngestionServer();

server.start().catch((err) => {
  logger.fatal('Failed to start Aether Ingestion Server', err as Error);
  process.exit(1);
});
