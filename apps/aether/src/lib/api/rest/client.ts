import { z } from 'zod';
import { getAccessToken } from '@aether-app/features/auth';
import { env, getEnvironment } from '@aether-app/lib/env';
import { log } from '@aether-app/lib/logging';

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
  return `aether-${Date.now()}-${++requestCounter}`;
}

async function request<T>(
  method: string,
  path: string,
  schema: z.ZodType<T>,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  const correlationId = generateCorrelationId();
  const startTime = performance.now();
  const url = path;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Correlation-ID': correlationId,
    'X-Aether-Environment': getEnvironment(),
    ...options?.headers,
  };

  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeout = options?.timeout ?? 30000;
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null,
      signal: options?.signal ?? controller.signal,
    });

    const duration = Math.round(performance.now() - startTime);

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({})) as Record<string, unknown>;
      log.warn(`[REST] ${method} ${path} -> ${response.status} (${duration}ms)`, { correlationId });
      throw new RestClientError(
        String(errorBody['message'] ?? response.statusText),
        response.status,
        String(errorBody['code'] ?? 'UNKNOWN'),
        correlationId,
      );
    }

    log.info(`[REST] ${method} ${path} -> ${response.status} (${duration}ms)`, { correlationId });

    const json: unknown = await response.json();
    const parsed = schema.safeParse(json);

    if (!parsed.success) {
      log.error(`[REST] Schema validation failed for ${path}`, { issues: parsed.error.issues, correlationId });
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

// Re-export env for convenience
export { env };
