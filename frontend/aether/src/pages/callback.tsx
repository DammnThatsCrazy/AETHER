import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { Button, ErrorState } from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';
import { useAuth, resolveAuthGrant } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';

export function CallbackPage() {
  const { isLoading, isAuthenticated, getAccessTokenSilently, error: auth0Error } = useAuth0();
  const { apiKeyLogin, sessionLogin } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [exchangeError, setExchangeError] = useState<string | null>(null);

  const urlError = searchParams.get('error');
  const urlErrorDesc = searchParams.get('error_description');

  useEffect(() => {
    if (urlError) return;
    if (!isLoading && isAuthenticated) {
      getAccessTokenSilently()
        .then(jwt => api.auth.ssoCallback(jwt))
        .then(async response => {
          // Trust-plane posture returns a durable session; legacy returns api_key.
          const grant = resolveAuthGrant(response);
          if (grant.kind === 'session') {
            await sessionLogin(grant.session);
          } else {
            await apiKeyLogin(grant.apiKey);
          }
          void navigate('/settings', { replace: true });
        })
        .catch(err => {
          setExchangeError(err instanceof Error ? err.message : 'Sign-in failed');
        });
    }
  }, [isLoading, isAuthenticated, navigate, urlError, getAccessTokenSilently, apiKeyLogin, sessionLogin]);

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
