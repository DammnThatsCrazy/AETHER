import type { ProblemDetails } from '@aether/ui';

/** The part of `RestClientError` this reads; matched by shape so auth does not import the REST client. */
interface RateLimitedLike {
  readonly status: number;
  readonly problem?: ProblemDetails | undefined;
}

function isRateLimited(error: unknown): error is RateLimitedLike {
  return (
    typeof error === 'object' &&
    error !== null &&
    'status' in error &&
    (error as { status: unknown }).status === 429
  );
}

/**
 * The public email/password endpoints answer 429 once a client or an address has
 * used its attempts. The wait is carried either as a top-level Problem-Details
 * extension or, from the backend's canonical error body, in `errors[0]`.
 * Returns `null` when the error is not a 429, and `0` when it carries no wait.
 */
export function retryAfterSeconds(error: unknown): number | null {
  if (!isRateLimited(error)) return null;
  const problem = error.problem;
  const extension = problem?.retry_after_seconds;
  const nested = (problem?.errors?.[0] as { retry_after_seconds?: unknown } | undefined)
    ?.retry_after_seconds;
  const seconds = typeof extension === 'number' ? extension : nested;
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0
    ? Math.ceil(seconds)
    : 0;
}

/** A readable message for a rate-limited auth request, or `null` for any other error. */
export function describeAuthRateLimit(error: unknown): string | null {
  const seconds = retryAfterSeconds(error);
  if (seconds === null) return null;
  if (seconds === 0) return 'Too many attempts. Wait a few minutes and try again.';
  if (seconds < 90) return `Too many attempts. Try again in ${seconds} seconds.`;
  return `Too many attempts. Try again in about ${Math.ceil(seconds / 60)} minutes.`;
}
