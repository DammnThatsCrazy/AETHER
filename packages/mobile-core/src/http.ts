/**
 * Transport abstraction for the mobile SDK.
 *
 * The SDK depends on a minimal `FetchLike` and an `AuthProvider` rather than a
 * concrete HTTP library, so the host app supplies the platform's networking and
 * secure-storage-backed token source. Nothing here reads or logs a raw token.
 */

/** The subset of the WHATWG fetch Response the SDK consumes. */
export interface FetchResponseLike {
  status: number;
  json(): Promise<unknown>;
  text(): Promise<string>;
}

export interface FetchRequestInit {
  method: string;
  headers: Record<string, string>;
  body?: string;
}

export type FetchLike = (url: string, init: FetchRequestInit) => Promise<FetchResponseLike>;

/** Supplies the current access token (from platform secure storage). */
export interface AuthProvider {
  /** Return a bearer token, or null when unauthenticated. Never logged by the SDK. */
  getAccessToken(): Promise<string | null>;
}

/** Raised for any non-2xx response. Carries the parsed body when available. */
export class MobileApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = 'MobileApiError';
    this.status = status;
    this.body = body;
  }
}

/** The backend wraps successful payloads in `{ data: ... }` (APIResponse). */
interface ApiEnvelope<T> {
  data: T;
}

function isEnvelope<T>(value: unknown): value is ApiEnvelope<T> {
  return typeof value === 'object' && value !== null && 'data' in value;
}

export interface HttpClientDeps {
  fetch: FetchLike;
  auth: AuthProvider;
}

/** Thin JSON-over-HTTP helper that unwraps the APIResponse envelope. */
export class HttpClient {
  constructor(private readonly baseUrl: string, private readonly deps: HttpClientDeps) {}

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = await this.deps.auth.getAccessToken();
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (token) {
      headers.authorization = `Bearer ${token}`;
    }
    const res = await this.deps.fetch(this.baseUrl + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let payload: unknown;
    try {
      payload = await res.json();
    } catch {
      payload = undefined;
    }
    if (res.status < 200 || res.status >= 300) {
      throw new MobileApiError(res.status, `${method} ${path} -> HTTP ${res.status}`, payload);
    }
    // Endpoints under /v1/mobile and /v1/continuations return `{ data: ... }`.
    return (isEnvelope<T>(payload) ? payload.data : (payload as T));
  }
}
