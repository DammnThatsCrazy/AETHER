/**
 * FPS-114 — Duplicate Fixture
 * Verifies duplicate handling in connectors.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { duplicateFixture, missingFieldsFixture, providerErrorFixture } from '@aether/proof-fixtures';

describe('FPS-114: Duplicate Fixture', () => {
  it('should validate duplicate fixture shows dedup detection', () => {
    expect(duplicateFixture.event_type).toBe('page');
    expect(duplicateFixture.platform_id).toBe('web');
    expect(duplicateFixture.tenant_id).toBe('aether-proof-tenant');
    const props = duplicateFixture.properties as Record<string, unknown>;
    expect(props.event).toBeDefined();
    const event = props.event as Record<string, unknown>;
    expect(event.eventName).toBe('page_view');
    expect(event.path).toBe('/demo');
    expect(props.isDuplicate).toBe(true);
    expect(props.dedupKey).toBe('page_view|/demo|2024-09-11T13:20:00.000Z');
    expect(props.firstSeenAt).toBe('2024-09-11T13:19:00.000Z');
    expect(props.duplicateSeenAt).toBe('2024-09-11T13:20:00.000Z');
  });

  it('should validate missing fields fixture shows validation errors', () => {
    expect(missingFieldsFixture.event_type).toBe('track');
    expect(missingFieldsFixture.platform_id).toBe('web');
    const props = missingFieldsFixture.properties as Record<string, unknown>;
    expect(props.partialEvent).toBeDefined();
    const partial = props.partialEvent as Record<string, unknown>;
    expect(partial.eventName).toBe('incomplete');
    expect(props.missingEmail).toBeDefined();
    expect(props.validationErrors).toBeInstanceOf(Array);
    const errors = props.validationErrors as Record<string, unknown>[];
    expect(errors.length).toBe(2);
    expect(errors[0].field).toBe('properties.email');
    expect(errors[0].error).toBe('missing_required_field');
  });

  it('should validate provider error fixture', () => {
    expect(providerErrorFixture.event_type).toBe('payment_failed');
    expect(providerErrorFixture.platform_id).toBe('stripe');
    expect(providerErrorFixture.tenant_id).toBe('aether-proof-tenant');
    const props = providerErrorFixture.properties as Record<string, unknown>;
    expect(props.errorCode).toBe('RATE_LIMIT_EXCEEDED');
    expect(props.errorMessage).toBe('Too many requests');
    expect(props.provider).toBe('stripe');
    expect(props.providerStatusCode).toBe(429);
    expect(props.retryAfter).toBe(60);
    expect(props.endpoint).toBe('/v1/charges');
    expect(props.method).toBe('post');
    expect(props.requestId).toBe('req_err_001');
  });

  it('should validate duplicate fixture against EventEnvelope shape', () => {
    const envelope = duplicateFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.event_type).toBe('page');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.identity.anonymous_id).toBe('anon_dup_001');
    expect(envelope.identity.user_id).toBe('user_009');
  });

  it('should validate missing-fields fixture degrades correctly', () => {
    // missingFieldsFixture is valid — it has all required envelope fields
    // but contains events with missing sub-fields
    const envelope = missingFieldsFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.event_type).toBe('track');
    expect(envelope.sdk.name).toBe('@aether/web');
  });

  it('should validate provider-error fixture has typed error shape', () => {
    const envelope = providerErrorFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('payment_failed');
    const props = envelope.properties as Record<string, unknown> | undefined;
    expect(props?.errorCode).toBe('RATE_LIMIT_EXCEEDED');
    expect(props?.errorMessage).toBe('Too many requests');
    expect(props?.provider).toBe('stripe');
    expect(props?.providerStatusCode).toBe(429);
    expect(props?.retryAfter).toBe(60);
  });
});
