/**
 * Route guard.
 *
 * ADVISORY: this only decides what to render. Every protected read behind it
 * is separately enforced by the backend against the session cookie.
 */

import type { ReactNode } from 'react';
import { useAuth } from './auth-context';
import { LoginPage } from './login-page';

interface RequireAuthProps {
  readonly children: ReactNode;
  readonly fallback?: ReactNode;
}

export function RequireAuth({ children, fallback }: RequireAuthProps) {
  const { isAuthenticated, isLoading, status } = useAuth();

  if (isLoading || status === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center">
          <div className="kyber-glyph text-2xl text-accent mb-2">[ KYBER ]</div>
          <div className="text-text-secondary text-sm">Checking session…</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return fallback ? <>{fallback}</> : <LoginPage />;
  }

  return <>{children}</>;
}
