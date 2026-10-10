/**
 * Auth-grant resolution for the trust-plane session migration.
 *
 * The backend's human auth endpoints (/v1/auth/login, /v1/auth/verify-email,
 * /v1/auth/sso/callback) return one of two shapes:
 *
 *  - Trust-plane posture (HUMAN_SESSIONS_ENABLED on the backend): a durable,
 *    revocable `session` — `{ session_id, token: "sess_...", idle_expires_at,
 *    absolute_expires_at }`. The token is a server-tracked session credential,
 *    NOT a reusable API key, and is accepted via `Authorization: Bearer`.
 *  - Legacy posture (flag off): a reusable `api_key` ("ak_...").
 *
 * The frontend is shape-driven: it prefers the session grant whenever the
 * backend provides one and only falls back to the legacy API-key grant when
 * the trust-plane flag is off, so neither posture breaks the login flow.
 */
import type { AuthGrantResponse, HumanSessionGrant } from '@aether-app/lib/api/endpoints';

export type { AuthGrantResponse, HumanSessionGrant };

export type ResolvedAuthGrant =
  | { readonly kind: 'session'; readonly session: HumanSessionGrant }
  | { readonly kind: 'api_key'; readonly apiKey: string };

/**
 * Resolve a login/verify/SSO response into the credential the app should use.
 * Session grants win over legacy keys; a response with neither is an error.
 */
export function resolveAuthGrant(grant: AuthGrantResponse): ResolvedAuthGrant {
  if (grant.session?.token) {
    return { kind: 'session', session: grant.session };
  }
  if (grant.api_key) {
    return { kind: 'api_key', apiKey: grant.api_key };
  }
  throw new Error('Auth response contained neither a session nor an api_key');
}
