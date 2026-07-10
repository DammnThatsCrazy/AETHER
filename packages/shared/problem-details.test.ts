import { describe, expect, it } from 'vitest';
import { isProblemDetails, parseProblemDetails } from './problem-details';

describe('problem-details', () => {
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
    expect(parsed.message).toBe('Campaign not found');
    expect(parsed.correlation_id).toBe('req-1');
  });

  it('normalizes the legacy nested error envelope', () => {
    const parsed = parseProblemDetails(
      {
        error: {
          code: 403,
          message: 'Forbidden',
          details: { reason: 'plan' },
          request_id: 'req-2',
        },
      },
      { status: 403 },
    );
    expect(parsed.status).toBe(403);
    expect(parsed.title).toBe('Forbidden');
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
    expect(parsed.detail).toContain('Burst rate limit');
  });

  it('handles string bodies', () => {
    const parsed = parseProblemDetails('upstream exploded', { status: 502 });
    expect(parsed.detail).toBe('upstream exploded');
    expect(parsed.status).toBe(502);
    expect(parsed.retryable).toBe(true);
  });

  it('synthesizes from the HTTP fallback for unknown bodies', () => {
    const parsed = parseProblemDetails(null, {
      status: 503,
      statusText: 'Service Unavailable',
    });
    expect(parsed.code).toBe('SERVICE_UNAVAILABLE');
    expect(parsed.detail).toBe('Service Unavailable');
    expect(parsed.retryable).toBe(true);
  });

  it('treats plain message objects as details', () => {
    const parsed = parseProblemDetails({ message: 'nope' }, { status: 400 });
    expect(parsed.detail).toBe('nope');
    expect(parsed.status).toBe(400);
    expect(parsed.retryable).toBe(false);
  });
});
