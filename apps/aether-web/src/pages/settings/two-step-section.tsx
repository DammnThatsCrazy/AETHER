import { useEffect, useState } from 'react';
import qrcode from 'qrcode-generator';
import { InlineNotice, TonePill } from '@aether-app/components/ae-ui';
import { api, type MfaStatus } from '@aether-app/lib/api/endpoints';
import { SettingsBlock, SettingsRow } from './settings-hubs';

type Mode =
  | { readonly kind: 'idle' }
  | { readonly kind: 'enrolling'; readonly secret: string; readonly uri: string }
  | { readonly kind: 'codes'; readonly codes: readonly string[]; readonly heading: string }
  | { readonly kind: 'confirm'; readonly action: 'disable' | 'regenerate' };

const mute = { color: 'var(--ae-mute)' } as const;

function qrDataUrl(uri: string): string {
  const qr = qrcode(0, 'M');
  qr.addData(uri);
  qr.make();
  return qr.createDataURL(5, 2);
}

function errorText(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message : '';
  return raw && raw.length < 160 ? raw : fallback;
}

function CodeInput({ value, onChange, placeholder, testId }: {
  readonly value: string; readonly onChange: (v: string) => void; readonly placeholder: string; readonly testId: string;
}) {
  return (
    <input
      className="ae-focus min-w-0 max-w-[200px] rounded-[10px] border px-3.5 py-2 text-[13px] outline-none"
      style={{ background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}
      inputMode="numeric"
      autoComplete="one-time-code"
      aria-label={placeholder}
      placeholder={placeholder}
      value={value}
      onChange={e => onChange(e.target.value)}
      data-testid={testId}
    />
  );
}

function Primary({ children, onClick, disabled, testId }: {
  readonly children: React.ReactNode; readonly onClick: () => void; readonly disabled?: boolean; readonly testId?: string;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} data-testid={testId} className="ae-btn-primary ae-focus whitespace-nowrap px-3.5 py-2 text-[12px]">
      {children}
    </button>
  );
}

function Secondary({ children, onClick, disabled, testId }: {
  readonly children: React.ReactNode; readonly onClick: () => void; readonly disabled?: boolean; readonly testId?: string;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} data-testid={testId} className="ae-btn-secondary ae-focus whitespace-nowrap px-3.5 py-1.5 text-[12px]">
      {children}
    </button>
  );
}

/** Personal → Profile: opt-in two-step verification with an authenticator app. */
export function TwoStepVerificationBlock() {
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [mode, setMode] = useState<Mode>({ kind: 'idle' });
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.me.mfa.status().then(s => { setStatus(s); setLoadError(false); }).catch(() => setLoadError(true));
  };
  useEffect(load, []);

  function reset(next: Mode = { kind: 'idle' }) {
    setMode(next);
    setCode('');
    setError(null);
    setBusy(false);
  }

  async function run<T>(fn: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(errorText(err, fallback));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function startEnrolment() {
    const started = await run(() => api.me.mfa.enroll(), 'Could not start set-up. Try again.');
    if (started) reset({ kind: 'enrolling', secret: started.secret, uri: started.otpauth_uri });
  }

  async function confirmEnrolment() {
    const done = await run(() => api.me.mfa.confirm(code.replace(/\s/g, '')), 'That code does not match.');
    if (done) {
      reset({ kind: 'codes', codes: done.recovery_codes, heading: 'Two-step verification is on' });
      load();
    }
  }

  async function confirmAction(action: 'disable' | 'regenerate') {
    if (action === 'disable') {
      const done = await run(() => api.me.mfa.disable(code.trim()), 'Incorrect code.');
      if (done) { reset(); load(); }
      return;
    }
    const done = await run(() => api.me.mfa.regenerateRecoveryCodes(code.trim()), 'Incorrect code.');
    if (done) { reset({ kind: 'codes', codes: done.recovery_codes, heading: 'New recovery codes' }); load(); }
  }

  const enabled = status?.enabled === true;

  return (
    <SettingsBlock
      title="Two-step verification"
      sub="Ask for a code from an authenticator app every time you sign in, whichever way you sign in."
      testId="settings-two-step"
    >
      {loadError ? (
        <div className="border-t pt-3"><InlineNotice>Two-step verification is unavailable for this sign-in.</InlineNotice></div>
      ) : status === null ? (
        <span className="border-t pt-3 text-[13px]" style={mute}>Loading…</span>
      ) : mode.kind === 'enrolling' ? (
        <>
          <SettingsRow
            label="1. Scan with your authenticator app"
            description="Google Authenticator, 1Password, Authy, Microsoft Authenticator and similar apps all work."
          >
            <img src={qrDataUrl(mode.uri)} alt="QR code for your authenticator app" width={148} height={148} style={{ borderRadius: 8, background: '#fff' }} />
          </SettingsRow>
          <SettingsRow label="Or enter this key" description="Time-based, 6 digits.">
            <span className="ae-mono break-all text-[13px]" data-testid="two-step-secret">{mode.secret.replace(/(.{4})/g, '$1 ').trim()}</span>
          </SettingsRow>
          <SettingsRow label="2. Enter the 6-digit code it shows">
            <CodeInput value={code} onChange={setCode} placeholder="6-digit code" testId="two-step-code" />
            <Primary onClick={() => void confirmEnrolment()} disabled={busy || !/^\d{6}$/.test(code.replace(/\s/g, ''))} testId="two-step-confirm">
              {busy ? 'Checking…' : 'Turn on'}
            </Primary>
            <Secondary onClick={() => reset()} disabled={busy}>Cancel</Secondary>
          </SettingsRow>
        </>
      ) : mode.kind === 'codes' ? (
        <SettingsRow
          label={mode.heading}
          description="Save these recovery codes somewhere safe. Each works once if you lose your authenticator. They will not be shown again."
        >
          <span className="ae-mono grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]" data-testid="two-step-recovery-codes">
            {mode.codes.map(c => <span key={c}>{c}</span>)}
          </span>
          <Secondary onClick={() => void navigator.clipboard?.writeText(mode.codes.join('\n'))}>Copy</Secondary>
          <Primary onClick={() => reset()} testId="two-step-done">I saved them</Primary>
        </SettingsRow>
      ) : mode.kind === 'confirm' ? (
        <SettingsRow
          label={mode.action === 'disable' ? 'Turn off two-step verification' : 'Replace recovery codes'}
          description="Enter a current code from your authenticator app, or a recovery code."
        >
          <CodeInput value={code} onChange={setCode} placeholder="Code" testId="two-step-action-code" />
          <Primary onClick={() => void confirmAction(mode.action)} disabled={busy || code.trim().length < 6} testId="two-step-action-confirm">
            {busy ? 'Checking…' : mode.action === 'disable' ? 'Turn off' : 'Replace codes'}
          </Primary>
          <Secondary onClick={() => reset()} disabled={busy}>Cancel</Secondary>
        </SettingsRow>
      ) : enabled ? (
        <>
          <SettingsRow label="Status" description={status.enrolled_at ? `On since ${new Date(status.enrolled_at).toLocaleDateString()}` : undefined}>
            <TonePill tone="sage">On</TonePill>
            <Secondary onClick={() => reset({ kind: 'confirm', action: 'disable' })} testId="two-step-disable">Turn off</Secondary>
          </SettingsRow>
          <SettingsRow label="Recovery codes" description={`${status.recovery_codes_remaining} unused.`}>
            <Secondary onClick={() => reset({ kind: 'confirm', action: 'regenerate' })} testId="two-step-regenerate">Replace codes</Secondary>
          </SettingsRow>
        </>
      ) : (
        <SettingsRow label="Status" description="Off. Your password, Google, Apple or other sign-in is the only check.">
          <TonePill tone="mute">Off</TonePill>
          <Primary onClick={() => void startEnrolment()} disabled={busy} testId="two-step-enable">Set up</Primary>
        </SettingsRow>
      )}
      {error && <div className="pt-2"><InlineNotice tone="ember">{error}</InlineNotice></div>}
    </SettingsBlock>
  );
}
