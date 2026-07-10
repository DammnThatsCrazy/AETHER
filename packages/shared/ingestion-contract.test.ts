import { describe, expect, it } from 'vitest';
import {
  FORBIDDEN_SDK_INGESTION_ROUTES,
  INGESTION_BATCH_MAX_EVENTS,
  INGESTION_BATCH_MIN_EVENTS,
  INGESTION_ENDPOINT,
  INGESTION_IDEMPOTENCY_KEY_FIELDS,
  INGESTION_SCHEMA_VERSION,
} from './ingestion-contract';
import { SDK_INGESTION_PATH } from './sdk-version';
import { CONTRACT_SCHEMA_VERSION } from './schema-version';

describe('ingestion-contract', () => {
  it('pins the canonical ingestion endpoint to /v1/batch', () => {
    expect(INGESTION_ENDPOINT).toBe('/v1/batch');
    expect(INGESTION_ENDPOINT).toBe(SDK_INGESTION_PATH);
  });

  it('forbids server-only ingestion routes for SDK transports', () => {
    expect(FORBIDDEN_SDK_INGESTION_ROUTES).toContain('/v1/ingest/events');
    expect(FORBIDDEN_SDK_INGESTION_ROUTES).not.toContain(INGESTION_ENDPOINT);
  });

  it('declares the backend idempotency key composition in order', () => {
    expect([...INGESTION_IDEMPOTENCY_KEY_FIELDS]).toEqual([
      'tenant_id',
      'event_id',
      'schema_version',
    ]);
  });

  it('tracks the shared contract schema version', () => {
    expect(INGESTION_SCHEMA_VERSION).toBe(CONTRACT_SCHEMA_VERSION);
  });

  it('bounds batch sizes to the backend BatchRequest constraints', () => {
    expect(INGESTION_BATCH_MIN_EVENTS).toBe(1);
    expect(INGESTION_BATCH_MAX_EVENTS).toBe(500);
    expect(INGESTION_BATCH_MIN_EVENTS).toBeLessThan(INGESTION_BATCH_MAX_EVENTS);
  });
});
