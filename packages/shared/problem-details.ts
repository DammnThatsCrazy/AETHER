// =============================================================================
// Aether Shared — Canonical API Error Contract (RFC 7807-compatible)
// The backend emits this shape from every JSON failure path (AetherError
// handlers and middleware early-exits). `parseProblemDetails` also tolerates
// the two legacy shapes so clients keep working against older backends.
// =============================================================================

export interface ProblemDetails {
  /** URI identifying the error category (stable identifier, may not resolve). */
  type: string;
  /** Short human-readable title of the error category. */
  title: string;
  /** HTTP status code. */
  status: number;
  /** Stable machine-readable UPPER_SNAKE code. */
  code: string;
  /** Human-readable explanation of this occurrence. */
  detail: string;
  /** Legacy alias of `detail` kept for older clients. */
  message?: string;
  request_id?: string;
  correlation_id?: string;
  /** Whether retrying the same request may succeed. */
  retryable?: boolean;
  /** Optional field-level errors. */
  errors?: unknown[];
  /** Problem-Details extensions (retry_after_seconds, upgrade_url, ...). */
  [extension: string]: unknown;
}

interface LegacyNestedError {
  error: {
    code?: number | string;
    message?: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

const httpTitle = (status: number): string => {
  const titles: Record<number, string> = {
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    409: 'Conflict',
    413: 'Payload Too Large',
    422: 'Unprocessable Entity',
    429: 'Rate Limit Exceeded',
    500: 'Internal Server Error',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
  };
  return titles[status] ?? 'Request Failed';
};

const RETRYABLE_STATUSES = new Set([429, 500, 502, 503, 504]);

export function isProblemDetails(body: unknown): body is ProblemDetails {
  if (typeof body !== 'object' || body === null) return false;
  const candidate = body as Record<string, unknown>;
  return (
    typeof candidate.type === 'string' &&
    typeof candidate.title === 'string' &&
    typeof candidate.status === 'number' &&
    typeof candidate.code === 'string' &&
    typeof candidate.detail === 'string'
  );
}

/**
 * Parse any backend error body into the canonical shape.
 * Accepts: canonical Problem Details, the legacy nested `{error: {...}}`
 * envelope, the legacy flat `{error: 'slug', message}` shape, plain strings,
 * and unknown bodies (synthesized from the HTTP fallback).
 */
export function parseProblemDetails(
  body: unknown,
  fallback?: { status?: number; statusText?: string },
): ProblemDetails {
  const status = fallback?.status ?? 0;

  if (isProblemDetails(body)) {
    return { message: body.detail, ...body };
  }

  if (typeof body === 'object' && body !== null) {
    const candidate = body as Record<string, unknown> & Partial<LegacyNestedError>;

    // Legacy nested: { error: { code, message, details, request_id } }
    if (typeof candidate.error === 'object' && candidate.error !== null) {
      const nested = candidate.error as LegacyNestedError['error'];
      const nestedStatus =
        typeof nested.code === 'number' ? nested.code : status || 500;
      const detail =
        typeof nested.message === 'string' ? nested.message : httpTitle(nestedStatus);
      return {
        type: 'about:blank',
        title: httpTitle(nestedStatus),
        status: nestedStatus,
        code:
          typeof nested.code === 'string'
            ? nested.code
            : httpTitle(nestedStatus).toUpperCase().replace(/ /g, '_'),
        detail,
        message: detail,
        request_id: nested.request_id,
        correlation_id: nested.request_id,
        retryable: RETRYABLE_STATUSES.has(nestedStatus),
        errors: nested.details ? [nested.details] : undefined,
      };
    }

    // Legacy flat: { error: 'rate_limit_exceeded', message, request_id, ...ext }
    if (typeof candidate.error === 'string') {
      const flatStatus = status || 500;
      const detail =
        typeof candidate.message === 'string' ? candidate.message : candidate.error;
      const { error: slug, message: _message, ...extensions } = candidate;
      return {
        type: 'about:blank',
        title: httpTitle(flatStatus),
        status: flatStatus,
        code: String(slug).toUpperCase(),
        detail,
        message: detail,
        request_id:
          typeof candidate.request_id === 'string' ? candidate.request_id : undefined,
        retryable: RETRYABLE_STATUSES.has(flatStatus),
        ...extensions,
      };
    }

    // Object with a top-level message but no canonical members.
    if (typeof candidate.message === 'string') {
      const objStatus = status || 500;
      return {
        type: 'about:blank',
        title: httpTitle(objStatus),
        status: objStatus,
        code: httpTitle(objStatus).toUpperCase().replace(/ /g, '_'),
        detail: candidate.message,
        message: candidate.message,
        retryable: RETRYABLE_STATUSES.has(objStatus),
      };
    }
  }

  if (typeof body === 'string' && body.length > 0) {
    const strStatus = status || 500;
    return {
      type: 'about:blank',
      title: httpTitle(strStatus),
      status: strStatus,
      code: httpTitle(strStatus).toUpperCase().replace(/ /g, '_'),
      detail: body,
      message: body,
      retryable: RETRYABLE_STATUSES.has(strStatus),
    };
  }

  const synthStatus = status || 0;
  const detail = fallback?.statusText || 'Request failed';
  return {
    type: 'about:blank',
    title: httpTitle(synthStatus),
    status: synthStatus,
    code: synthStatus
      ? httpTitle(synthStatus).toUpperCase().replace(/ /g, '_')
      : 'UNKNOWN',
    detail,
    message: detail,
    retryable: RETRYABLE_STATUSES.has(synthStatus),
  };
}
