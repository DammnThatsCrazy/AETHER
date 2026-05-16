import type { ReactNode } from 'react';
import { useAuth } from './auth-context';

interface RequireAuthProps {
  readonly children: ReactNode;
  readonly fallback?: ReactNode;
}

export function RequireAuth({ children, fallback }: RequireAuthProps) {
  const { isAuthenticated, isLoading, login } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center">
          <div className="font-mono text-2xl text-accent mb-2">[ AETHER ]</div>
          <div className="text-text-secondary text-sm">Loading...</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    if (fallback) return <>{fallback}</>;
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center space-y-4">
          <div className="font-mono text-2xl text-accent">[ AETHER ]</div>
          <p className="text-text-secondary text-sm">Sign in to continue</p>
          <button
            type="button"
            onClick={() => void login()}
            className="px-4 py-2 bg-accent text-white rounded text-sm font-medium hover:bg-accent-hover transition-colors"
          >
            Sign in
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
