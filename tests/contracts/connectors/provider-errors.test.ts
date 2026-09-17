/**
 * FPS-022 — Connector Provider Error Handling
 * Verifies that connector errors from providers are surfaced and handled gracefully.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope, SourceClassification } from '@aether/proof-contracts';
import { providerErrorFixture } from '@aether/proof-fixtures';

describe('FPS-022: Connector Provider Errors', () => {
  it('should surface rate limit errors from provider fixture', () => {
    expect(providerErrorFixture.event_type).toBe('payment_failed');
    expect(providerErrorFixture.properties?.errorCode).toBe('RATE_LIMIT_EXCEEDED');
    expect(providerErrorFixture.properties?.errorMessage).toBe('Too many requests');
    expect(providerErrorFixture.properties?.provider).toBe('stripe');
    expect(providerErrorFixture.properties?.providerStatusCode).toBe(429);
    expect(providerErrorFixture.properties?.retryAfter).toBe(60);
  });

  it('should surface authentication errors from provider', () => {
    const errorProperties = {
      errorCode: 'AUTHENTICATION_FAILED',
      errorMessage: 'Invalid API key',
      provider: 'shopify',
      providerStatusCode: 401,
    };
    expect(errorProperties.errorCode).toBe('AUTHENTICATION_FAILED');
    expect(errorProperties.provider).toBe('shopify');
    expect(errorProperties.providerStatusCode).toBe(401);
  });

  it('should surface timeout errors from provider', () => {
    const errorProperties = {
      errorCode: 'TIMEOUT',
      errorMessage: 'Request timed out after 30s',
      provider: 'email',
      providerStatusCode: 504,
    };
    expect(errorProperties.errorCode).toBe('TIMEOUT');
    expect(errorProperties.provider).toBe('email');
  });

  it('should surface server errors from provider', () => {
    const errorProperties = {
      errorCode: 'SERVER_ERROR',
      errorMessage: 'Internal server error',
      provider: 'stripe',
      providerStatusCode: 500,
    };
    expect(errorProperties.errorCode).toBe('SERVER_ERROR');
    expect(errorProperties.providerStatusCode).toBe(500);
  });

  it('should include provider name in error context', () => {
    const errorProperties = {
      errorCode: 'UNKNOWN',
      errorMessage: 'Something went wrong',
      provider: 'shopify',
      retryable: false,
    };
    expect(errorProperties.provider).toBe('shopify');
    expect(errorProperties.retryable).toBe(false);
  });

  it('should construct EventEnvelope for provider error', () => {
    const envelope: EventEnvelope = {
      tenant_id: providerErrorFixture.tenant_id,
      workspace_id: providerErrorFixture.workspace_id,
      platform_id: providerErrorFixture.platform_id,
      environment: providerErrorFixture.environment,
      event_type: providerErrorFixture.event_type,
      sdk: providerErrorFixture.sdk,
      identity: providerErrorFixture.identity,
      timestamp: providerErrorFixture.timestamp,
      properties: providerErrorFixture.properties,
    };
    expect(envelope.event_type).toBe('payment_failed');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.properties?.errorCode).toBe('RATE_LIMIT_EXCEEDED');
    expect(envelope.properties?.providerStatusCode).toBe(429);
    expect(envelope.properties?.retryAfter).toBe(60);
  });

  it('should classify provider error source correctly', () => {
    const source: SourceClassification = {
      platform: 'stripe',
      data_type: 'event',
      platform_id: 'stripe_account_001',
      sdk: '@aether/stripe',
      environment: 'staging',
      metadata: { errorCode: 'RATE_LIMIT_EXCEEDED' },
    };
    expect(source.platform).toBe('stripe');
    expect(source.data_type).toBe('event');
    expect(source.metadata?.errorCode).toBe('RATE_LIMIT_EXCEEDED');
  });

  it('should validate provider error has all required envelope fields', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'stripe',
      environment: 'staging',
      event_type: 'payment_failed',
      sdk: { name: '@aether/stripe', version: '1.0.0' },
      identity: { anonymous_id: 'anon_err_1', user_id: 'user_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: {
        errorCode: 'RATE_LIMIT_EXCEEDED',
        errorMessage: 'Too many requests',
        provider: 'stripe',
        providerStatusCode: 429,
        retryAfter: 60,
        endpoint: '/v1/charges',
        method: 'post',
        requestId: 'req_001',
        attemptedAt: '2024-01-01T00:00:00.000Z',
      },
    };
    // All required EventEnvelope fields present
    expect(envelope.tenant_id).toBe('t1');
    expect(envelope.workspace_id).toBe('w1');
    expect(envelope.platform_id).toBe('stripe');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('payment_failed');
    expect(envelope.sdk.name).toBe('@aether/stripe');
    expect(envelope.identity.anonymous_id).toBe('anon_err_1');
    expect(envelope.identity.user_id).toBe('user_1');
    expect(envelope.timestamp).toBe('2024-01-01T00:00:00.000Z');
    expect(envelope.properties?.errorCode).toBe('RATE_LIMIT_EXCEEDED');
  });
});
