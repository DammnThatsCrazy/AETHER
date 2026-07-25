/**
 * Kyber session API surface.
 *
 * There is no token exchange here and no PKCE. Login is a full-page navigation
 * to a backend endpoint that issues the redirect to the identity provider; the
 * backend owns `state`, `nonce` and the PKCE verifier and never hands any of
 * them to the browser. The browser's entire role is "follow the redirect".
 */

import { KYBER_AUTH_ENDPOINTS, requestJson, requestVoid, resolveControlPlaneBase } from '@kyber/lib/auth';
import type { KyberPrincipalView, KyberSessionView, WebAuthnAssertionOptions } from '@kyber/types';
import { parseAssertionOptions, parsePrincipal, parseSession } from './schemas';

export async function fetchPrincipal(signal?: AbortSignal): Promise<KyberPrincipalView> {
  return requestJson(KYBER_AUTH_ENDPOINTS.me, parsePrincipal, { signal });
}

export async function fetchSession(signal?: AbortSignal): Promise<KyberSessionView> {
  return requestJson(KYBER_AUTH_ENDPOINTS.session, parseSession, { signal });
}

/**
 * Build the login URL. `return_to` is a *path*, never an absolute URL, so a
 * crafted link cannot turn the backend into an open redirector.
 */
export function buildLoginUrl(returnTo?: string): string {
  const base = resolveControlPlaneBase();
  const path = KYBER_AUTH_ENDPOINTS.login;
  const safeReturn = sanitiseReturnTo(returnTo);
  if (safeReturn === null) return `${base}${path}`;
  return `${base}${path}?return_to=${encodeURIComponent(safeReturn)}`;
}

export function sanitiseReturnTo(returnTo: string | undefined): string | null {
  if (!returnTo) return null;
  // Only same-origin absolute paths. Reject '//evil.com' and any scheme.
  if (!returnTo.startsWith('/') || returnTo.startsWith('//')) return null;
  return returnTo;
}

/** Full-page navigation into the backend-driven OIDC flow. */
export function startLogin(returnTo?: string): void {
  if (typeof window === 'undefined') return;
  window.location.assign(buildLoginUrl(returnTo));
}

export async function endSession(): Promise<void> {
  await requestVoid(KYBER_AUTH_ENDPOINTS.logout, { method: 'POST' });
}

export async function requestStepUpOptions(): Promise<WebAuthnAssertionOptions> {
  return requestJson(KYBER_AUTH_ENDPOINTS.stepUpOptions, parseAssertionOptions, {
    method: 'POST',
    body: {},
  });
}

export interface StepUpAssertionPayload {
  readonly credential_id: string;
  readonly client_data_json: string;
  readonly authenticator_data: string;
  readonly signature: string;
  readonly user_handle: string | null;
}

export async function verifyStepUp(payload: StepUpAssertionPayload): Promise<KyberSessionView> {
  return requestJson(KYBER_AUTH_ENDPOINTS.stepUpVerify, parseSession, {
    method: 'POST',
    body: payload,
  });
}
