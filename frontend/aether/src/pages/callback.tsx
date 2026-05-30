import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { Button, ErrorState } from '@aether/ui';
import { isLocalMocked } from '@aether-app/lib/env';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';

export function CallbackPage() {
  const { isLoading, isAuthenticated, getAccessTokenSilently, error: auth0Error } = useAuth0();
  const { apiKeyLogin } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [exchangeError, setExchangeError] = useState<string | null>(null);

  const urlError = searchParams.get('error');
  const urlErrorDesc = searchParams.get('error_description');

  useEffect(() => {
    if (isLocalMocked()) {
      void navigate('/settings', { replace: true });
      return;
    }
    if (urlError) return;
    if (!isLoading && isAuthenticated) {
      getAccessTokenSilently()
        .then(jwt => api.auth.ssoCallback(jwt))
        .then(({ api_key }) => {
          apiKeyLogin(api_key);
          void navigate('/settings', { replace: true });
        })
        .catch(err => {
          setExchangeError(err instanceof Error ? err.message : 'Sign-in failed');
        });
    }
  }, [isLoading, isAuthenticated, navigate, urlError, getAccessTokenSilently, apiKeyLogin]);

  if (urlError || auth0Error) {
    const msg = urlErrorDesc ?? auth0Error?.message ?? urlError ?? 'Unknown error';
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base px-4">
        <div className="max-w-sm w-full text-center space-y-4">
          <div className="font-mono text-2xl text-accent">[ AETHER ]</div>
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
          <div className="font-mono text-2xl text-accent">[ AETHER ]</div>
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
        <div className="font-mono text-2xl text-accent">[ AETHER ]</div>
        <div className="text-text-secondary text-sm font-mono">Completing sign-in...</div>
      </div>
    </div>
  );
}
