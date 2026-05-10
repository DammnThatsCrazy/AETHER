// =============================================================================
// Aether BACKEND — SHARED TYPE DEFINITIONS
// Server-side mirrors of SDK types + backend-specific extensions
// =============================================================================

// =============================================================================
// EVENT TYPES (matches SDK BaseEvent schema exactly)
// =============================================================================

export type EventType =
  | 'track'
  | 'page'
  | 'screen'
  | 'identify'
  | 'conversion'
  | 'wallet'
  | 'transaction'
  | 'error'
  | 'performance'
  | 'experiment'
  | 'consent'
  | 'heartbeat';

export interface BaseEvent {
  id: string;
  type: EventType;
  timestamp: string;
  sessionId: string;
  anonymousId: string;
  userId?: string;
  event?: string;
  properties?: Record<string, unknown>;
  context: EventContext;
}

export interface EventContext {
  library: { name: string; version: string };
  page?: PageContext;
  device?: DeviceContext;
  campaign?: CampaignContext;
  ip?: string;
  locale?: string;
  timezone?: string;
  userAgent?: string;
  consent?: ConsentState;
}

export interface PageContext {
  url: string;
  path: string;
  title: string;
  referrer: string;
  search: string;
  hash: string;
}

export interface DeviceContext {
  type: 'desktop' | 'mobile' | 'tablet';
  browser: string;
  browserVersion: string;
  os: string;
  osVersion: string;
  screenWidth: number;
  screenHeight: number;
  viewportWidth: number;
  viewportHeight: number;
  pixelRatio: number;
  language: string;
  cookieEnabled: boolean;
  online: boolean;
}

export interface CampaignContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
  clickId?: string;
  referrerDomain?: string;
  referrerType?: 'direct' | 'organic' | 'paid' | 'social' | 'email' | 'referral' | 'unknown';
}

export interface ConsentState {
  analytics: boolean;
  marketing: boolean;
  web3: boolean;
  updatedAt: string;
  policyVersion: string;
}

// =============================================================================
// BATCH PAYLOAD (what the SDK sends to POST /v1/batch)
// =============================================================================

export interface BatchPayload {
  batch: BaseEvent[];
  sentAt: string;
  context?: {
    library: { name: string; version: string };
  };
}

// =============================================================================
// ENRICHED EVENT (event after server-side enrichment pipeline)
// =============================================================================

export interface EnrichedEvent extends BaseEvent {
  /** Optional backend-owned semantic envelope; SDK producers do not emit this. */
  semanticContext?: SemanticContextEnvelope;
  /** Server-assigned receive timestamp */
  receivedAt: string;
  /** Server-assigned processing timestamp */
  processedAt?: string;
  /** Project/workspace ID derived from API key */
  projectId: string;
  /** Enrichment metadata */
  enrichment: EventEnrichment;
  /** Partition key for Kafka/Kinesis */
  partitionKey: string;
}

export interface EventEnrichment {
  /** GeoIP resolved location */
  geo?: GeoData;
  /** Anonymized IP address */
  anonymizedIp?: string;
  /** Normalized user agent */
  parsedUA?: ParsedUserAgent;
  /** Server-detected bot score (0-1) */
  botProbability?: number;
  /** Ingestion pipeline version */
  pipelineVersion: string;
  /** Processing duration in ms */
  processingDurationMs?: number;
}

export interface GeoData {
  country?: string;
  countryCode?: string;
  region?: string;
  city?: string;
  latitude?: number;
  longitude?: number;
  timezone?: string;
  isp?: string;
  asn?: number;
}

export interface ParsedUserAgent {
  browser: string;
  browserVersion: string;
  os: string;
  osVersion: string;
  device: string;
  isBot: boolean;
}


// =============================================================================
// SEMANTIC CONTEXT INTELLIGENCE LAYER (backend-owned, additive)
// =============================================================================

export type SemanticLayer =
  | 'pulse'
  | 'session'
  | 'semantic'
  | 'workflow'
  | 'relational'
  | 'behavioral'
  | 'architectural'
  | 'systemic';

export type SemanticPersistenceClass =
  | 'transient'
  | 'short_ttl'
  | 'medium_ttl'
  | 'long_decaying'
  | 'summarized'
  | 'ephemeral_deep';

export type SemanticRelationshipKind =
  | 'USES'
  | 'MODIFIES'
  | 'INFLUENCES'
  | 'DERIVES_FROM'
  | 'CO_OCCURS_WITH'
  | 'DEPENDS_ON'
  | 'FREQUENTLY_PRECEDES'
  | 'CAUSED_DRIFT_IN'
  | 'SEMANTICALLY_SIMILAR'
  | 'WORKFLOW_PARTNER';

export interface SemanticRelationshipRef {
  kind: SemanticRelationshipKind;
  target_ref: string;
  strength: number;
  confidence: number;
  graph_edge_ref?: string;
  expires_at?: string;
}

export interface SemanticDelta {
  field: string;
  operation: string;
  summary: string;
  confidence: number;
}

export interface SemanticPersistencePolicy {
  class: SemanticPersistenceClass;
  ttl_seconds: number | null;
  decay_rate: number;
  summarize_after_seconds?: number;
  max_relationship_refs: number;
  max_payload_keys: number;
}

export interface SemanticContextEnvelope {
  schema_version: string;
  primary_layer: SemanticLayer;
  layers: SemanticLayer[];
  confidence: number;
  temporal_weight: number;
  recency_score: number;
  stable_hash: string;
  persistence: SemanticPersistencePolicy;
  relationship_refs?: SemanticRelationshipRef[];
  semantic_deltas?: SemanticDelta[];
  compressed_payload?: Record<string, unknown>;
  workflow_refs?: string[];
  episode_refs?: string[];
  enrichment?: Record<string, unknown>;
  vector_ref?: string;
}

// =============================================================================
// API KEY / PROJECT
// =============================================================================

export interface ApiKeyRecord {
  key: string;
  keyHash: string;
  projectId: string;
  projectName: string;
  organizationId: string;
  environment: 'production' | 'staging' | 'development';
  permissions: ApiKeyPermissions;
  rateLimits: RateLimitConfig;
  createdAt: string;
  expiresAt?: string;
  isActive: boolean;
}

export interface ApiKeyPermissions {
  write: boolean;
  read: boolean;
  admin: boolean;
  allowedEventTypes?: EventType[];
  allowedOrigins?: string[];
}

export interface RateLimitConfig {
  eventsPerSecond: number;
  eventsPerMinute: number;
  batchSizeLimit: number;
  dailyEventLimit: number;
}

// =============================================================================
// HEALTH & METRICS
// =============================================================================

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  uptime: number;
  timestamp: string;
  checks: Record<string, ComponentHealth>;
}

export interface ComponentHealth {
  status: 'up' | 'down' | 'degraded';
  latencyMs?: number;
  message?: string;
  lastCheck: string;
}

export interface IngestionMetrics {
  eventsReceived: number;
  eventsProcessed: number;
  eventsFailed: number;
  eventsDropped: number;
  batchesReceived: number;
  avgBatchSize: number;
  avgProcessingMs: number;
  p99ProcessingMs: number;
  activeConnections: number;
  kafkaLag: number;
  errorRate: number;
}

// =============================================================================
// SINK DESTINATIONS
// =============================================================================

export type SinkType = 'kafka' | 'kinesis' | 's3' | 'clickhouse' | 'redis' | 'opensearch' | 'neptune';

export interface SinkConfig {
  type: SinkType;
  enabled: boolean;
  config: Record<string, unknown>;
  batchSize?: number;
  flushIntervalMs?: number;
  retryAttempts?: number;
}

// =============================================================================
// SERVICE CONFIG
// =============================================================================

export interface IngestionConfig {
  port: number;
  host: string;
  environment: 'production' | 'staging' | 'development';
  cors: CorsConfig;
  rateLimiting: GlobalRateLimitConfig;
  processing: ProcessingConfig;
  sinks: SinkConfig[];
  monitoring: MonitoringConfig;
}

export interface CorsConfig {
  origins: string[];
  methods: string[];
  allowedHeaders: string[];
  maxAge: number;
}

export interface GlobalRateLimitConfig {
  enabled: boolean;
  windowMs: number;
  maxRequestsPerWindow: number;
  keyGenerator: 'ip' | 'apiKey' | 'combined';
}

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

export interface MonitoringConfig {
  metricsEnabled: boolean;
  metricsPort: number;
  healthCheckPath: string;
  tracingEnabled: boolean;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
}

// =============================================================================
// ERROR TYPES
// =============================================================================

export class AetherError extends Error {
  constructor(
    message: string,
    public code: string,
    public statusCode: number = 500,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'AetherError';
  }
}

export class ValidationError extends AetherError {
  constructor(message: string, details?: Record<string, unknown>) {
    super(message, 'VALIDATION_ERROR', 400, details);
    this.name = 'ValidationError';
  }
}

export class AuthenticationError extends AetherError {
  constructor(message: string = 'Invalid API key') {
    super(message, 'AUTH_ERROR', 401);
    this.name = 'AuthenticationError';
  }
}

export class RateLimitError extends AetherError {
  constructor(retryAfter: number = 60) {
    super('Rate limit exceeded', 'RATE_LIMIT', 429, { retryAfter });
    this.name = 'RateLimitError';
  }
}

export class PayloadTooLargeError extends AetherError {
  constructor(maxSize: number) {
    super(`Payload exceeds maximum size of ${maxSize} bytes`, 'PAYLOAD_TOO_LARGE', 413, { maxSize });
    this.name = 'PayloadTooLargeError';
  }
}
