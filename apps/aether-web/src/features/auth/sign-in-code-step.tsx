import { useState } from 'react';
import {
  AuthPortalError, AuthPortalInput, AuthPortalNote, AuthPortalPrimaryButton, AuthPortalShell, AuthPortalTextButton,
} from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';
import { describeAuthRateLimit } from './rate-limit';

export type SignInCodeKind = 'signup' | 'mfa';

interface SignInCodeStepProps {
  readonly kind: SignInCodeKind;
  /** Where the sign-up code went (shown for kind="signup"). */
  readonly email?: string | undefined;
  /** Submit a code; resolve when the caller has moved on, reject with the server's error. */
  readonly onSubmit: (code: string) => Promise<void>;
  /** Ask for a fresh sign-up code (kind="signup"). */
  readonly onResend?: (() => Promise<void>) | undefined;
  readonly onCancel: () => void;
}

const COPY: Record<SignInCodeKind, { title: string; lead: string; label: string; placeholder: string; action: string }> = {
  signup: {
    title: 'Check your email',
    lead: 'We sent a 6-digit code to confirm it is you. It expires in 10 minutes.',
    label: 'Sign-up code',
    placeholder: '6-digit code',
    action: 'Create my workspace',
  },
  mfa: {
    title: 'Two-step verification',
    lead: 'Enter the 6-digit code from your authenticator app.',
    label: 'Authentication code',
    placeholder: '6-digit code',
    action: 'Verify',
  },
};

function messageFor(err: unknown): string {
  const limited = describeAuthRateLimit(err);
  if (limited) return limited;
  const raw = err instanceof Error ? err.message : '';
  if (/expired/i.test(raw)) return raw.includes('Sign in again') ? raw : 'That code has expired. Request a new one.';
  if (/too many/i.test(raw)) return 'Too many incorrect codes. Sign in again.';
  return 'That code is not right. Try again.';
}

/** The code step shared by first-time sign-up and two-step sign-in, in the portal look. */
export function SignInCodeStep({ kind, email, onSubmit, onResend, onCancel }: SignInCodeStepProps) {
  const copy = COPY[kind];
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [useRecovery, setUseRecovery] = useState(false);

  const cleaned = code.trim();
  const valid = useRecovery ? cleaned.length >= 9 : /^\d{6}$/.test(cleaned.replace(/\s/g, ''));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await onSubmit(useRecovery ? cleaned : cleaned.replace(/\s/g, ''));
    } catch (err) {
      setError(messageFor(err));
      setBusy(false);
    }
  }

  async function resend() {
    if (!onResend) return;
    setError(null);
    try {
      await onResend();
      setNotice('We sent a new code.');
    } catch (err) {
      setError(describeAuthRateLimit(err) ?? 'Could not send a new code. Try again shortly.');
    }
  }

  return (
    <AuthPortalShell
      brand={<AetherLogo size={26} />}
      title={copy.title}
      lead={kind === 'signup' && email ? <>We sent a 6-digit code to <strong style={{ color: '#e8e6e1' }}>{email}</strong>. It expires in 10 minutes.</> : copy.lead}
    >
      <form onSubmit={(e) => void submit(e)} style={{ display: 'flex', flexDirection: 'column', gap: 12 }} noValidate>
        <AuthPortalInput
          label={useRecovery ? 'Recovery code' : copy.label}
          inputMode={useRecovery ? 'text' : 'numeric'}
          autoComplete="one-time-code"
          placeholder={useRecovery ? 'xxxx-xxxx' : copy.placeholder}
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value)}
          maxLength={useRecovery ? 16 : 7}
        />
        {error && <AuthPortalError>{error}</AuthPortalError>}
        {notice && <AuthPortalNote>{notice}</AuthPortalNote>}
        <AuthPortalPrimaryButton disabled={!valid || busy}>{busy ? 'Checking…' : copy.action}</AuthPortalPrimaryButton>
      </form>
      <AuthPortalNote>
        {kind === 'signup' && onResend && (
          <><AuthPortalTextButton onClick={() => void resend()}>Send a new code</AuthPortalTextButton>{' · '}</>
        )}
        {kind === 'mfa' && (
          <><AuthPortalTextButton onClick={() => { setUseRecovery(!useRecovery); setCode(''); setError(null); }}>
            {useRecovery ? 'Use authenticator code' : 'Use a recovery code'}
          </AuthPortalTextButton>{' · '}</>
        )}
        <AuthPortalTextButton onClick={onCancel}>Back to sign in</AuthPortalTextButton>
      </AuthPortalNote>
    </AuthPortalShell>
  );
}
