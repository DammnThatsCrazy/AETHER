/**
 * Event schema validation.
 * Validates BatchPayload and individual BaseEvent against the expected schema.
 */

import type { BatchPayload, BaseEvent, EventType } from '@aether/common';
import { ValidationError } from '@aether/common';

const VALID_EVENT_TYPES: Set<EventType> = new Set([
  'track',
  'page',
  'screen',
  'identify',
  'conversion',
  'wallet',
  'transaction',
  'error',
  'performance',
  'experiment',
  'consent',
  'heartbeat',
]);

const MAX_BATCH_SIZE = 500;

/**
 * Validate the top-level batch payload structure.
 * Ensures the payload is an object with a `batch` array and `sentAt` string.
 */
export function validateBatchPayload(payload: unknown): BatchPayload {
  if (!payload || typeof payload !== 'object') {
    throw new ValidationError('Batch payload must be a JSON object', {
      received: typeof payload,
    });
  }

  const obj = payload as Record<string, unknown>;

  // Validate batch array
  if (!Array.isArray(obj.batch)) {
    throw new ValidationError('Batch payload must contain a "batch" array', {
      received: typeof obj.batch,
    });
  }

  if (obj.batch.length === 0) {
    throw new ValidationError('Batch array must contain at least one event', {
      batchLength: 0,
    });
  }

  if (obj.batch.length > MAX_BATCH_SIZE) {
    throw new ValidationError(
      `Batch size exceeds maximum of ${MAX_BATCH_SIZE} events`,
      {
        batchLength: obj.batch.length,
        maxBatchSize: MAX_BATCH_SIZE,
      },
    );
  }

  // Validate sentAt
  if (typeof obj.sentAt !== 'string' || obj.sentAt.length === 0) {
    throw new ValidationError('Batch payload must contain a "sentAt" ISO timestamp string', {
      received: typeof obj.sentAt,
    });
  }

  // Validate sentAt is a parseable date
  const sentAtDate = Date.parse(obj.sentAt);
  if (isNaN(sentAtDate)) {
    throw new ValidationError('"sentAt" must be a valid ISO 8601 timestamp', {
      received: obj.sentAt,
    });
  }

  return payload as BatchPayload;
}

/**
 * Validate a single event within a batch.
 * Ensures all required fields are present and correctly typed.
 */
export function validateEvent(event: unknown, index: number): BaseEvent {
  if (!event || typeof event !== 'object') {
    throw new ValidationError(`Event at index ${index} must be a JSON object`, {
      index,
      received: typeof event,
    });
  }

  const obj = event as Record<string, unknown>;

  // Validate id (string, non-empty)
  if (typeof obj.id !== 'string' || obj.id.length === 0) {
    throw new ValidationError(`Event at index ${index}: "id" must be a non-empty string`, {
      index,
      field: 'id',
      received: typeof obj.id,
    });
  }

  // Validate type (must be a valid EventType)
  if (typeof obj.type !== 'string' || !VALID_EVENT_TYPES.has(obj.type as EventType)) {
    throw new ValidationError(
      `Event at index ${index}: "type" must be one of: ${Array.from(VALID_EVENT_TYPES).join(', ')}`,
      {
        index,
        field: 'type',
        received: obj.type,
        validTypes: Array.from(VALID_EVENT_TYPES),
      },
    );
  }

  // Validate timestamp (ISO string)
  if (typeof obj.timestamp !== 'string' || obj.timestamp.length === 0) {
    throw new ValidationError(
      `Event at index ${index}: "timestamp" must be a non-empty ISO 8601 string`,
      {
        index,
        field: 'timestamp',
        received: typeof obj.timestamp,
      },
    );
  }

  const tsDate = Date.parse(obj.timestamp);
  if (isNaN(tsDate)) {
    throw new ValidationError(
      `Event at index ${index}: "timestamp" must be a valid ISO 8601 timestamp`,
      {
        index,
        field: 'timestamp',
        received: obj.timestamp,
      },
    );
  }

  // Validate sessionId (string, non-empty)
  if (typeof obj.sessionId !== 'string' || obj.sessionId.length === 0) {
    throw new ValidationError(
      `Event at index ${index}: "sessionId" must be a non-empty string`,
      {
        index,
        field: 'sessionId',
        received: typeof obj.sessionId,
      },
    );
  }

  // Validate anonymousId (string, non-empty)
  if (typeof obj.anonymousId !== 'string' || obj.anonymousId.length === 0) {
    throw new ValidationError(
      `Event at index ${index}: "anonymousId" must be a non-empty string`,
      {
        index,
        field: 'anonymousId',
        received: typeof obj.anonymousId,
      },
    );
  }

  // Validate context (object with library)
  if (!obj.context || typeof obj.context !== 'object') {
    throw new ValidationError(
      `Event at index ${index}: "context" must be an object`,
      {
        index,
        field: 'context',
        received: typeof obj.context,
      },
    );
  }

  const context = obj.context as Record<string, unknown>;

  if (!context.library || typeof context.library !== 'object') {
    throw new ValidationError(
      `Event at index ${index}: "context.library" must be an object with name and version`,
      {
        index,
        field: 'context.library',
        received: typeof context.library,
      },
    );
  }

  const library = context.library as Record<string, unknown>;

  if (typeof library.name !== 'string' || library.name.length === 0) {
    throw new ValidationError(
      `Event at index ${index}: "context.library.name" must be a non-empty string`,
      {
        index,
        field: 'context.library.name',
        received: typeof library.name,
      },
    );
  }

  if (typeof library.version !== 'string' || library.version.length === 0) {
    throw new ValidationError(
      `Event at index ${index}: "context.library.version" must be a non-empty string`,
      {
        index,
        field: 'context.library.version',
        received: typeof library.version,
      },
    );
  }

  // Optional field validation
  if (obj.userId !== undefined && typeof obj.userId !== 'string') {
    throw new ValidationError(
      `Event at index ${index}: "userId" must be a string if provided`,
      {
        index,
        field: 'userId',
        received: typeof obj.userId,
      },
    );
  }

  if (obj.event !== undefined && typeof obj.event !== 'string') {
    throw new ValidationError(
      `Event at index ${index}: "event" must be a string if provided`,
      {
        index,
        field: 'event',
        received: typeof obj.event,
      },
    );
  }

  if (obj.properties !== undefined && (typeof obj.properties !== 'object' || obj.properties === null)) {
    throw new ValidationError(
      `Event at index ${index}: "properties" must be an object if provided`,
      {
        index,
        field: 'properties',
        received: typeof obj.properties,
      },
    );
  }

  return event as BaseEvent;
}
