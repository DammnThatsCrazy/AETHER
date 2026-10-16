import { useState } from 'react';
import { BrandMark } from '@aether-app/components/brand-mark';
import { ChoiceChip, InlineNotice, LinkButton, Panel, PrimaryButton, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { api } from '@aether-app/lib/api/endpoints';
import {
  ACTIVATION_PLAN_TIERS,
  useCreateSdkKeys,
  useSelectPlan,
  useSelectSdks,
  useSendTestEvent,
  type ActivationPlanTier,
  type ActivationStatus,
} from '@aether-app/features/activation/use-activation';
import {
  invalidateTenantApiKeys,
  useCreateTenantApiKey,
  useTenantApiKeys,
  useTenantProfile,
} from '@aether-app/features/onboarding/use-workspace-setup';
import {
  SDK_OPTIONS,
  canRecordSdkSelection,
  hasReceivedEvent,
  keyMintRoute,
  platformsFor,
  sdkKeyLabel,
  type SdkOption,
} from './onboarding-model';
import { StepHeading } from './step-heading';

/** A raw key shown once in this session, plus the visitor's "stored it" tick. */
interface RevealedKey {
  readonly id: string;
  readonly key: string;
  readonly saved: boolean;
}

function isPlanTier(value: string | null | undefined): value is ActivationPlanTier {
  return !!value && (ACTIVATION_PLAN_TIERS as readonly string[]).includes(value);
}

/**
 * SDK fleet state shared by the step and the flow footer: which SDKs are
 * selected, which have a key on record (by label in /v1/me/api-keys), and
 * which raw keys were revealed in this session.
 */
export function useSdkFleet(status: ActivationStatus | null, selected: readonly string[]) {
  const keys = useTenantApiKeys();
  const [revealed, setRevealed] = useState<Readonly<Record<string, RevealedKey>>>({});
  const onRecord = (sdk: SdkOption) => (keys.data?.api_keys ?? []).find(k => k.name === sdkKeyLabel(sdk)) ?? null;

  const rows = SDK_OPTIONS.filter(sdk => selected.includes(sdk.id)).map(sdk => {
    const shown = revealed[sdk.id] ?? null;
    const record = onRecord(sdk);
    const issued = Boolean(shown) || Boolean(record);
    // A key revealed in this session is ready once the visitor confirms they
    // stored it; a key already on record was revealed in an earlier session.
    const ready = shown ? shown.saved : Boolean(record);
    return { sdk, shown, record, issued, ready };
  });

  return {
    keys,
    rows,
    revealed,
    setRevealed,
    selectedCount: rows.length,
    issuedCount: rows.filter(r => r.issued).length,
    readyCount: rows.filter(r => r.ready).length,
    live: hasReceivedEvent(status?.state),
  };
}

export type SdkFleet = ReturnType<typeof useSdkFleet>;

export interface SdksStepProps {
  readonly status: ActivationStatus;
  readonly selected: readonly string[];
  readonly onToggle: (id: string) => void;
  readonly fleet: SdkFleet;
}

const BADGE: Record<'live' | 'ready' | 'issued' | 'none', { readonly label: string; readonly tone: Tone }> = {
  live: { label: 'live', tone: 'sage' },
  ready: { label: 'key ready', tone: 'blue' },
  issued: { label: 'key issued', tone: 'amber' },
  none: { label: 'no key', tone: 'mute' },
};

export function SdksStep({ status, selected, onToggle, fleet }: SdksStepProps) {
  const selectPlan = useSelectPlan();
  const selectSdks = useSelectSdks();
  const createSdkKeys = useCreateSdkKeys();
  const createTenantKey = useCreateTenantApiKey();
  const sendTest = useSendTestEvent();
  const me = useTenantProfile();
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [needsPlan, setNeedsPlan] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const signupTier = me.data?.plan?.plan_id;

  async function mint(sdk: SdkOption, chosenTier?: ActivationPlanTier) {
    setBusy(sdk.id);
    setFailure(null);
    const label = sdkKeyLabel(sdk);
    try {
      let route = keyMintRoute(status.state);
      if (route === 'blocked') {
        setFailure(status.waiting_reason ?? 'Activation is paused. Resolve the blocker before issuing keys.');
        return;
      }
      if (route === 'needs_plan') {
        // The plan is the one chosen at signup (or picked here); never assumed.
        const tier = chosenTier ?? (isPlanTier(signupTier) ? signupTier : null);
        if (!tier) {
          setNeedsPlan(true);
          return;
        }
        if (!(await selectPlan.mutate({ plan_tier: tier }))) throw new Error(selectPlan.error ?? 'Could not record your plan.');
        setNeedsPlan(false);
        route = 'select_then_activation';
      }
      let raw: { id: string; key: string } | null = null;
      if (route === 'select_then_activation' || route === 'activation') {
        if (route === 'select_then_activation' || canRecordSdkSelection(status.state)) {
          const recorded = await selectSdks.mutate({ platforms: platformsFor(selected) });
          if (!recorded) throw new Error(selectSdks.error ?? 'Could not record the SDK selection.');
        }
        const result = await createSdkKeys.mutate({ count: 1, label });
        const key = result?.keys[0];
        if (!key) throw new Error(createSdkKeys.error ?? 'Could not issue a key.');
        raw = { id: key.id, key: key.key };
      } else {
        const created = await createTenantKey.mutate({ name: label, platform: sdk.platform });
        if (!created) throw new Error(createTenantKey.error ?? 'Could not issue a key.');
        raw = { id: created.id, key: created.key || created.api_key };
      }
      fleet.setRevealed(prev => ({ ...prev, [sdk.id]: { id: raw.id, key: raw.key, saved: false } }));
      invalidateTenantApiKeys();
    } catch (e) {
      setFailure(e instanceof Error ? e.message : 'Could not issue a key.');
    } finally {
      setBusy(null);
    }
  }

  async function revokeAndReissue(sdk: SdkOption, keyId: string) {
    setBusy(sdk.id);
    setFailure(null);
    try {
      await api.settings.revokeKey(keyId);
      fleet.setRevealed(prev => {
        const next = { ...prev };
        delete next[sdk.id];
        return next;
      });
      invalidateTenantApiKeys();
    } catch (e) {
      setFailure(e instanceof Error ? e.message : 'Could not revoke the key.');
      setBusy(null);
      return;
    }
    await mint(sdk);
  }

  async function copy(sdkId: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(sdkId);
      window.setTimeout(() => setCopied(c => (c === sdkId ? null : c)), 1600);
    } catch {
      // Clipboard blocked: the key stays selectable for a manual copy.
    }
  }

  const testResult = sendTest.data?.results[0];

  return (
    <div className="ae-rise flex flex-col items-center gap-[22px]" data-testid="onboarding-step-sdks">
      <StepHeading
        step={3}
        kicker="SDKs and keys"
        title="Add your SDKs"
        description="Select every surface you run. Each SDK gets its own key, so every app, device and server can be rotated and revoked on its own."
        summary={`${fleet.selectedCount} SDK${fleet.selectedCount === 1 ? '' : 's'} · ${fleet.issuedCount} key${fleet.issuedCount === 1 ? '' : 's'} · ${fleet.live ? 'events arriving' : 'awaiting first event'}`}
      />

      <div className="flex flex-wrap justify-center gap-1.5" aria-label="Key permissions">
        {['read', 'write', 'ingest', 'analytics'].map(scope => (
          <span
            key={scope}
            className="ae-mono rounded-full border px-2.5 py-1 text-[12px]"
            style={{ color: 'var(--ae-blue-ink)', borderColor: 'var(--ae-blue)', background: 'var(--ae-blue-tint)' }}
          >
            {scope}
          </span>
        ))}
      </div>

      {needsPlan && (
        <Panel className="flex w-full max-w-[640px] flex-col items-center gap-3 p-5 text-center">
          <span className="text-[14px] font-medium">Choose your plan to issue keys</span>
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
            Keys carry your plan's limits. You can change plans later in Billing.
          </span>
          <div className="flex flex-wrap justify-center gap-1.5">
            {ACTIVATION_PLAN_TIERS.map(tier => (
              <ChoiceChip
                key={tier}
                size="sm"
                selected={false}
                disabled={busy !== null}
                onClick={() => {
                  const first = fleet.rows.find(r => !r.issued);
                  if (first) void mint(first.sdk, tier);
                }}
              >
                {tier}
              </ChoiceChip>
            ))}
          </div>
        </Panel>
      )}

      {failure && <InlineNotice tone="ember">{failure}</InlineNotice>}

      <div className="grid w-full max-w-[760px] gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(150px, 100%), 1fr))' }}>
        {SDK_OPTIONS.map(sdk => {
          const on = selected.includes(sdk.id);
          const row = fleet.rows.find(r => r.sdk.id === sdk.id);
          const badge = !row ? null : fleet.live && row.issued ? BADGE.live : row.ready ? BADGE.ready : row.issued ? BADGE.issued : BADGE.none;
          return (
            <button
              key={sdk.id}
              type="button"
              aria-pressed={on}
              data-sdk={sdk.id}
              onClick={() => onToggle(sdk.id)}
              className="ae-focus relative flex flex-col items-center gap-2.5 rounded-[20px] border px-3 pb-3.5 pt-[18px] text-center"
              style={{
                background: on ? 'var(--ae-blue-tint)' : 'var(--ae-glass-card)',
                borderColor: on ? 'var(--ae-blue)' : 'var(--ae-edge-soft)',
                backdropFilter: 'blur(20px) saturate(1.4)',
                boxShadow: 'var(--ae-lift)',
              }}
            >
              <span
                aria-hidden="true"
                className="absolute right-2.5 top-2.5 flex h-4 w-4 items-center justify-center rounded-full text-[10px] text-white"
                style={{ border: `1.5px solid ${on ? 'var(--ae-blue)' : 'var(--ae-faint)'}`, background: on ? 'var(--ae-blue)' : 'transparent' }}
              >
                {on ? '✓' : ''}
              </span>
              <BrandMark token={sdk.mark} label={sdk.name} size={44} markSize={26} />
              <span className="flex flex-col leading-snug">
                <span className="text-[14px] font-medium">{sdk.name}</span>
                <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{sdk.description}</span>
              </span>
              {badge && <TonePill tone={badge.tone}>{badge.label}</TonePill>}
            </button>
          );
        })}
      </div>

      <div className="flex w-full max-w-[640px] flex-col gap-3">
        {fleet.rows.map(({ sdk, shown, record, issued }) => (
          <Panel key={sdk.id} className="flex min-w-0 flex-col gap-3" style={{ padding: 'clamp(14px,2.6vw,20px)' }}>
            <div className="flex items-center gap-3">
              <BrandMark token={sdk.mark} label={sdk.name} size={32} markSize={20} />
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="text-[14px] font-medium">{sdk.name}</span>
                <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{sdkKeyLabel(sdk)}</span>
              </span>
            </div>

            {!issued && (
              <PrimaryButton disabled={busy !== null} onClick={() => void mint(sdk)} data-testid={`generate-key-${sdk.id}`}>
                {busy === sdk.id ? 'Issuing key…' : `Generate key for ${sdk.short}`}
              </PrimaryButton>
            )}

            {shown && (
              <div className="flex flex-col gap-2.5">
                <div className="flex items-center gap-2 rounded-lg px-3 py-2.5" style={{ background: 'var(--ae-code)', color: 'var(--ae-code-ink)' }}>
                  <code className="ae-mono flex-1 select-all break-all text-[12px] leading-snug" data-testid={`raw-key-${sdk.id}`}>{shown.key}</code>
                  <button
                    type="button"
                    onClick={() => void copy(sdk.id, shown.key)}
                    className="ae-focus flex-none rounded px-2.5 py-1 text-[11px]"
                    style={{ background: '#2a2a2f', color: '#e8e6e1' }}
                  >
                    {copied === sdk.id ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <span className="text-[12px] leading-snug" style={{ color: 'var(--ae-amber)' }}>
                  {sdk.platform === 'server' ? 'Secret key, server-side only' : 'Write key for this SDK'} · shown once, stored as a hash.
                </span>
                <label className="flex cursor-pointer items-center gap-2.5 text-[13px]">
                  <input
                    type="checkbox"
                    checked={shown.saved}
                    onChange={e => fleet.setRevealed(prev => ({ ...prev, [sdk.id]: { ...shown, saved: e.target.checked } }))}
                    className="h-[18px] w-[18px] accent-[var(--ae-blue)]"
                  />
                  I have stored this key securely
                </label>
              </div>
            )}

            {!shown && record && (
              <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                Key on record · the raw value was shown once when it was issued.
              </span>
            )}

            <pre
              className="ae-mono m-0 whitespace-pre-wrap break-all rounded-lg px-3.5 py-3 text-[12px] leading-relaxed"
              style={{ background: 'rgba(127,127,127,.08)', color: 'var(--ae-ink)' }}
            >
              {sdk.snippet.replace(/YOUR_API_KEY/g, shown ? `${shown.key.slice(0, 12)}…` : 'YOUR_API_KEY')}
            </pre>

            {issued && (
              <div
                className="flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5"
                style={{
                  background: fleet.live ? 'var(--ae-sage-tint)' : 'var(--ae-card)',
                  borderColor: fleet.live ? 'var(--ae-sage)' : 'var(--ae-edge-soft)',
                }}
              >
                <span className={fleet.live ? '' : 'ae-pulse'} style={{ color: fleet.live ? 'var(--ae-sage)' : 'var(--ae-faint)' }}>
                  {fleet.live ? '●' : '○'}
                </span>
                <span className="flex flex-1 flex-col leading-snug">
                  <span className="text-[13px] font-medium">{fleet.live ? 'Events are arriving' : 'Awaiting first event'}</span>
                  <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>
                    {fleet.live
                      ? 'first event received for this workspace'
                      : testResult
                        ? `test event ${testResult.status}${testResult.reason ? ` · ${testResult.reason}` : ''}`
                        : 'install the snippet, or send a test event'}
                  </span>
                </span>
                {!fleet.live && (
                  <LinkButton onClick={() => void sendTest.mutate({ event_type: 'onboarding_test_event', properties: { source: 'onboarding', sdk: sdk.id } })}>
                    {sendTest.isLoading ? 'Sending…' : 'Send test event'}
                  </LinkButton>
                )}
              </div>
            )}

            {issued && (record || shown) && (
              <LinkButton
                className="self-start"
                onClick={() => void revokeAndReissue(sdk, (shown?.id ?? record?.id) as string)}
              >
                Revoke and generate a new key
              </LinkButton>
            )}
          </Panel>
        ))}
      </div>
    </div>
  );
}
