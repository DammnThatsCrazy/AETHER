import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, GlyphIcon, SocialProviderIcon } from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';
import type { SocialProvider } from '@aether/ui';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { OtpInput } from '@aether-app/components/otp-input';

type Step = 'email' | 'otp';
type SsoState = 'idle' | 'loading';

const SSO_PROVIDERS: Array<{ provider: SocialProvider; label: string }> = [
  { provider: 'google', label: 'Continue with Google' },
  { provider: 'apple', label: 'Continue with Apple' },
  { provider: 'slack', label: 'Continue with Slack' },
  { provider: 'microsoft', label: 'Continue with Microsoft' },
];

const RESEND_COOLDOWN = 30;

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { apiKeyLogin } = useAuth();

  const [step, setStep] = useState<Step>('email');
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [otpError, setOtpError] = useState<string | null>(null);
  const [resendHighlighted, setResendHighlighted] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [emailLoading, setEmailLoading] = useState(false);
  const [otpLoading, setOtpLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState<SsoState>('idle');

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const id = setTimeout(() => setResendCooldown(c => c - 1), 1000);
    return () => clearTimeout(id);
  }, [resendCooldown]);

  const redirectTo = searchParams.get('redirect') ?? '/settings';

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setEmailLoading(true);
    try {
      await api.auth.requestOtp(email.trim());
      setStep('otp');
      setResendCooldown(RESEND_COOLDOWN);
    } catch {
      // Treat failures silently to prevent email enumeration
      setStep('otp');
      setResendCooldown(RESEND_COOLDOWN);
    } finally {
      setEmailLoading(false);
    }
  }

  async function handleOtpSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (otp.length < 6) return;
    setOtpLoading(true);
    setOtpError(null);
    try {
      const { api_key } = await api.auth.verifyOtp(email.trim(), otp);
      apiKeyLogin(api_key);
      void navigate(redirectTo, { replace: true });
    } catch {
      setOtpError('Invalid or expired code — try again or request a new one below');
      setResendHighlighted(true);
      setOtp('');
    } finally {
      setOtpLoading(false);
    }
  }

  async function handleResend() {
    if (resendCooldown > 0) return;
    setResendHighlighted(false);
    setOtpError(null);
    setResendCooldown(RESEND_COOLDOWN);
    try {
      await api.auth.requestOtp(email.trim());
    } catch {
      // silent
    }
  }

  function handleSso(provider: SocialProvider) {
    setSsoLoading('loading');
    // Auth0 loginWithRedirect will redirect away; loading state is intentionally sticky
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
          {step === 'email' && (
            <>
              <form onSubmit={(e) => { void handleEmailSubmit(e); }} className="space-y-3">
                <div className="flex flex-col gap-1">
                  <label htmlFor="login-email" className="text-xs text-text-secondary">
                    Email address
                  </label>
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
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  className="w-full"
                  disabled={!email.trim() || emailLoading}
                >
                  {emailLoading ? '[···]' : 'Continue'}
                </Button>
              </form>

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
                <button
                  onClick={() => void navigate('/signup')}
                  className="text-accent underline"
                >
                  Create one
                </button>
              </p>
            </>
          )}

          {step === 'otp' && (
            <form onSubmit={(e) => { void handleOtpSubmit(e); }} className="space-y-4">
              <div>
                <p className="text-sm text-text-secondary">
                  We sent a 6-digit code to{' '}
                  <span className="font-mono text-accent">{email}</span>
                </p>
                <button
                  type="button"
                  onClick={() => { setStep('email'); setOtp(''); setOtpError(null); }}
                  className="text-xs text-text-muted underline mt-0.5"
                >
                  Change email
                </button>
              </div>

              <div className="flex flex-col gap-2">
                <OtpInput
                  value={otp}
                  onChange={setOtp}
                  error={!!otpError}
                  disabled={otpLoading}
                />
                {otpError && (
                  <p className="text-danger text-xs font-mono">{otpError}</p>
                )}
              </div>

              <Button
                type="submit"
                variant="primary"
                size="sm"
                className="w-full"
                disabled={otp.length < 6 || otpLoading}
              >
                {otpLoading ? '[···]' : 'Verify & sign in'}
              </Button>

              <div className="text-center">
                {resendCooldown > 0 ? (
                  <span className="text-text-muted text-xs font-mono">
                    resend in {resendCooldown}s
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => { void handleResend(); }}
                    className={resendHighlighted ? 'text-accent underline text-xs animate-pulse' : 'text-accent underline text-xs'}
                  >
                    Resend code
                  </button>
                )}
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
