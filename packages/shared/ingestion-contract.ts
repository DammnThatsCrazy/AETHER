// =============================================================================
// Aether SDK — Ingestion Contract (canonical source of truth)
// The single place that pins WHERE SDKs send events and WHAT the backend
// guarantees about acceptance. Mirrors
// `Backend Architecture/aether-backend/services/ingestion/batch.py` and is
// validated against it by `scripts/validate_sdk_contracts.py`.
// =============================================================================

import type { BaseEvent, BatchPayload, LibraryContext } from './events';
import type { ConsentPurpose, ConsentState } from './consent';
import { CONTRACT_SCHEMA_VERSION } from './schema-version';
import { SDK_INGESTION_PATH } from './sdk-version';

/** The one ingestion endpoint every SDK transport MUST target (alias of SDK_INGESTION_PATH). */
export const INGESTION_ENDPOINT: '/v1/batch' = SDK_INGESTION_PATH;

/**
 * Server-only ingestion routes SDKs must never call directly.
 * `/v1/ingest/events` is the deprecated legacy route; `/v1/events/ingest`
 * is the internal replay path.
 */
export const FORBIDDEN_SDK_INGESTION_ROUTES = [
  '/v1/ingest/events',
  '/v1/events/ingest',
] as const;

/**
 * Components of the backend's tenant-scoped idempotency key, in order:
 * sha256(`${tenantId}:${eventId}:${schemaVersion}`) truncated to 40 hex chars.
 * Retrying the same event id within a batch window is a safe no-op.
 */
export const INGESTION_IDEMPOTENCY_KEY_FIELDS = [
  'tenant_id',
  'event_id',
  'schema_version',
] as const;

/** Schema version stamped on the idempotency key; tracks the event contract. */
export const INGESTION_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION;

/** Hard batch-size bounds enforced by the backend BatchRequest model. */
export const INGESTION_BATCH_MIN_EVENTS = 1 as const;
export const INGESTION_BATCH_MAX_EVENTS = 500 as const;

/** Per-event acceptance status returned by POST /v1/batch. */
export type IngestEventResultStatus = 'accepted' | 'duplicate' | 'rejected';

export interface IngestEventResult {
  id: string;
  status: IngestEventResultStatus;
  reason?: string;
}

/** Response envelope of POST /v1/batch (backend BatchResponse). */
export interface BatchIngestResponse {
  accepted: number;
  duplicates: number;
  rejected: number;
  events: IngestEventResult[];
  batchId: string;
  receivedAt: string;
}

/** Request envelope of POST /v1/batch (alias of the SDK BatchPayload). */
export type BatchIngestRequest = BatchPayload;

export type {
  BaseEvent,
  BatchPayload,
  LibraryContext,
  ConsentPurpose,
  ConsentState,
};
