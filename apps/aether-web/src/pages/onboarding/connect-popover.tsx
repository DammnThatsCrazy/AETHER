import { useEffect, useRef, useState } from 'react';
import { BrandMark } from '@aether-app/components/brand-mark';
import { Eyebrow, InlineNotice, PrimaryButton, Spinner } from '@aether-app/components/ae-ui';
import {
  useActivationConnectAction,
  type ActivationConnectAction,
  type ActivationPlanIntegration,
} from '@aether-app/features/activation/use-activation-intents';
import { authenticationLabel } from './onboarding-model';

type Phase = 'ask' | 'credential' | 'working' | 'done' | 'error';

const ACTION_COPY: Record<ActivationConnectAction, string> = {
  create_tenant_integration: 'Registering the connection…',
  configure_credential: 'Storing the credential…',
  enable_connection: 'Enabling the connection…',
  first_sync: 'Starting the first sync…',
};

function isConnectAction(value: string | null | undefined): value is ActivationConnectAction {
  return value === 'create_tenant_integration' || value === 'configure_credential' || value === 'enable_connection' || value === 'first_sync';
}

/**
 * Connect one recommended integration from a pop-over. Each click runs the
 * server's next connect action (create → credential → enable → first sync)
 * through POST /v1/activation/connect-action and follows the returned
 * next_action until a step needs the visitor (a credential) or the first sync
 * has started. The pop-over closes itself once the connection is under way.
 */
export function ConnectPopover({
  integration,
  onClose,
}: {
  readonly integration: ActivationPlanIntegration;
  readonly onClose: () => void;
}) {
  const connect = useActivationConnectAction();
  const [phase, setPhase] = useState<Phase>(integration.next_action === 'configure_credential' ? 'credential' : 'ask');
  const [credential, setCredential] = useState('');
  const [working, setWorking] = useState<string>('');
  const [failure, setFailure] = useState<string | null>(null);
  const mounted = useRef(true);
  const method = authenticationLabel(integration.authentication);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && phase !== 'working') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, phase]);

  useEffect(() => {
    if (phase !== 'done') return;
    const t = window.setTimeout(onClose, 1100);
    return () => window.clearTimeout(t);
  }, [phase, onClose]);

  async function run(startAction: string | null, secret?: string) {
    let next = startAction;
    let pendingSecret = secret;
    setFailure(null);
    // Bounded: the connect machine has four actions; never loop past them.
    for (let guard = 0; guard < 6 && isConnectAction(next); guard++) {
      if (next === 'configure_credential' && !pendingSecret) {
        if (mounted.current) setPhase('credential');
        return;
      }
      if (mounted.current) {
        setPhase('working');
        setWorking(ACTION_COPY[next]);
      }
      const input =
        next === 'configure_credential' && pendingSecret
          ? { family: integration.family, action: next, credential: pendingSecret }
          : { family: integration.family, action: next };
      const result = await connect.mutate(input);
      pendingSecret = undefined;
      if (!mounted.current) return;
      if (!result || !result.ok) {
        // A null result means the request itself failed; connect.error (rendered
        // below) carries the transport message on the next render.
        setFailure(result?.detail ?? 'The connection step did not complete.');
        setPhase('error');
        return;
      }
      if (next === 'first_sync' || result.connection_state === 'connected') {
        setPhase('done');
        return;
      }
      if (result.can_act === false) break;
      next = result.next_action ?? null;
    }
    if (mounted.current) setPhase('done');
  }

  const credentialOk = credential.trim().length >= 8;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-5"
      style={{ background: 'var(--ae-scrim)', backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)' }}
      onClick={() => phase !== 'working' && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-title"
        data-testid="connect-popover"
        onClick={e => e.stopPropagation()}
        className="ae-rise flex w-[min(430px,100%)] flex-col gap-4 rounded-3xl border p-[22px]"
        style={{
          background: 'var(--ae-glass)',
          backdropFilter: 'blur(28px) saturate(1.4)',
          WebkitBackdropFilter: 'blur(28px) saturate(1.4)',
          borderColor: 'var(--ae-edge)',
          boxShadow: 'inset 0 2px 0 var(--ae-blue), 0 30px 80px -20px rgba(26,26,30,.45)',
        }}
      >
        <div className="flex items-center gap-3">
          <BrandMark token={integration.family} label={integration.display_name} size={40} markSize={24} />
          <span className="flex flex-1 flex-col leading-tight">
            <span id="connect-title" className="text-[16px] font-medium">{integration.display_name}</span>
            <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{method}</span>
          </span>
          <button
            type="button"
            aria-label="Close"
            disabled={phase === 'working'}
            onClick={onClose}
            className="ae-focus flex h-7 w-7 items-center justify-center rounded-full hover:bg-[var(--ae-edge-soft)]"
            style={{ color: 'var(--ae-mute)' }}
          >
            ✕
          </button>
        </div>

        {(phase === 'ask' || phase === 'error') && (
          <div className="flex flex-col gap-3.5">
            <p className="text-[13px] leading-normal" style={{ color: 'var(--ae-mute)' }}>
              Aether connects to {integration.display_name} read-only. Nothing is written back to your source.
            </p>
            <ul className="flex flex-col gap-1.5 text-[13px]">
              <li className="flex gap-2.5"><span style={{ color: 'var(--ae-sage)' }}>✓</span>Read {integration.product.replace(/_/g, ' ')} data</li>
              <li className="flex gap-2.5"><span style={{ color: 'var(--ae-sage)' }}>✓</span>No write access</li>
              <li className="flex gap-2.5"><span style={{ color: 'var(--ae-sage)' }}>✓</span>Disconnect any time in Settings</li>
            </ul>
            {failure && (
              <InlineNotice tone="ember">
                {failure}
                {connect.error && connect.error !== failure ? ` (${connect.error})` : ''}
              </InlineNotice>
            )}
            <PrimaryButton onClick={() => void run(integration.next_action)} data-testid="connect-popover-act">
              {phase === 'error' ? 'Try again' : `Connect ${integration.display_name}`}
            </PrimaryButton>
          </div>
        )}

        {phase === 'credential' && (
          <form
            className="flex flex-col gap-3"
            onSubmit={e => {
              e.preventDefault();
              if (credentialOk) {
                const secret = credential.trim();
                setCredential('');
                void run('configure_credential', secret);
              }
            }}
          >
            <p className="text-[13px] leading-normal" style={{ color: 'var(--ae-mute)' }}>
              Paste a read-only {integration.display_name} credential. It is stored encrypted and never shown again.
            </p>
            <Eyebrow>Credential</Eyebrow>
            <input
              type="password"
              autoComplete="off"
              autoFocus
              value={credential}
              onChange={e => setCredential(e.target.value)}
              placeholder="Paste read-only key"
              data-credential-field="secret"
              className="ae-mono rounded border px-3 py-2.5 text-[13px] outline-none focus:border-[var(--ae-blue)]"
              style={{ background: 'var(--ae-raised)', borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}
            />
            <PrimaryButton type="submit" disabled={!credentialOk}>Verify and connect</PrimaryButton>
          </form>
        )}

        {phase === 'working' && (
          <div className="flex flex-col items-center gap-3 pb-2.5 pt-[18px]">
            <Spinner />
            <span className="text-center text-[13px]" style={{ color: 'var(--ae-mute)' }}>{working}</span>
          </div>
        )}

        {phase === 'done' && (
          <div className="flex flex-col items-center gap-2.5 pb-2.5 pt-[18px]">
            <span
              className="ae-rise flex h-10 w-10 items-center justify-center rounded-full text-[18px]"
              style={{ background: 'var(--ae-sage-tint)', color: 'var(--ae-sage)' }}
            >
              ✓
            </span>
            <span className="text-[14px] font-medium">Connection under way</span>
            <span className="text-center text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              The first sync runs in the background. Its status shows on the source row.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
