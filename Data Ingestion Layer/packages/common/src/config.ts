// =============================================================================
// AETHER BACKEND — CONFIGURATION LOADER
// Environment-aware config with type-safe defaults and validation
// =============================================================================

import type { IngestionConfig, SinkConfig } from './types.js';

function env(key: string, fallback: string = ''): string {
  return process.env[key] ?? fallback;
}

function envInt(key: string, fallback: number): number {
  const v = process.env[key];
  return v ? parseInt(v, 10) : fallback;
}

function envBool(key: string, fallback: boolean): boolean {
  const v = process.env[key];
  if (!v) return fallback;
  return v === 'true' || v === '1';
}

export function loadIngestionConfig(): IngestionConfig {
  const environment = env('NODE_ENV', 'development') as IngestionConfig['environment'];

  const sinks: SinkConfig[] = [
    {
      type: 'kafka',
      enabled: envBool('KAFKA_ENABLED', true),
      config: {
        brokers: env('KAFKA_BROKERS', 'localhost:9092').split(','),
        topic: env('KAFKA_EVENTS_TOPIC', 'aether.events.raw'),
        clientId: env('KAFKA_CLIENT_ID', 'aether-ingestion'),
        compression: env('KAFKA_COMPRESSION', 'snappy'),
        acks: envInt('KAFKA_ACKS', -1),
        maxBatchSize: envInt('KAFKA_MAX_BATCH_SIZE', 16384),
        lingerMs: envInt('KAFKA_LINGER_MS', 5),
        ssl: envBool('KAFKA_SSL', environment === 'production'),
        sasl: envBool('KAFKA_SASL', environment === 'production')
          ? { mechanism: 'plain', username: env('KAFKA_SASL_USER'), password: env('KAFKA_SASL_PASS') }
          : undefined,
      },
      batchSize: envInt('KAFKA_FLUSH_BATCH', 100),
      flushIntervalMs: envInt('KAFKA_FLUSH_INTERVAL_MS', 1000),
      retryAttempts: 3,
    },
    {
      type: 's3',
      enabled: envBool('S3_ENABLED', true),
      config: {
        bucket: env('S3_EVENTS_BUCKET', 'aether-events-raw'),
        region: env('AWS_REGION', 'us-east-1'),
        prefix: env('S3_PREFIX', 'events/'),
        format: 'jsonl',
        compression: 'gzip',
        partitionBy: 'hour',
      },
      batchSize: envInt('S3_FLUSH_BATCH', 5000),
      flushIntervalMs: envInt('S3_FLUSH_INTERVAL_MS', 60000),
      retryAttempts: 3,
    },
    {
      type: 'clickhouse',
      enabled: envBool('CLICKHOUSE_ENABLED', false),
      config: {
        host: env('CLICKHOUSE_HOST', 'localhost'),
        port: envInt('CLICKHOUSE_PORT', 8123),
        database: env('CLICKHOUSE_DB', 'aether'),
        username: env('CLICKHOUSE_USER', 'default'),
        password: env('CLICKHOUSE_PASS', ''),
        table: 'events',
      },
      batchSize: envInt('CLICKHOUSE_FLUSH_BATCH', 1000),
      flushIntervalMs: envInt('CLICKHOUSE_FLUSH_INTERVAL_MS', 5000),
      retryAttempts: 3,
    },
    {
      type: 'redis',
      enabled: envBool('REDIS_ENABLED', true),
      config: {
        url: env('REDIS_URL', 'redis://localhost:6379'),
        prefix: 'aether:rt:',
        ttlSeconds: envInt('REDIS_RT_TTL', 86400),
      },
    },
  ];

  return {
    port: envInt('PORT', 3001),
    host: env('HOST', '0.0.0.0'),
    environment,
    cors: {
      origins: env('CORS_ORIGINS', 'http://localhost:3000,https://app.aether.io').split(','),
      methods: ['GET', 'POST', 'OPTIONS'],
      allowedHeaders: ['Content-Type', 'Authorization', 'X-Aether-SDK'],
      maxAge: 86400,
    },
    rateLimiting: {
      enabled: envBool('RATE_LIMIT_ENABLED', true),
      windowMs: envInt('RATE_LIMIT_WINDOW_MS', 60000),
      maxRequestsPerWindow: envInt('RATE_LIMIT_MAX_REQUESTS', 1000),
      keyGenerator: 'apiKey',
    },
    processing: {
      maxBatchSize: envInt('MAX_BATCH_SIZE', 500),
      maxEventSizeBytes: envInt('MAX_EVENT_SIZE_BYTES', 32768),
      enrichGeo: envBool('ENRICH_GEO', true),
      enrichUA: envBool('ENRICH_UA', true),
      anonymizeIp: envBool('ANONYMIZE_IP', true),
      validateSchema: envBool('VALIDATE_SCHEMA', true),
      deduplicationWindowMs: envInt('DEDUP_WINDOW_MS', 300000),
      deadLetterEnabled: envBool('DLQ_ENABLED', true),
    },
    sinks: sinks.filter(s => s.enabled),
    monitoring: {
      metricsEnabled: envBool('METRICS_ENABLED', true),
      metricsPort: envInt('METRICS_PORT', 9090),
      healthCheckPath: '/health',
      tracingEnabled: envBool('TRACING_ENABLED', false),
      logLevel: env('LOG_LEVEL', 'info') as 'debug' | 'info' | 'warn' | 'error',
    },
  };
}
