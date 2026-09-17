/**
 * FPS-115 — Error Fixture
 * Verifies provider error fixture validation.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { providerErrorFixture } from '@aether/proof-fixtures';

describe('FPS-115: Error Fixture', () => {
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
    expect(props.attemptedAt).toBe('2024-09-11T13:25:00.000Z');
  });

  it('should validate provider error has typed error shape', () => {
    const envelope = providerErrorFixture as unknown as EventEnvelope;
    expect(envelope.event_type).toBe('payment_failed');
    const props = envelope.properties as Record<string, unknown> | undefined;
    expect(props?.errorCode).toBe('RATE_LIMIT_EXCEEDED');
    expect(props?.errorMessage).toBe('Too many requests');
    expect(props?.provider).toBe('stripe');
    expect(props?.providerStatusCode).toBe(429);
  });

  it('should validate error properties degrade gracefully', () => {
    const envelope = providerErrorFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBeDefined();
    expect(envelope.workspace_id).toBeDefined();
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_provider_err_001');
    expect(envelope.identity.user_id).toBe('user_010');
  });
});
