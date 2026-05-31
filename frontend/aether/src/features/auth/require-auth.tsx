import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './auth-context';
import { AetherLogo } from '@aether-app/components/aether-logo';

interface RequireAuthProps {
  readonly children: ReactNode;
  readonly fallback?: ReactNode;
}

export function RequireAuth({ children, fallback }: RequireAuthProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center">
          <AetherLogo size={32} className="justify-center mb-2" />
          <div className="text-text-secondary text-sm">Loading...</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    if (fallback) return <>{fallback}</>;
    return (
      <Navigate
        to={`/login?redirect=${encodeURIComponent(location.pathname)}`}
        replace
      />
    );
  }

  return <>{children}</>;
}
