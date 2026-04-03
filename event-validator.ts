// =============================================================================
// AETHER INGESTION — EVENT VALIDATION
// Schema validation, size enforcement, consent filtering, PII masking
// =============================================================================

import type { BaseEvent, EventType } from './WebSDKTypes(CoreTypeDefinitions)';

// Stub types for server-side constructs not in the client SDK types
interface BatchPayload {
  batch: BaseEvent[];
  sentAt: string;
  context?: { library?: { name: string; version: string } };
}

interface ProcessingConfig {
  maxBatchSize: number;
  maxEventSizeBytes: number;
}

class ValidationError extends Error {
  public details?: Record<string, unknown>;
  constructor(message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = 'ValidationError';
    this.details = details;
  }
}

// Stub logger (replaces @aether/logger)
const logger = {
  warn: (msg: string, meta?: Record<string, unknown>) => console.warn('[aether.ingestion.validator]', msg, meta),
  info: (msg: string, meta?: Record<string, unknown>) => console.info('[aether.ingestion.validator]', msg, meta),
  error: (msg: string, meta?: Record<string, unknown>) => console.error('[aether.ingestion.validator]', msg, meta),
};

const VALID_EVENT_TYPES: Set<EventType> = new Set([
  'track', 'page', 'screen', 'identify', 'conversion',
  'wallet', 'transaction', 'error', 'performance',
  'experiment', 'consent', 'heartbeat',
]);

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_TIMESTAMP_REGEX = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

// Sensitive field patterns for PII masking
const SENSITIVE_PATTERNS: RegExp[] = [
  /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/g,  // Credit cards
  /\b\d{3}-\d{2}-\d{4}\b/g,                          // SSN
  /\bpassword\s*[:=]\s*\S+/gi,                        // Passwords in strings
];

export interface ValidationResult {
  valid: BaseEvent[];
  invalid: Array<{ event: unknown; errors: string[] }>;
  filtered: number; // Consent-filtered count
}

export class EventValidator {
  constructor(private config: ProcessingConfig) {}

  /** Validate a full batch payload */
  validateBatch(payload: unknown): BatchPayload {
    if (!payload || typeof payload !== 'object') {
      throw new ValidationError('Invalid payload: expected JSON object');
    }

    const p = payload as Record<string, unknown>;

    if (!Array.isArray(p.batch)) {
      throw new ValidationError('Invalid payload: "batch" must be an array');
    }

    if (p.batch.length === 0) {
      throw new ValidationError('Empty batch');
    }

    if (p.batch.length > this.config.maxBatchSize) {
      throw new ValidationError(
        `Batch size ${p.batch.length} exceeds maximum of ${this.config.maxBatchSize}`,
        { batchSize: p.batch.length, maxBatchSize: this.config.maxBatchSize },
      );
    }

    return {
      batch: p.batch as BaseEvent[],
      sentAt: typeof p.sentAt === 'string' ? p.sentAt : new Date().toISOString(),
      context: p.context as BatchPayload['context'],
    };
  }

  /** Validate and filter individual events */
  validateEvents(events: BaseEvent[]): ValidationResult {
    const valid: BaseEvent[] = [];
    const invalid: Array<{ event: unknown; errors: string[] }> = [];
    let filtered = 0;

    for (const event of events) {
      const errors = this.validateEvent(event);

      if (errors.length > 0) {
        invalid.push({ event, errors });
        continue;
      }

      // Consent filtering
      if (event.context?.consent && !this.isConsentGranted(event)) {
        filtered++;
        continue;
      }

      // PII masking
      const masked = this.maskPII(event);

      // Size check
      const size = Buffer.byteLength(JSON.stringify(masked), 'utf8');
      if (size > this.config.maxEventSizeBytes) {
        invalid.push({ event: masked, errors: [`Event size ${size} bytes exceeds limit of ${this.config.maxEventSizeBytes}`] });
        continue;
      }

      valid.push(masked);
    }

    if (invalid.length > 0) {
      logger.warn('Validation rejected events', { invalidCount: invalid.length, reasons: invalid.slice(0, 5).map(i => i.errors) });
    }

    return { valid, invalid, filtered };
  }

  /** Validate a single event */
  private validateEvent(event: unknown): string[] {
    const errors: string[] = [];

    if (!event || typeof event !== 'object') {
      return ['Event must be an object'];
    }

    const e = event as Record<string, unknown>;

    // Required fields
    if (!e.id || typeof e.id !== 'string') {
      errors.push('Missing or invalid "id"');
    } else if (e.id.length > 128) {
      errors.push('"id" exceeds 128 characters');
    }

    if (!e.type || typeof e.type !== 'string') {
      errors.push('Missing or invalid "type"');
    } else if (!VALID_EVENT_TYPES.has(e.type as EventType)) {
      errors.push(`Invalid event type: "${e.type}"`);
    }

    if (!e.timestamp || typeof e.timestamp !== 'string') {
      errors.push('Missing or invalid "timestamp"');
    } else if (!ISO_TIMESTAMP_REGEX.test(e.timestamp)) {
      errors.push('Invalid timestamp format (expected ISO 8601)');
    } else {
      // Reject timestamps too far in the past or future
      const ts = new Date(e.timestamp).getTime();
      const now = Date.now();
      if (ts < now - 7 * 86400_000) errors.push('Timestamp is more than 7 days in the past');
      if (ts > now + 300_000) errors.push('Timestamp is more than 5 minutes in the future');
    }

    if (!e.sessionId || typeof e.sessionId !== 'string') {
      errors.push('Missing or invalid "sessionId"');
    }

    if (!e.anonymousId || typeof e.anonymousId !== 'string') {
      errors.push('Missing or invalid "anonymousId"');
    }

    // Properties must be an object if present
    if (e.properties !== undefined && (typeof e.properties !== 'object' || Array.isArray(e.properties))) {
      errors.push('"properties" must be a plain object');
    }

    // Context must be an object if present
    if (e.context !== undefined && (typeof e.context !== 'object' || Array.isArray(e.context))) {
      errors.push('"context" must be a plain object');
    }

    return errors;
  }

  /** Check if consent allows this event type */
  private isConsentGranted(event: BaseEvent): boolean {
    const consent = event.context?.consent;
    if (!consent) return true; // No consent info = allow (pre-consent state)

    // Consent events always pass through
    if (event.type === 'consent') return true;

    // Analytics consent
    if (['track', 'page', 'screen', 'performance', 'heartbeat', 'error', 'identify'].includes(event.type)) {
      return consent.analytics;
    }

    // Marketing consent
    if (['conversion', 'experiment'].includes(event.type)) {
      return consent.marketing;
    }

    // Web3 consent
    if (['wallet', 'transaction'].includes(event.type)) {
      return consent.web3;
    }

    return true;
  }

  /** Mask PII in event properties */
  private maskPII(event: BaseEvent): BaseEvent {
    if (!event.properties) return event;

    const masked = { ...event, properties: { ...event.properties } };

    for (const [key, value] of Object.entries(masked.properties)) {
      if (typeof value !== 'string') continue;

      let maskedValue = value;
      for (const pattern of SENSITIVE_PATTERNS) {
        maskedValue = maskedValue.replace(pattern, '[REDACTED]');
      }
      if (maskedValue !== value) {
        masked.properties[key] = maskedValue;
      }
    }

    return masked;
  }
}
