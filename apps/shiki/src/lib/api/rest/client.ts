import { z } from 'zod';
import { getAccessToken } from '@shiki/features/auth';
import { env, getEnvironment, getRuntimeMode } from '@shiki/lib/env';
import { log } from '@shiki/lib/logging';

export class RestClientError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly correlationId?: string | undefined,
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
  return `shiki-${Date.now()}-${++requestCounter}`;
}

async function request<T>(
  method: string,
  path: string,
  schema: z.ZodType<T>,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  const correlationId = generateCorrelationId();
  const baseUrl = env.VITE_API_BASE_URL;
  const url = `${baseUrl}${path}`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Correlation-ID': correlationId,
    'X-Shiki-Environment': getEnvironment(),
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
      const errorBody = await response.json().catch(() => ({})) as Record<string, unknown>;
      throw new RestClientError(
        String(errorBody['message'] ?? response.statusText),
        response.status,
        String(errorBody['code'] ?? 'UNKNOWN'),
        correlationId,
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
