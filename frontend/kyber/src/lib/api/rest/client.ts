import { z } from 'zod';
import { parseProblemDetails, type ProblemDetails } from '@aether/ui';
import { getAccessToken } from '@kyber/features/auth';
import { env, getEnvironment, getRuntimeMode } from '@kyber/lib/env';
import { log } from '@kyber/lib/logging';

export class RestClientError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly correlationId?: string | undefined,
    public readonly retryable: boolean = false,
    public readonly problem?: ProblemDetails | undefined,
  ) {
    super(message);
    this.name = 'RestClientError';
  }
}

interface RequestOptions {
  readonly headers?: Record<string, string> | undefined;
  readonly signal?: AbortSignal | undefined;
  readonly timeout?: number | undefined;
}

let requestCounter = 0;

function generateCorrelationId(): string {
  return `kyber-${Date.now()}-${++requestCounter}`;
}

/**
 * Resolve the REST base URL for the current runtime/environment.
 *
 * - Mocked mode: relative (MSW intercepts).
 * - local-live: the dev server and backend are different origins with no proxy,
 *   so use the explicit absolute base (defaults to http://localhost:8000).
 * - staging/production: the nginx image proxies /v1 same-origin, and its CSP is
 *   `connect-src 'self'`. Keep relative paths so hosted calls stay same-origin
 *   (no CSP/CORS breakage, and never fall back to the operator's localhost when
 *   VITE_API_BASE_URL is unset). Only go absolute when an explicit base that is
 *   neither localhost nor the page origin is configured — an opt-in cross-origin
 *   backend whose CSP/CORS the operator is expected to allow.
 */
function resolveApiBaseUrl(): string {
  if (getRuntimeMode() !== 'live') return '';
  const configured = (env.VITE_API_BASE_URL ?? '').trim().replace(/\/$/, '');
  if (env.VITE_KYBER_ENV === 'local-live') return configured;
  if (!configured) return '';
  if (/\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(configured)) return '';
  try {
    if (typeof window !== 'undefined' && new URL(configured).origin === window.location.origin) return '';
  } catch {
    return '';
  }
  return configured;
}

async function request<T>(
  method: string,
  path: string,
  schema: z.ZodType<T>,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  const correlationId = generateCorrelationId();
  const baseUrl = resolveApiBaseUrl();
  const url = path.startsWith('http') ? path : `${baseUrl}${path}`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Correlation-ID': correlationId,
    'X-Kyber-Environment': getEnvironment(),
    ...options?.headers,
  };

  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeout = options?.timeout ?? 30000;
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  const startTime = performance.now();

  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null,
      signal: options?.signal ?? controller.signal,
    });

    const duration = Math.round(performance.now() - startTime);
    log.info(`[REST] ${method} ${path} -> ${response.status} (${duration}ms)`, { correlationId });

    if (!response.ok) {
      const errorBody: unknown = await response.json().catch(() => null);
      const problem = parseProblemDetails(errorBody, {
        status: response.status,
        statusText: response.statusText,
      });
      throw new RestClientError(
        problem.detail || problem.title || response.statusText,
        response.status,
        problem.code,
        problem.correlation_id ??
          response.headers?.get('X-Correlation-ID') ??
          correlationId,
        problem.retryable ?? false,
        problem,
      );
    }

    const json: unknown = await response.json();
    const parsed = schema.safeParse(json);

    if (!parsed.success) {
      log.error(`[REST] Schema validation failed for ${path}`, {
        correlationId,
        errors: parsed.error.issues,
      });
      throw new RestClientError(
        `Response validation failed: ${parsed.error.issues.map(i => i.message).join(', ')}`,
        response.status,
        'VALIDATION_ERROR',
        correlationId,
      );
    }

    return parsed.data;
  } catch (err) {
    if (err instanceof RestClientError) throw err;
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new RestClientError('Request timed out', 0, 'TIMEOUT', correlationId);
    }
    throw new RestClientError(
      err instanceof Error ? err.message : 'Network error',
      0,
      'NETWORK_ERROR',
      correlationId,
    );
  } finally {
    clearTimeout(timeoutId);
  }
}

export const restClient = {
  get: <T>(path: string, schema: z.ZodType<T>, options?: RequestOptions) =>
    request('GET', path, schema, undefined, options),
  post: <T>(path: string, schema: z.ZodType<T>, body?: unknown, options?: RequestOptions) =>
    request('POST', path, schema, body, options),
  put: <T>(path: string, schema: z.ZodType<T>, body?: unknown, options?: RequestOptions) =>
    request('PUT', path, schema, body, options),
  patch: <T>(path: string, schema: z.ZodType<T>, body?: unknown, options?: RequestOptions) =>
    request('PATCH', path, schema, body, options),
  delete: <T>(path: string, schema: z.ZodType<T>, options?: RequestOptions) =>
    request('DELETE', path, schema, undefined, options),
};
