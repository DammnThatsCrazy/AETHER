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
  createSdkSite,
  createSitePublishableKey,
  invalidateTenantApiKeys,
  useCreateTenantApiKey,
  useSdkSites,
  useSiteLive,
  useTenantApiKeys,
  useTenantProfile,
  SDK_KEY_PERMISSIONS,
  type SdkSite,
  type TenantApiKey,
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
  readonly siteId?: string;
  /** Server-rendered install snippet (publishable keys only). */
  readonly snippet?: string;
}

const ACK_PREFIX = 'aether:onboarding-key-ack:';

/**
 * Whether the visitor confirmed storing a key's raw value. Persisted per key
 * id, so a reload after issuing (when the raw value can no longer be shown)
 * does not silently count an unconfirmed key as stored.
 */
export function readKeyAck(keyId: string): boolean {
  try {
    return window.localStorage.getItem(ACK_PREFIX + keyId) === '1';
  } catch {
    return false;
  }
}

function writeKeyAck(keyId: string, value: boolean): void {
  try {
    if (value) window.localStorage.setItem(ACK_PREFIX + keyId, '1');
    else window.localStorage.removeItem(ACK_PREFIX + keyId);
  } catch {
    // Storage unavailable: the confirmation lasts for this session only.
  }
}

function isPlanTier(value: string | null | undefined): value is ActivationPlanTier {
  return !!value && (ACTIVATION_PLAN_TIERS as readonly string[]).includes(value);
}

function parseOrigins(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map(o => o.trim())
    .filter(Boolean);
}

/**
 * SDK fleet state shared by the step and the flow footer: which SDKs are
 * selected, which have a key on record (by label, across every key page),
 * which raw keys were revealed in this session, and which were confirmed
 * stored.
 */
export function useSdkFleet(status: ActivationStatus | null, selected: readonly string[]) {
  const keys = useTenantApiKeys();
  const sites = useSdkSites();
  const [revealed, setRevealed] = useState<Readonly<Record<string, RevealedKey>>>({});
  const [acks, setAcks] = useState<Readonly<Record<string, boolean>>>({});

  const keyList: readonly TenantApiKey[] = keys.data?.api_keys ?? [];
  const siteList: readonly SdkSite[] = sites.data ?? [];

  const rows = SDK_OPTIONS.filter(sdk => selected.includes(sdk.id)).map(sdk => {
    const label = sdkKeyLabel(sdk);
    const shown = revealed[sdk.id] ?? null;
    const record = keyList.find(k => k.name === label) ?? null;
    const site = sdk.keyKind === 'publishable' ? (siteList.find(s => s.name === label && s.status !== 'revoked') ?? null) : null;
    const issued = Boolean(shown) || Boolean(record);
    const keyId = shown?.id ?? record?.id ?? null;
    const acknowledged = shown ? shown.saved : keyId ? (acks[keyId] ?? readKeyAck(keyId)) : false;
    return { sdk, shown, record, site, issued, keyId, ready: issued && acknowledged };
  });

  function acknowledge(keyId: string, value: boolean) {
    writeKeyAck(keyId, value);
    setAcks(prev => ({ ...prev, [keyId]: value }));
  }

  return {
    keys,
    sites,
    rows,
    revealed,
    setRevealed,
    acknowledge,
    selectedCount: rows.length,
    issuedCount: rows.filter(r => r.issued).length,
    readyCount: rows.filter(r => r.ready).length,
    /** Whether any secret (activation-trackable) SDK key is part of the fleet. */
    hasSecretSdk: rows.some(r => r.sdk.keyKind === 'secret'),
    live: hasReceivedEvent(status?.state),
  };
}

export type SdkFleet = ReturnType<typeof useSdkFleet>;
type FleetRow = SdkFleet['rows'][number];

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

function snippetFor(sdk: SdkOption, shown: RevealedKey | null, siteId: string | null): string {
  if (shown?.snippet && sdk.id === 'web') return shown.snippet;
  return sdk.snippet
    .replace(/YOUR_API_KEY/g, shown ? `${shown.key.slice(0, 12)}…` : sdk.keyKind === 'publishable' ? 'pk_YOUR_PUBLISHABLE_KEY' : 'YOUR_API_KEY')
    .replace(/YOUR_SITE_ID/g, shown?.siteId ?? siteId ?? 'site_YOUR_SITE_ID');
}

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
  const [origins, setOrigins] = useState<Readonly<Record<string, string>>>({});

  const signupTier = me.data?.plan?.plan_id;

  /** Plan + SDK selection bookkeeping on the activation record (where the state machine allows it). */
  async function recordSelection(chosenTier?: ActivationPlanTier): Promise<'ok' | 'needs_plan'> {
    let route = keyMintRoute(status.state);
    if (route === 'needs_plan') {
      // The plan is the one chosen at signup (or picked here); never assumed.
      const tier = chosenTier ?? (isPlanTier(signupTier) ? signupTier : null);
      if (!tier) return 'needs_plan';
      if (!(await selectPlan.mutate({ plan_tier: tier }))) throw new Error('Could not record your plan.');
      setNeedsPlan(false);
      route = 'select_then_activation';
    }
    if (route === 'select_then_activation' || canRecordSdkSelection(status.state)) {
      if (!(await selectSdks.mutate({ platforms: platformsFor(selected) }))) throw new Error('Could not record the SDK selection.');
    }
    return 'ok';
  }

  async function mintPublishable(row: FleetRow): Promise<RevealedKey> {
    const label = sdkKeyLabel(row.sdk);
    let site = row.site;
    if (!site) {
      const list = parseOrigins(origins[row.sdk.id] ?? '');
      if (!list.length) throw new Error(`Enter the site address ${row.sdk.short} runs on, e.g. https://example.com.`);
      site = await createSdkSite({ name: label, origins: list });
    }
    const pk = await createSitePublishableKey(site.id, label);
    return { id: pk.id, key: pk.key, saved: false, siteId: pk.siteId, snippet: pk.snippet };
  }

  async function mintSecret(sdk: SdkOption): Promise<RevealedKey> {
    const label = sdkKeyLabel(sdk);
    const route = keyMintRoute(status.state);
    if (route === 'select_then_activation' || route === 'activation' || route === 'needs_plan') {
      const result = await createSdkKeys.mutate({ count: 1, label });
      const key = result?.keys[0];
      if (!key) throw new Error('Could not issue a key.');
      return { id: key.id, key: key.key, saved: false };
    }
    const created = await createTenantKey.mutate({ name: label, platform: sdk.keyPlatform });
    if (!created) throw new Error('Could not issue a key.');
    return { id: created.id, key: created.key || created.api_key, saved: false };
  }

  async function mint(row: FleetRow, chosenTier?: ActivationPlanTier) {
    setBusy(row.sdk.id);
    setFailure(null);
    try {
      if (keyMintRoute(status.state) === 'blocked') {
        setFailure(status.waiting_reason ?? 'Activation is paused. Resolve the blocker before issuing keys.');
        return;
      }
      if ((await recordSelection(chosenTier)) === 'needs_plan') {
        setNeedsPlan(true);
        return;
      }
      const raw = row.sdk.keyKind === 'publishable' ? await mintPublishable(row) : await mintSecret(row.sdk);
      fleet.setRevealed(prev => ({ ...prev, [row.sdk.id]: raw }));
      invalidateTenantApiKeys();
    } catch (e) {
      setFailure(e instanceof Error ? e.message : 'Could not issue a key.');
    } finally {
      setBusy(null);
    }
  }

  async function revokeAndReissue(row: FleetRow) {
    if (!row.keyId) return;
    setBusy(row.sdk.id);
    setFailure(null);
    try {
      await api.settings.revokeKey(row.keyId);
      fleet.acknowledge(row.keyId, false);
      fleet.setRevealed(prev => {
        const next = { ...prev };
        delete next[row.sdk.id];
        return next;
      });
      invalidateTenantApiKeys();
    } catch (e) {
      setFailure(e instanceof Error ? e.message : 'Could not revoke the key.');
      setBusy(null);
      return;
    }
    await mint({ ...row, shown: null, record: null, keyId: null, issued: false, ready: false });
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
        description="Select every surface you run. Each SDK gets its own key, so every app, device and server can be rotated and revoked on its own. Browser SDKs get a publishable key bound to your site."
        summary={`${fleet.selectedCount} SDK${fleet.selectedCount === 1 ? '' : 's'} · ${fleet.issuedCount} key${fleet.issuedCount === 1 ? '' : 's'} · ${fleet.live ? 'events arriving' : 'awaiting first event'}`}
      />

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
                  if (first) void mint(first, tier);
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
          const badge = !row ? null : row.ready ? BADGE.ready : row.issued ? BADGE.issued : BADGE.none;
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
              <BrandMark token={sdk.mark} size={44} markSize={26} />
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
        {fleet.rows.map(row => (
          <SdkPanel
            key={row.sdk.id}
            row={row}
            busy={busy}
            copied={copied}
            origin={origins[row.sdk.id] ?? ''}
            onOrigin={value => setOrigins(prev => ({ ...prev, [row.sdk.id]: value }))}
            onMint={() => void mint(row)}
            onRevoke={() => void revokeAndReissue(row)}
            onCopy={value => void copy(row.sdk.id, value)}
            onAck={value => {
              if (row.shown) fleet.setRevealed(prev => ({ ...prev, [row.sdk.id]: { ...row.shown!, saved: value } }));
              if (row.keyId) fleet.acknowledge(row.keyId, value);
            }}
            tenantLive={fleet.live}
            testLabel={sendTest.isLoading ? 'Sending…' : 'Send test event'}
            testResult={testResult ? `test event ${testResult.status}${testResult.reason ? ` · ${testResult.reason}` : ''}` : null}
            onTest={() => void sendTest.mutate({ event_type: 'onboarding_test_event', properties: { source: 'onboarding', sdk: row.sdk.id } })}
          />
        ))}
      </div>

      <div className="flex flex-wrap justify-center gap-1.5" aria-label="Secret key permissions">
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Server and app keys can</span>
        {SDK_KEY_PERMISSIONS.map(scope => (
          <span
            key={scope}
            className="ae-mono rounded-full border px-2.5 py-0.5 text-[12px]"
            style={{ color: 'var(--ae-blue-ink)', borderColor: 'var(--ae-blue)', background: 'var(--ae-blue-tint)' }}
          >
            {scope}
          </span>
        ))}
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>· browser keys can only ingest for their site</span>
      </div>
    </div>
  );
}

function SdkPanel({
  row,
  busy,
  copied,
  origin,
  onOrigin,
  onMint,
  onRevoke,
  onCopy,
  onAck,
  tenantLive,
  testLabel,
  testResult,
  onTest,
}: {
  readonly row: FleetRow;
  readonly busy: string | null;
  readonly copied: string | null;
  readonly origin: string;
  readonly onOrigin: (value: string) => void;
  readonly onMint: () => void;
  readonly onRevoke: () => void;
  readonly onCopy: (value: string) => void;
  readonly onAck: (value: boolean) => void;
  readonly tenantLive: boolean;
  readonly testLabel: string;
  readonly testResult: string | null;
  readonly onTest: () => void;
}) {
  const { sdk, shown, record, site, issued, ready } = row;
  const publishable = sdk.keyKind === 'publishable';
  const siteId = shown?.siteId ?? site?.id ?? null;
  const siteLive = useSiteLive(publishable && issued ? siteId : null);
  const live = publishable ? siteLive.data?.live === true : tenantLive;
  const liveDetail = publishable
    ? siteLive.data
      ? live
        ? `site ${siteId} · loader reporting`
        : `site ${siteId} · ${siteLive.data.state.replace(/_/g, ' ')}`
      : `GET /v1/sdk/sites/${siteId ?? '{site_id}'}/live`
    : live
      ? 'first event received for this workspace'
      : (testResult ?? 'install the snippet, or send a test event');

  return (
    <Panel className="flex min-w-0 flex-col gap-3" style={{ padding: 'clamp(14px,2.6vw,20px)' }}>
      <div className="flex items-center gap-3">
        <BrandMark token={sdk.mark} size={32} markSize={20} />
        <span className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="text-[14px] font-medium">{sdk.name}</span>
          <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>
            {sdkKeyLabel(sdk)} · {publishable ? 'publishable, site-bound' : 'secret'}
          </span>
        </span>
      </div>

      {!issued && publishable && !site && (
        <label className="flex flex-col gap-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          Site address the {sdk.short} SDK runs on
          <input
            value={origin}
            onChange={e => onOrigin(e.target.value)}
            placeholder="https://www.example.com"
            data-testid={`site-origin-${sdk.id}`}
            className="ae-mono rounded border px-3 py-2 text-[13px] outline-none focus:border-[var(--ae-blue)]"
            style={{ background: 'var(--ae-raised)', borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}
          />
        </label>
      )}

      {!issued && (
        <PrimaryButton
          disabled={busy !== null || (publishable && !site && origin.trim() === '')}
          onClick={onMint}
          data-testid={`generate-key-${sdk.id}`}
        >
          {busy === sdk.id ? 'Issuing key…' : `Generate ${publishable ? 'publishable ' : ''}key for ${sdk.short}`}
        </PrimaryButton>
      )}

      {shown && (
        <div className="flex items-center gap-2 rounded-lg px-3 py-2.5" style={{ background: 'var(--ae-code)', color: 'var(--ae-code-ink)' }}>
          <code className="ae-mono flex-1 select-all break-all text-[12px] leading-snug" data-testid={`raw-key-${sdk.id}`}>{shown.key}</code>
          <button
            type="button"
            onClick={() => onCopy(shown.key)}
            className="ae-focus flex-none rounded px-2.5 py-1 text-[11px]"
            style={{ background: '#2a2a2f', color: '#e8e6e1' }}
          >
            {copied === sdk.id ? 'Copied' : 'Copy'}
          </button>
        </div>
      )}
      {shown && (
        <span className="text-[12px] leading-snug" style={{ color: 'var(--ae-amber)' }}>
          {publishable
            ? 'Publishable key, bound to this site · visible in your page, still shown here only once.'
            : sdk.platform === 'server'
              ? 'Secret key, server-side only · shown once, stored as a hash.'
              : 'Secret key for this app · shown once, stored as a hash.'}
        </span>
      )}
      {!shown && record && (
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          Key on record · the raw value was shown once when it was issued. If you did not store it, revoke it and issue a new one.
        </span>
      )}
      {issued && (
        <label className="flex cursor-pointer items-center gap-2.5 text-[13px]">
          <input
            type="checkbox"
            checked={ready}
            onChange={e => onAck(e.target.checked)}
            className="h-[18px] w-[18px] accent-[var(--ae-blue)]"
          />
          {shown ? 'I have stored this key securely' : 'I stored this key when it was issued'}
        </label>
      )}

      <pre
        className="ae-mono m-0 whitespace-pre-wrap break-all rounded-lg px-3.5 py-3 text-[12px] leading-relaxed"
        style={{ background: 'rgba(127,127,127,.08)', color: 'var(--ae-ink)' }}
      >
        {snippetFor(sdk, shown, siteId)}
      </pre>

      {issued && (
        <div
          className="flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5"
          style={{ background: live ? 'var(--ae-sage-tint)' : 'var(--ae-card)', borderColor: live ? 'var(--ae-sage)' : 'var(--ae-edge-soft)' }}
          data-testid={`sdk-live-${sdk.id}`}
        >
          <span className={live ? '' : 'ae-pulse'} style={{ color: live ? 'var(--ae-sage)' : 'var(--ae-faint)' }}>{live ? '●' : '○'}</span>
          <span className="flex flex-1 flex-col leading-snug">
            <span className="text-[13px] font-medium">{live ? 'live' : 'awaiting first signal'}</span>
            <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{liveDetail}</span>
          </span>
          {!live && !publishable && <LinkButton onClick={onTest}>{testLabel}</LinkButton>}
        </div>
      )}

      {issued && row.keyId && (
        <LinkButton className="self-start" onClick={onRevoke}>
          Revoke and generate a new key
        </LinkButton>
      )}
    </Panel>
  );
}
