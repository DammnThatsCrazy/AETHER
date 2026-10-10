import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './auth-context';
import { AetherLogo } from '@aether-app/components/aether-logo';

interface RequireAuthProps {
  readonly children: ReactNode;
  readonly fallback?: ReactNode;
}

/**
 * The post-auth destination for an anonymous tenant hitting a guarded deep
 * link: the FULL location (pathname + search + hash), never just the pathname.
 * A connect-intent deep link such as
 * `/settings/integrations?family=google_ads&intent=connect` (WS-5 public→app
 * handoff) or `/activate?experience=advertising_campaigns&intent=connect`
 * (WS-3 activation) must survive the sign-in bounce intact, or the visitor
 * lands back on a bare page with the intent gone.
 */
export function postAuthDestination(location: {
  pathname: string;
  search: string;
  hash: string;
}): string {
  return location.pathname + location.search + location.hash;
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
        to={`/login?redirect=${encodeURIComponent(postAuthDestination(location))}`}
        replace
      />
    );
  }

  return <>{children}</>;
}
