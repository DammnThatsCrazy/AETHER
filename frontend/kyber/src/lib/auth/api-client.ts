/**
 * Auth-aware fetch wrapper for Kyber.
 *
 * Automatically injects the Auth0 access token as an Authorization: Bearer
 * header on each request. Falls back to no auth header for unauthenticated
 * requests (useful for public API endpoints).
 *
 * Usage:
 *   const client = createAuthApiClient(getAccessToken);
 *   const data = await client.get('/api/v1/something');
 */

export interface AuthApiClientOptions {
  readonly baseUrl?: string | undefined;
  readonly defaultHeaders?: Record<string, string> | undefined;
  readonly timeout?: number | undefined;
}

export interface AuthApiRequestOptions {
  readonly headers?: Record<string, string> | undefined;
  readonly signal?: AbortSignal | undefined;
}

export class AuthApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = 'AuthApiError';
  }
}

/**
 * Factory that creates a fetch-based API client bound to a token getter.
 *
 * @param getToken - async function that returns the current access token,
 *   or null/undefined if not authenticated (e.g. in local development mode).
 */
export function createAuthApiClient(
  getToken: () => Promise<string | null | undefined>,
  options: AuthApiClientOptions = {},
) {
  const { baseUrl = '', defaultHeaders = {}, timeout = 30_000 } = options;

  async function request(
    method: string,
    path: string,
    body?: unknown,
    reqOptions: AuthApiRequestOptions = {},
  ): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    let token: string | null | undefined;
    try {
      token = await getToken();
    } catch {
      // Not authenticated — proceed without a token.
      token = null;
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...defaultHeaders,
      ...reqOptions.headers,
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      const response = await fetch(`${baseUrl}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : null,
        signal: reqOptions.signal ?? controller.signal,
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => undefined) as unknown;
        throw new AuthApiError(
          `${method} ${path} failed with status ${response.status}`,
          response.status,
          errorBody,
        );
      }

      return response;
    } catch (err) {
      if (err instanceof AuthApiError) throw err;
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new AuthApiError(`${method} ${path} timed out`, 0);
      }
      throw new AuthApiError(
        err instanceof Error ? err.message : 'Network error',
        0,
      );
    } finally {
      clearTimeout(timeoutId);
    }
  }

  return {
    get: (path: string, opts?: AuthApiRequestOptions) =>
      request('GET', path, undefined, opts),
    post: (path: string, body?: unknown, opts?: AuthApiRequestOptions) =>
      request('POST', path, body, opts),
    put: (path: string, body?: unknown, opts?: AuthApiRequestOptions) =>
      request('PUT', path, body, opts),
    patch: (path: string, body?: unknown, opts?: AuthApiRequestOptions) =>
      request('PATCH', path, body, opts),
    delete: (path: string, opts?: AuthApiRequestOptions) =>
      request('DELETE', path, undefined, opts),
  };
}
