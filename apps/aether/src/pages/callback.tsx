/**
 * Auth0 callback handler page for Aether.
 *
 * Auth0 redirects here after login (VITE_AUTH0_REDIRECT_URI=/callback).
 * The Auth0Provider processes the code exchange automatically.
 * Once isLoading is false and isAuthenticated is true, we navigate home.
 */
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { isLocalMocked } from '@aether-app/lib/env';

export function CallbackPage() {
  const { isLoading, isAuthenticated, error } = useAuth0();
  const navigate = useNavigate();

  useEffect(() => {
    if (isLocalMocked()) {
      // Local-mocked mode: Auth0 is not wired — go home immediately.
      void navigate('/', { replace: true });
      return;
    }
    if (!isLoading && isAuthenticated) {
      void navigate('/', { replace: true });
    }
  }, [isLoading, isAuthenticated, navigate]);

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center space-y-2">
          <div className="font-mono text-2xl text-accent">[ AETHER ]</div>
          <p className="text-red-500 text-sm">Authentication error: {error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen items-center justify-center bg-surface-base">
      <div className="text-center space-y-2">
        <div className="font-mono text-2xl text-accent">[ AETHER ]</div>
        <div className="text-text-secondary text-sm">Completing sign-in...</div>
      </div>
    </div>
  );
}
