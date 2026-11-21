/**
 * Login surface.
 *
 * Same look as the public website's sign-in (shared auth portal primitives),
 * but the flow is Kyber's own: there is no form and no client-side crypto.
 * Signing in is a single navigation to `GET /v1/kyber/auth/login`; the backend
 * builds the OIDC request (state, nonce, PKCE verifier all server-side),
 * redirects to the workforce identity provider, receives the callback, and
 * sets the `__Host-kyber_session` cookie. The browser never sees a
 * code_verifier or a token.
 */

import {
  AuthPortalError, AuthPortalNote, AuthPortalPrimaryButton, AuthPortalProviderButton, AuthPortalShell,
} from '@aether/ui';
import { useAuth } from './auth-context';

interface LoginPageProps {
  /** Same-origin path to return to after the backend completes the flow. */
  readonly returnTo?: string | undefined;
}

export function LoginPage({ returnTo }: LoginPageProps = {}) {
  const { login, error, status, refresh } = useAuth();

  return (
    <AuthPortalShell
      brand={<span style={{ fontSize: 20, fontWeight: 500, letterSpacing: '-0.4px' }}>Kyber</span>}
      title="Operator sign-in"
      lead="The Aether command surface. Sign in with your Olympus Labs workforce account."
    >
      {status === 'error' && error !== null && (
        <div data-testid="login-error" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <AuthPortalError>Could not reach the Kyber control plane.</AuthPortalError>
          <AuthPortalNote><span style={{ fontFamily: 'monospace' }}>{error}</span></AuthPortalNote>
          <AuthPortalProviderButton onClick={() => void refresh()}>Retry</AuthPortalProviderButton>
        </div>
      )}

      <AuthPortalPrimaryButton type="button" onClick={() => login(returnTo)} data-testid="login-button">
        Sign in with SSO
      </AuthPortalPrimaryButton>

      <AuthPortalNote>
        Your session is issued and held by the Kyber backend. This browser stores no access token and derives
        no permissions on its own.
      </AuthPortalNote>
    </AuthPortalShell>
  );
}
