/**
 * Legacy `/callback` route.
 *
 * The OIDC callback is now handled entirely by the backend at
 * `GET /v1/kyber/auth/callback`, which exchanges the code and sets the
 * `__Host-kyber_session` cookie before redirecting. Nothing is exchanged in
 * the browser any more — this component only exists because the router still
 * references it, and it simply re-reads the session and moves on.
 *
 * The integrator owns `router.tsx`; once this route is dropped there, delete
 * this file.
 */

import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@kyber/features/auth';

export function CallbackPage() {
  const { isLoading, isAuthenticated, error, refresh } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      void navigate('/', { replace: true });
    }
  }, [isLoading, isAuthenticated, navigate]);

  return (
    <div className="flex h-screen items-center justify-center bg-surface-base">
      <div className="text-center space-y-2">
        <div className="kyber-glyph text-2xl text-accent">[ KYBER ]</div>
        {error !== null ? (
          <p className="text-danger text-sm">Authentication error: {error}</p>
        ) : (
          <div className="text-text-secondary text-sm">Completing sign-in…</div>
        )}
      </div>
    </div>
  );
}
