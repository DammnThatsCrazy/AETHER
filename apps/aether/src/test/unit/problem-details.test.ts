import { describe, expect, it } from 'vitest';
import { isProblemDetails, parseProblemDetails } from '@aether/ui';

describe('problem-details parser', () => {
  it('passes through a canonical Problem Details body', () => {
    const body = {
      type: 'https://errors.aether.dev/not-found',
      title: 'Not Found',
      status: 404,
      code: 'NOT_FOUND',
      detail: 'Campaign not found',
      request_id: 'req-1',
      correlation_id: 'req-1',
      retryable: false,
    };
    expect(isProblemDetails(body)).toBe(true);
    const parsed = parseProblemDetails(body, { status: 404 });
    expect(parsed.code).toBe('NOT_FOUND');
    expect(parsed.detail).toBe('Campaign not found');
    expect(parsed.correlation_id).toBe('req-1');
  });

  it('normalizes the legacy nested error envelope', () => {
    const parsed = parseProblemDetails(
      { error: { code: 403, message: 'Forbidden', details: { reason: 'plan' }, request_id: 'req-2' } },
      { status: 403 },
    );
    expect(parsed.status).toBe(403);
    expect(parsed.detail).toBe('Forbidden');
    expect(parsed.request_id).toBe('req-2');
    expect(parsed.retryable).toBe(false);
    expect(parsed.errors).toEqual([{ reason: 'plan' }]);
  });

  it('normalizes the legacy flat slug shape with extensions', () => {
    const parsed = parseProblemDetails(
      {
        error: 'rate_limit_exceeded',
        message: 'Burst rate limit exceeded. Limit: 60 RPM.',
        retry_after_seconds: 30,
        request_id: 'req-3',
      },
      { status: 429 },
    );
    expect(parsed.code).toBe('RATE_LIMIT_EXCEEDED');
    expect(parsed.status).toBe(429);
    expect(parsed.retryable).toBe(true);
    expect(parsed.retry_after_seconds).toBe(30);
  });

  it('handles string bodies and synthesizes from the HTTP fallback', () => {
    expect(parseProblemDetails('upstream exploded', { status: 502 }).detail).toBe('upstream exploded');
    const synth = parseProblemDetails(null, { status: 503, statusText: 'Service Unavailable' });
    expect(synth.code).toBe('SERVICE_UNAVAILABLE');
    expect(synth.retryable).toBe(true);
  });
});
