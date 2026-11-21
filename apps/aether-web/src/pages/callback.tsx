import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { Button, ErrorState } from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';
import { useAuth, resolveAuthGrant, SignInCodeStep, type AuthGrantResponse } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { readPostAuthDestination } from '@aether-app/features/auth/post-auth-redirect';
import { appHref } from '@aether-app/lib/app-path';

type CodeStep =
  | { readonly kind: 'signup'; readonly email: string | undefined }
  | { readonly kind: 'mfa'; readonly challenge: string };

export function CallbackPage() {
  const { isLoading, isAuthenticated, getAccessTokenSilently, error: auth0Error, logout } = useAuth0();
  const { apiKeyLogin, sessionLogin } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [exchangeError, setExchangeError] = useState<string | null>(null);
  const [codeStep, setCodeStep] = useState<CodeStep | null>(null);
  const tokenRef = useRef<string | null>(null);
  const started = useRef(false);

  const urlError = searchParams.get('error');
  const urlErrorDesc = searchParams.get('error_description');

  // A response either grants a session, or asks for one more code: the code
  // emailed to a first-time sign-up, or the user's two-step verification code.
  const settle = useCallback(async (response: AuthGrantResponse) => {
    if (response.signup_verification_required) {
      setCodeStep({ kind: 'signup', email: response.email });
      return;
    }
    if (response.mfa_required && response.mfa_challenge) {
      setCodeStep({ kind: 'mfa', challenge: response.mfa_challenge });
      return;
    }
    // Trust-plane posture returns a durable session; legacy returns api_key.
    const grant = resolveAuthGrant(response);
    if (grant.kind === 'session') {
      await sessionLogin(grant.session);
    } else {
      await apiKeyLogin(grant.apiKey);
    }
    // Auth0 sign-up/sign-in stored where to land (e.g. billing with the plan
    // chosen on the pricing page); otherwise the tenant home.
    void navigate(readPostAuthDestination(), { replace: true });
  }, [apiKeyLogin, sessionLogin, navigate]);

  useEffect(() => {
    if (urlError || started.current) return;
    if (!isLoading && isAuthenticated) {
      started.current = true;
      getAccessTokenSilently()
        .then(jwt => {
          if (!jwt) {
            throw new Error('Failed to obtain access token');
          }
          tokenRef.current = jwt;
          return api.auth.ssoCallback(jwt);
        })
        .then(settle)
        .catch(err => {
          setExchangeError(err instanceof Error ? err.message : 'Sign-in failed');
        });
    }
  }, [isLoading, isAuthenticated, urlError, getAccessTokenSilently, settle]);

  const backToSignIn = () => {
    // End the Auth0 session too, so "Back to sign in" really starts over.
    void logout({ logoutParams: { returnTo: `${window.location.origin}${appHref('/login')}` } })
      .catch(() => navigate('/login'));
  };

  if (codeStep) {
    return codeStep.kind === 'signup' ? (
      <SignInCodeStep
        kind="signup"
        email={codeStep.email}
        onSubmit={async code => { await settle(await api.auth.ssoCallback(tokenRef.current ?? '', code)); }}
        onResend={async () => { await api.auth.ssoCallback(tokenRef.current ?? ''); }}
        onCancel={backToSignIn}
      />
    ) : (
      <SignInCodeStep
        kind="mfa"
        onSubmit={async code => { await settle(await api.auth.mfaVerify(codeStep.challenge, code)); }}
        onCancel={backToSignIn}
      />
    );
  }

  if (urlError || auth0Error) {
    const msg = urlErrorDesc ?? auth0Error?.message ?? urlError ?? 'Unknown error';
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base px-4">
        <div className="max-w-sm w-full text-center space-y-4">
          <AetherLogo size={32} className="justify-center" />
          <div className="bg-danger/10 border border-danger/30 rounded p-4 text-xs font-mono text-danger">
            <span className="font-medium">Sign-in failed:</span> {msg}
          </div>
          <Button variant="primary" size="sm" onClick={() => void navigate('/login')}>
            Back to login
          </Button>
        </div>
      </div>
    );
  }

  if (exchangeError) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base px-4">
        <div className="max-w-sm w-full text-center space-y-4">
          <AetherLogo size={32} className="justify-center" />
          <ErrorState message={exchangeError ?? 'Sign-in failed'} />
          <Button variant="primary" size="sm" onClick={() => void navigate('/login')}>
            Back to login
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen items-center justify-center bg-surface-base">
      <div className="text-center space-y-2">
        <AetherLogo size={32} className="justify-center" />
        <div className="text-text-secondary text-sm font-mono">Completing sign-in...</div>
      </div>
    </div>
  );
}
