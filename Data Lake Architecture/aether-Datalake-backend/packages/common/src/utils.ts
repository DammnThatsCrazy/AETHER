import { createHash, randomUUID } from 'node:crypto';
import type { BaseEvent, IngestionConfig } from './types.js';

export function generateId(): string {
  return randomUUID();
}

export function now(): string {
  return new Date().toISOString();
}

export function sha256(input: string): string {
  return createHash('sha256').update(input).digest('hex');
}

export function anonymizeIp(ip: string): string {
  if (ip.includes(':')) {
    const parts = ip.split(':');
    return parts.slice(0, 4).join(':') + ':0:0:0:0';
  }
  const parts = ip.split('.');
  return parts.slice(0, 3).join('.') + '.0';
}

export function extractClientIp(headers: Record<string, string | string[] | undefined>): string {
  const xff = headers['x-forwarded-for'];
  if (xff) {
    const first = Array.isArray(xff) ? xff[0] : xff.split(',')[0];
    return first.trim();
  }
  return '0.0.0.0';
}

export function startTimer(): () => number {
  const start = performance.now();
  return () => Math.round(performance.now() - start);
}

export function chunk<T>(arr: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export function backoffDelay(attempt: number, baseMs: number = 1000, maxMs: number = 30000): number {
  return Math.min(baseMs * Math.pow(2, attempt), maxMs);
}

export function safeJsonParse<T = unknown>(input: string): T | null {
  try {
    return JSON.parse(input) as T;
  } catch {
    return null;
  }
}

/**
 * Generate a Hive-style partition key for an event.
 * Accepts either a BaseEvent (uses projectId + timestamp) or (projectId, date) pair.
 */
export function partitionKey(eventOrProjectId: BaseEvent | string, date?: Date): string {
  let projectId: string;
  let d: Date;

  if (typeof eventOrProjectId === 'string') {
    projectId = eventOrProjectId;
    d = date ?? new Date();
  } else {
    projectId = eventOrProjectId.projectId;
    d = new Date(eventOrProjectId.timestamp);
  }

  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  const h = String(d.getUTCHours()).padStart(2, '0');
  return `project_id=${projectId}/year=${y}/month=${m}/day=${day}/hour=${h}`;
}

/**
 * Load ingestion configuration from environment variables with sensible defaults.
 */
export function loadIngestionConfig(): IngestionConfig {
  return {
    port: parseInt(process.env.INGESTION_PORT ?? '8081', 10),
    host: process.env.INGESTION_HOST ?? '0.0.0.0',
    environment: (process.env.NODE_ENV ?? 'development') as IngestionConfig['environment'],
    cors: {
      origins: (process.env.CORS_ORIGINS ?? '*').split(','),
      methods: ['GET', 'POST', 'OPTIONS'],
      allowedHeaders: ['Content-Type', 'Authorization', 'X-Aether-Key', 'X-Request-Id'],
      maxAge: 86400,
    },
    rateLimiting: {
      enabled: process.env.RATE_LIMIT_ENABLED !== 'false',
      windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS ?? '60000', 10),
      maxRequestsPerWindow: parseInt(process.env.RATE_LIMIT_MAX ?? '1000', 10),
      keyGenerator: 'apiKey',
    },
    processing: {
      maxBatchSize: parseInt(process.env.MAX_BATCH_SIZE ?? '500', 10),
      maxEventSizeBytes: parseInt(process.env.MAX_EVENT_SIZE ?? '65536', 10),
      enrichGeo: process.env.ENRICH_GEO !== 'false',
      enrichUA: process.env.ENRICH_UA !== 'false',
      anonymizeIp: process.env.ANONYMIZE_IP !== 'false',
      validateSchema: true,
      deduplicationWindowMs: parseInt(process.env.DEDUP_WINDOW_MS ?? '300000', 10),
      deadLetterEnabled: process.env.DLQ_ENABLED !== 'false',
    },
    sinks: parseSinkConfig(),
    monitoring: {
      metricsEnabled: process.env.METRICS_ENABLED !== 'false',
      metricsPort: parseInt(process.env.METRICS_PORT ?? '9090', 10),
      healthCheckPath: process.env.HEALTH_PATH ?? '/health',
      tracingEnabled: process.env.TRACING_ENABLED === 'true',
      logLevel: (process.env.LOG_LEVEL ?? 'info') as 'debug' | 'info' | 'warn' | 'error',
    },
  };
}

function parseSinkConfig(): IngestionConfig['sinks'] {
  const sinkTypes = (process.env.SINKS ?? 'kafka').split(',').map(s => s.trim());
  return sinkTypes.map(type => ({
    type: type as 'kafka' | 's3' | 'clickhouse' | 'redis',
    enabled: true,
    config: {},
    batchSize: 100,
    flushIntervalMs: 5000,
    retryAttempts: 3,
  }));
}
