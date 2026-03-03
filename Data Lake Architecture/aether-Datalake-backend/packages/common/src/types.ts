// =============================================================================
// AETHER COMMON — TYPE DEFINITIONS
// Shared across ingestion, data lake, and all services
// =============================================================================

// Event types
export type EventType = 'track' | 'page' | 'screen' | 'identify' | 'conversion' | 'wallet' | 'transaction' | 'error' | 'performance' | 'experiment' | 'consent' | 'heartbeat';

export interface BaseEvent {
  id: string;
  type: EventType;
  timestamp: string;
  anonymousId: string;
  userId?: string;
  sessionId: string;
  projectId: string;
  properties?: Record<string, unknown>;
  context?: EventContext;
}

export interface EventContext {
  page?: { url?: string; path?: string; title?: string; referrer?: string; search?: string };
  device?: { type?: string; browser?: string; browserVersion?: string; os?: string; osVersion?: string; screenWidth?: number; screenHeight?: number; viewportWidth?: number; viewportHeight?: number; pixelRatio?: number; language?: string };
  campaign?: { source?: string; medium?: string; campaign?: string; content?: string; term?: string; clickId?: string; referrerDomain?: string; referrerType?: string };
  sdk?: { name?: string; version?: string };
  consent?: { analytics: boolean; marketing: boolean; web3: boolean };
  library?: { name?: string; version?: string };
  timezone?: string;
  locale?: string;
  /** Raw User-Agent string (for server-side UA parsing) */
  userAgent?: string;
  /** Client IP (set by server-side enrichment) */
  ip?: string;
}

// ---- Enrichment sub-types ----

export interface GeoData {
  countryCode?: string;
  region?: string;
  city?: string;
  latitude?: number;
  longitude?: number;
  timezone?: string;
}

export interface ParsedUserAgent {
  browser: string;
  browserVersion: string;
  os: string;
  osVersion: string;
  device: string;
  isBot: boolean;
}

export interface EventEnrichment {
  geo?: GeoData;
  parsedUA?: ParsedUserAgent;
  anonymizedIp?: string;
  botProbability?: number;
  pipelineVersion?: string;
  processingDurationMs?: number;
}

export interface EnrichedEvent extends BaseEvent {
  receivedAt: string;
  sentAt?: string;
  enrichment?: EventEnrichment;
  partitionKey?: string;
  /** Timestamp when processing completed */
  processedAt?: string;
}

export interface BatchPayload {
  batch: BaseEvent[];
  sentAt?: string;
  context?: EventContext;
}

// ---- API Key & Auth ----

export interface ApiKeyPermissions {
  write: boolean;
  read: boolean;
  admin: boolean;
  allowedOrigins?: string[];
}

export interface ApiKeyRecord {
  /** Raw API key (only available at creation time) */
  key?: string;
  keyHash: string;
  projectId: string;
  projectName: string;
  organizationId?: string;
  environment?: 'development' | 'staging' | 'production';
  isActive: boolean;
  createdAt: string;
  rateLimits: RateLimitConfig;
  permissions: ApiKeyPermissions;
}

export interface RateLimitConfig {
  eventsPerSecond?: number;
  eventsPerMinute: number;
  batchSizeLimit?: number;
  batchesPerMinute?: number;
  maxBatchSize?: number;
  dailyEventLimit?: number;
}

// ---- Health ----

export interface HealthCheckEntry {
  status: string;
  latencyMs?: number;
  lastCheck?: string;
  message?: string;
}

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  uptime: number;
  version: string;
  timestamp: string;
  checks: Record<string, HealthCheckEntry>;
}

export interface IngestionMetrics {
  eventsReceived: number;
  eventsProcessed: number;
  eventsFailed: number;
  avgLatencyMs: number;
  activeConnections: number;
  startedAt: string;
}

// ---- Sink configuration ----

export interface SinkConfig {
  type: 'kafka' | 's3' | 'clickhouse' | 'redis';
  enabled: boolean;
  config: Record<string, unknown>;
  batchSize?: number;
  flushIntervalMs?: number;
  retryAttempts?: number;
}

// ---- CORS ----

export interface CorsConfig {
  origins: string[];
  methods: string[];
  allowedHeaders: string[];
  maxAge: number;
}

// ---- Processing ----

export interface ProcessingConfig {
  maxBatchSize: number;
  maxEventSizeBytes: number;
  enrichGeo: boolean;
  enrichUA: boolean;
  anonymizeIp: boolean;
  validateSchema: boolean;
  deduplicationWindowMs: number;
  deadLetterEnabled: boolean;
}

// ---- Ingestion config ----

export interface IngestionConfig {
  port: number;
  host: string;
  environment: 'development' | 'staging' | 'production';
  cors: CorsConfig;
  rateLimiting: {
    enabled: boolean;
    windowMs: number;
    maxRequestsPerWindow: number;
    keyGenerator: string;
  };
  processing: ProcessingConfig;
  sinks: SinkConfig[];
  monitoring: {
    metricsEnabled: boolean;
    metricsPort: number;
    healthCheckPath: string;
    tracingEnabled: boolean;
    logLevel: 'debug' | 'info' | 'warn' | 'error';
  };
}

// ---- Error classes ----

export class AetherError extends Error {
  public details?: unknown;

  constructor(message: string, public code: string, public statusCode: number = 500) {
    super(message);
    this.name = 'AetherError';
  }
}

export class ValidationError extends AetherError {
  constructor(message: string, details?: unknown) {
    super(message, 'VALIDATION_ERROR', 400);
    this.name = 'ValidationError';
    this.details = details;
  }
}

export class AuthenticationError extends AetherError {
  constructor(message: string = 'Invalid or missing API key') {
    super(message, 'AUTHENTICATION_ERROR', 401);
    this.name = 'AuthenticationError';
  }
}

export class RateLimitError extends AetherError {
  constructor(public retryAfterMs: number) {
    super('Rate limit exceeded', 'RATE_LIMIT_ERROR', 429);
    this.name = 'RateLimitError';
  }
}

export class PayloadTooLargeError extends AetherError {
  constructor(maxBytes: number) {
    super(`Payload exceeds maximum size of ${maxBytes} bytes`, 'PAYLOAD_TOO_LARGE', 413);
    this.name = 'PayloadTooLargeError';
  }
}
