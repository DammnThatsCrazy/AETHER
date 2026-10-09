import { describe, expect, it } from 'vitest';
import { describeAuthRateLimit, retryAfterSeconds } from './rate-limit';

function limited(problem: Record<string, unknown> | undefined, status = 429) {
  return Object.assign(new Error('Rate limit exceeded'), { status, problem });
}

describe('auth rate-limit messages', () => {
  it('reads the wait from the backend canonical error body', () => {
    const error = limited({ errors: [{ retry_after_seconds: 600 }] });
    expect(retryAfterSeconds(error)).toBe(600);
    expect(describeAuthRateLimit(error)).toBe('Too many attempts. Try again in about 10 minutes.');
  });

  it('reads a top-level Problem-Details extension and rounds partial minutes up', () => {
    expect(retryAfterSeconds(limited({ retry_after_seconds: 61 }))).toBe(61);
    expect(describeAuthRateLimit(limited({ retry_after_seconds: 61 }))).toBe(
      'Too many attempts. Try again in 61 seconds.',
    );
    expect(describeAuthRateLimit(limited({ retry_after_seconds: 130 }))).toBe(
      'Too many attempts. Try again in about 3 minutes.',
    );
  });

  it('still says to wait when a 429 carries no usable wait', () => {
    expect(describeAuthRateLimit(limited(undefined))).toBe(
      'Too many attempts. Wait a few minutes and try again.',
    );
    expect(describeAuthRateLimit(limited({ retry_after_seconds: 'soon' }))).toBe(
      'Too many attempts. Wait a few minutes and try again.',
    );
  });

  it('ignores every other error', () => {
    expect(describeAuthRateLimit(limited({ retry_after_seconds: 30 }, 400))).toBeNull();
    expect(describeAuthRateLimit(new Error('network'))).toBeNull();
    expect(describeAuthRateLimit(null)).toBeNull();
    expect(describeAuthRateLimit('429')).toBeNull();
  });
});
