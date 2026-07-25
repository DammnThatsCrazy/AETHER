/**
 * Login surface.
 *
 * There is no form and no client-side crypto here. Signing in is a single
 * navigation to `GET /v1/kyber/auth/login`; the backend builds the OIDC
 * request (state, nonce, PKCE verifier all server-side), redirects to Google,
 * receives the callback, and sets the `__Host-kyber_session` cookie. The
 * browser never sees a code_verifier or a token.
 */

import { Button } from '@aether/ui';
import { useAuth } from './auth-context';

interface LoginPageProps {
  /** Same-origin path to return to after the backend completes the flow. */
  readonly returnTo?: string | undefined;
}

export function LoginPage({ returnTo }: LoginPageProps = {}) {
  const { login, error, status, refresh } = useAuth();

  return (
    <div className="flex h-screen items-center justify-center bg-surface-base">
      <div className="w-full max-w-md space-y-6 p-8">
        <div className="text-center">
          <div className="font-mono text-3xl font-bold text-text-primary mb-1">KYBER</div>
          <div className="text-text-secondary text-sm">Aether Command Surface</div>
        </div>

        {status === 'error' && error !== null && (
          <div
            role="alert"
            className="kyber-card border-danger/50 text-danger text-sm space-y-2"
            data-testid="login-error"
          >
            <p>Could not reach the Kyber control plane.</p>
            <p className="font-mono text-xs opacity-80">{error}</p>
            <Button variant="secondary" size="sm" onClick={() => void refresh()}>
              Retry
            </Button>
          </div>
        )}

        <Button
          className="w-full"
          size="lg"
          onClick={() => login(returnTo)}
          data-testid="login-button"
        >
          Sign in with Google
        </Button>

        <p className="text-center text-[11px] leading-relaxed text-text-muted">
          Your session is issued and held by the Kyber backend. This browser
          stores no access token and derives no permissions on its own.
        </p>
      </div>
    </div>
  );
}
