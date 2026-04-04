import type { ReactNode } from 'react';
import { useAuth } from './auth-context';
import { LoginPage } from './login-page';

interface RequireAuthProps {
  readonly children: ReactNode;
  readonly fallback?: ReactNode;
}

export function RequireAuth({ children, fallback }: RequireAuthProps) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center">
          <div className="shiki-glyph text-2xl text-accent mb-2">[ SHIKI ]</div>
          <div className="text-text-secondary text-sm">Authenticating...</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return fallback ? <>{fallback}</> : <LoginPage />;
  }

  return <>{children}</>;
}
