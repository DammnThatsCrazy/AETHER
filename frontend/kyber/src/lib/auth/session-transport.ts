/**
 * Kyber session transport — the only sanctioned way to talk to the Kyber
 * control plane from the browser.
 *
 * Design invariants (do not weaken):
 *
 *  1. The browser holds NO token. The session is a server-side
 *     `__Host-kyber_session` HttpOnly cookie that JavaScript cannot read.
 *     Every request therefore sets `credentials: 'include'` and there is no
 *     `Authorization` header anywhere in this app.
 *  2. Mutating requests (anything that is not GET/HEAD/OPTIONS) carry the CSRF
 *     token from the paired, readable cookie in an `X-Kyber-CSRF` header. The
 *     backend rejects the request if it is missing or does not match.
 *  3. A 401 is authoritative and immediate: it means the session is gone. Any
 *     401 broadcasts `kyber:session-expired` on `window` so the auth provider
 *     can flip the whole app to logged-out without waiting for a poll.
 */

import { env, getEnvironment } from '@kyber/lib/env';

/** Readable CSRF cookie paired with the HttpOnly session cookie. */
// Pinned to the single name the backend actually sets
// (services/kyber/sessions/cookies.py::CSRF_COOKIE_NAME). Accepting a
// non-`__Host-` fallback would let a cookie set by a sibling subdomain satisfy
// the CSRF check, which is the precise attack the `__Host-` prefix prevents.
export const CSRF_COOKIE_NAMES = ['__Host-kyber_csrf'] as const;
export const CSRF_HEADER = 'X-Kyber-CSRF';

/** Broadcast when any credentialed call observes a 401. */
export const SESSION_EXPIRED_EVENT = 'kyber:session-expired';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export class KyberAuthError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string = 'kyber_request_failed',
    public readonly detail: string | null = null,
  ) {
    super(message);
    this.name = 'KyberAuthError';
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }
}

/**
 * Resolve the control-plane base URL.
 *
 * Mirrors `lib/api/rest/client.ts`: relative same-origin paths everywhere
 * except an explicitly configured, non-localhost, cross-origin backend. Same
 * origin matters more here than elsewhere — `__Host-` cookies are origin-bound
 * and a cross-origin base silently drops the session.
 */
export function resolveControlPlaneBase(): string {
  const configured = (env.VITE_API_BASE_URL ?? '').trim().replace(/\/$/, '');
  if (env.VITE_KYBER_ENV === 'local') return configured;
  if (!configured) return '';
  if (/\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(configured)) return '';
  try {
    if (typeof window !== 'undefined' && new URL(configured).origin === window.location.origin) {
      return '';
    }
  } catch {
    return '';
  }
  return configured;
}

export function readCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const jar = document.cookie ? document.cookie.split(';') : [];
  for (const raw of jar) {
    const separator = raw.indexOf('=');
    if (separator === -1) continue;
    const name = raw.slice(0, separator).trim();
    if ((CSRF_COOKIE_NAMES as readonly string[]).includes(name)) {
      const value = raw.slice(separator + 1).trim();
      if (value.length > 0) return decodeURIComponent(value);
    }
  }
  return null;
}

function notifySessionExpired(path: string): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: { path } }));
}

export interface CredentialedRequestInit {
  readonly method?: string | undefined;
  readonly body?: unknown;
  readonly signal?: AbortSignal | undefined;
  readonly headers?: Record<string, string> | undefined;
  readonly timeoutMs?: number | undefined;
}

/**
 * Cookie-authenticated fetch. Never attaches a bearer token — there is none.
 */
export async function credentialedFetch(
  path: string,
  init: CredentialedRequestInit = {},
): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase();
  const url = path.startsWith('http') ? path : `${resolveControlPlaneBase()}${path}`;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-Kyber-Environment': getEnvironment(),
    ...init.headers,
  };

  if (init.body !== undefined) headers['Content-Type'] = 'application/json';

  if (!SAFE_METHODS.has(method)) {
    const csrf = readCsrfToken();
    // Send the header even when the cookie is absent so the backend returns a
    // precise CSRF refusal instead of a confusing generic 403.
    headers[CSRF_HEADER] = csrf ?? '';
  }

  const controller = new AbortController();
  const timeoutMs = init.timeoutMs ?? 30_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method,
      headers,
      credentials: 'include',
      body: init.body === undefined ? null : JSON.stringify(init.body),
      signal: init.signal ?? controller.signal,
    });
    if (response.status === 401) notifySessionExpired(path);
    return response;
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new KyberAuthError(`${method} ${path} timed out`, 0, 'kyber_request_timeout');
    }
    throw new KyberAuthError(
      err instanceof Error ? err.message : 'Network error',
      0,
      'kyber_network_error',
    );
  } finally {
    clearTimeout(timer);
  }
}

interface ProblemBody {
  readonly detail?: unknown;
  readonly title?: unknown;
  readonly code?: unknown;
  readonly message?: unknown;
}

async function raiseForStatus(response: Response, path: string): Promise<never> {
  let body: ProblemBody | null = null;
  try {
    body = (await response.json()) as ProblemBody;
  } catch {
    body = null;
  }
  const detail =
    typeof body?.detail === 'string'
      ? body.detail
      : typeof body?.message === 'string'
        ? body.message
        : null;
  const title = typeof body?.title === 'string' ? body.title : null;
  const code = typeof body?.code === 'string' ? body.code : `http_${response.status}`;
  throw new KyberAuthError(
    detail ?? title ?? `${path} failed with status ${response.status}`,
    response.status,
    code,
    detail,
  );
}

/** GET/POST/... returning parsed JSON, raising `KyberAuthError` on non-2xx. */
export async function requestJson<T>(
  path: string,
  parse: (raw: unknown) => T,
  init: CredentialedRequestInit = {},
): Promise<T> {
  const response = await credentialedFetch(path, init);
  if (!response.ok) await raiseForStatus(response, path);
  if (response.status === 204) return parse(null);
  const raw: unknown = await response.json().catch(() => null);
  return parse(raw);
}

/** Fire-and-forget mutation that only cares whether the backend accepted it. */
export async function requestVoid(
  path: string,
  init: CredentialedRequestInit = {},
): Promise<void> {
  const response = await credentialedFetch(path, init);
  if (!response.ok) await raiseForStatus(response, path);
}

export function describeAuthError(err: unknown): string {
  if (err instanceof KyberAuthError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Request failed';
}
