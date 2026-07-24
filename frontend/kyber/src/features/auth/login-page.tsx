import { useAuth } from './auth-context';

export function LoginPage() {
  const { login, error } = useAuth();

  return (
    <div className="flex h-screen items-center justify-center bg-surface-base">
      <div className="w-full max-w-md space-y-6 p-8">
        <div className="text-center">
          <div className="font-mono text-3xl font-bold text-text-primary mb-1">KYBER</div>
          <div className="text-text-secondary text-sm">Aether Command Surface</div>
        </div>

        {error && (
          <div className="kyber-card border-danger/50 text-danger text-sm">{error}</div>
        )}

        <button
          onClick={() => void login()}
          className="w-full rounded-md bg-accent px-4 py-3 text-text-inverse font-medium hover:bg-accent-hover transition-colors"
        >
          Sign in with SSO
        </button>
      </div>
    </div>
  );
}
