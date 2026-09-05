/**
 * Public → private authentication handoff for the Aether marketing shell.
 *
 * Tenant sessions and credentials are scoped to the Aether application origin
 * (app.olympuslabs.com). This module is the ONLY place a public page may build
 * an application-origin handoff URL. The public marketing origin never stores
 * tenant credentials — no cookie, token, api key, PKCE verifier, or client-side
 * storage write belongs anywhere in this workspace.
 *
 * The authentication threshold pages collect a workspace email (and, at
 * signup, a name) and hand the values to the real Aether application sign-in /
 * sign-up pages as prefill query parameters. The threshold never claims to
 * have signed a user in, and it never sends a password-reset email — recovery
 * is reached from the application origin too.
 */
import { AETHER_APP_URL } from '@aether-marketing/lib/env';

export { AETHER_APP_URL };

/** Public→private sign-in handoff path on the Aether application origin. */
export const APP_LOGIN_PATH = '/login';

/** Public→private sign-up handoff path on the Aether application origin. */
export const APP_SIGNUP_PATH = '/signup';

/** Optional prefill carried to the application forms. Empty and absent values
 * are dropped, so a handoff never ends in a bare `?`. */
export interface AppHandoffParams {
  readonly [key: string]: string | undefined;
}

/** Joins the application origin with `path` and appends only non-empty prefill
 * parameters. This is the single construction point for application-origin
 * URLs from public marketing pages. */
export function buildAppHandoffUrl(path: string, params: AppHandoffParams): string {
  const origin = AETHER_APP_URL.replace(/\/$/, '');
  const base = `${origin}${path.startsWith('/') ? path : `/${path}`}`;

  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') {
      query.set(key, value);
    }
  }
  const encoded = query.toString();

  return encoded.length === 0 ? base : `${base}?${encoded}`;
}

/** Shared honest labels for the public threshold forms. */
export const EMAIL_LABEL = 'Work email';
export const NAME_LABEL = 'Your name';
