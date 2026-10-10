// =============================================================================
// Client-side parser for the canonical Problem-Details error contract.
//
// The `ProblemDetails` TYPE is canonical in `@aether/shared` (mirrors the
// backend `shared/common/common.py`). The runtime parser lives here because
// `@aether/ui` is the ESM, source-consumed frontend library both apps bundle;
// `@aether/shared` compiles to CommonJS and its runtime values are not
// resolvable by the app rollup builds (only its types are).
// =============================================================================

import type { ProblemDetails } from '@aether/shared';

export type { ProblemDetails };

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
        retryable: RETRYABLE_STATUSES.has(nestedStatus),
        ...(nested.request_id !== undefined
          ? { request_id: nested.request_id, correlation_id: nested.request_id }
          : {}),
        ...(nested.details ? { errors: [nested.details] } : {}),
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
        retryable: RETRYABLE_STATUSES.has(flatStatus),
        ...(typeof candidate.request_id === 'string'
          ? { request_id: candidate.request_id }
          : {}),
        ...extensions,
      };
    }

    // Object with a top-level message but no canonical members. Honor a
    // server-provided `code`/`status`/`request_id` when present; otherwise
    // fall back to the HTTP status and an UNKNOWN code.
    if (typeof candidate.message === 'string') {
      const objStatus =
        typeof candidate.status === 'number' ? candidate.status : status || 500;
      return {
        type: 'about:blank',
        title: httpTitle(objStatus),
        status: objStatus,
        code:
          typeof candidate.code === 'string' ? candidate.code : 'UNKNOWN',
        detail: candidate.message,
        message: candidate.message,
        retryable: RETRYABLE_STATUSES.has(objStatus),
        ...(typeof candidate.request_id === 'string'
          ? { request_id: candidate.request_id }
          : {}),
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
