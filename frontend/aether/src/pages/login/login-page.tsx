import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, SocialProviderIcon } from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';
import type { SocialProvider } from '@aether/ui';
import { useAuth, resolveAuthGrant } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { env } from '@aether-app/lib/env';

type SsoState = 'idle' | 'loading';

const SSO_PROVIDERS: Array<{ provider: SocialProvider; label: string }> = [
  { provider: 'google', label: 'Continue with Google' },
  { provider: 'apple', label: 'Continue with Apple' },
  { provider: 'slack', label: 'Continue with Slack' },
  { provider: 'microsoft', label: 'Continue with Microsoft' },
];

/**
 * The post-auth destination a successful login should land on. Only an
 * internal absolute path is accepted (a single leading `/`, not a
 * protocol-relative `//…` or an absolute scheme) — RequireAuth builds it from
 * the visitor's own deep link, and anything else falls back to the tenant home
 * so a hand-built `/login?redirect=…` link can never push the browser to a
 * foreign origin.
 */
export function resolvePostAuthRedirect(raw: string | null): string {
  if (raw !== null && raw.startsWith('/') && !raw.startsWith('//')) {
    return raw;
  }
  return '/settings';
}

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { apiKeyLogin, sessionLogin } = useAuth();

  const [email, setEmail] = useState(searchParams.get('email') ?? '');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState<SsoState>('idle');

  const redirectTo = resolvePostAuthRedirect(searchParams.get('redirect'));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      // Trust-plane posture returns a durable session; legacy returns api_key.
      const grant = resolveAuthGrant(await api.auth.login(email.trim(), password));
      if (grant.kind === 'session') {
        await sessionLogin(grant.session);
      } else {
        await apiKeyLogin(grant.apiKey);
      }
      void navigate(redirectTo, { replace: true });
    } catch {
      setError('Incorrect email or password');
    } finally {
      setLoading(false);
    }
  }

  async function handleDevelopmentSession() {
    setLoading(true);
    setError(null);
    try {
      const grant = resolveAuthGrant(await api.auth.developmentSession());
      if (grant.kind !== 'session') {
        throw new Error('Development login did not return a backend session');
      }
      await sessionLogin(grant.session);
      void navigate(redirectTo, { replace: true });
    } catch {
      setError('Development session unavailable');
    } finally {
      setLoading(false);
    }
  }

  function handleSso(provider: SocialProvider) {
    setSsoLoading('loading');
    window.location.href = `/v1/auth/sso/${provider}?redirect_uri=${encodeURIComponent(window.location.origin + '/callback')}`;
  }

  return (
    <div className="min-h-screen bg-surface-base flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <AetherLogo size={36} className="justify-center mb-2" />
          <p className="text-text-muted text-sm">Sign in to your account</p>
        </div>

        <div className="bg-surface-raised border border-border-default rounded-lg p-6 space-y-5">
          <form onSubmit={(e) => { void handleSubmit(e); }} className="space-y-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="login-email" className="text-xs text-text-secondary">Email address</label>
              <input
                id="login-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="bg-surface-base text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="login-password" className="text-xs text-text-secondary">Password</label>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Your password"
                className="bg-surface-base text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
              />
            </div>
            {error && <p className="text-danger text-xs font-mono">{error}</p>}
            <Button type="submit" variant="primary" size="sm" className="w-full"
              disabled={!email.trim() || !password || loading}>
              {loading ? '[···]' : 'Sign in'}
            </Button>
          </form>

          {env.VITE_AETHER_ENV === 'local' && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="w-full"
              disabled={loading}
              onClick={() => { void handleDevelopmentSession(); }}
            >
              Use backend development session
            </Button>
          )}

          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-border-subtle" />
            <span className="text-text-muted text-xs font-mono">or</span>
            <div className="flex-1 h-px bg-border-subtle" />
          </div>

          <div className="space-y-2">
            {SSO_PROVIDERS.map(({ provider, label }) => (
              <Button
                key={provider}
                variant="secondary"
                size="sm"
                className="w-full flex items-center gap-2"
                disabled={ssoLoading === 'loading'}
                onClick={() => handleSso(provider)}
                aria-label={label}
              >
                {ssoLoading === 'loading' ? (
                  <span className="text-text-muted">[···]</span>
                ) : (
                  <SocialProviderIcon provider={provider} />
                )}
                <span>{label}</span>
              </Button>
            ))}
          </div>

          <p className="text-center text-xs text-text-muted">
            No account?{' '}
            <button onClick={() => void navigate('/signup')} className="text-accent underline">
              Create one
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
