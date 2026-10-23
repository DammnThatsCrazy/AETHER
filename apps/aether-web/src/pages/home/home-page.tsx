import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon, useQuery, useTheme } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import { BrandMark } from '@aether-app/components/brand-mark';
import { Bar, Eyebrow, InlineNotice, LinkButton, PrimaryButton, SecondaryButton, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { useActivationStatus } from '@aether-app/features/activation/use-activation';
import { useTenantReadiness } from '@aether-app/features/activation/use-tenant-readiness';
import { useAccessInventory, useCapabilityRiskFindings } from '@aether-app/features/agent-access';
import { useAuth } from '@aether-app/features/auth';
import { useTenantIntegrations, type TenantIntegrationItem } from '@aether-app/features/integrations';
import {
  useAnalyticsSummary,
  useOrganizationProfile,
  useTenantApiKeys,
} from '@aether-app/features/onboarding/use-workspace-setup';
import { api, type EconomicWindow } from '@aether-app/lib/api/endpoints';
import { campaignSummary, statusTone } from '@aether-app/pages/campaigns/campaign-model';
import { GRAPH_STAGES, stageStatuses } from '@aether-app/pages/onboarding/onboarding-model';
import {
  activityMoments,
  compact,
  economicKpis,
  needsAttention,
  num,
  platformLabel,
  readLastVisit,
  relative,
  shortStamp,
  sinceVisit,
  usdShort,
  writeLastVisit,
} from './home-model';

type Row = Record<string, unknown>;

const TONE_DOT: Record<Tone, string> = {
  blue: 'var(--ae-blue)',
  sage: 'var(--ae-sage)',
  amber: 'var(--ae-amber)',
  ember: 'var(--ae-ember)',
  solar: 'var(--ae-solar)',
  mute: 'var(--ae-mute)',
};

const EVENT_COLORS = ['var(--ae-blue)', 'var(--ae-solar)', 'var(--ae-ink)', 'var(--ae-sage)', 'var(--ae-violet)', 'var(--ae-teal)'];

const WINDOWS: ReadonlyArray<{ readonly value: EconomicWindow; readonly label: string }> = [
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
];

const NOT_AVAILABLE = 'Not available yet — this control has no backing read.';

interface Attention {
  readonly key: string;
  readonly title: string;
  readonly why: string;
  readonly tag: string;
  readonly tone: Tone;
  readonly action: string;
  readonly to: string;
}

function syncTone(item: TenantIntegrationItem): Tone {
  if (!item.enabled) return 'mute';
  if (needsAttention(item)) return 'amber';
  if (item.connected) return 'sage';
  return 'blue';
}

// ── Small layout pieces ──────────────────────────────────────────────────────

function ControlPill({ label, value, disabled, children, testId }: { readonly label: string; readonly value?: string; readonly disabled?: boolean; readonly children?: ReactNode; readonly testId?: string }) {
  return (
    <span
      className="ae-card inline-flex items-center gap-1 whitespace-nowrap rounded-xl px-3 py-2 text-[13px]"
      style={disabled ? { opacity: 0.6, cursor: 'not-allowed' } : undefined}
      title={disabled ? NOT_AVAILABLE : undefined}
      aria-disabled={disabled || undefined}
      data-testid={testId}
    >
      <span style={{ color: 'var(--ae-mute)' }}>{label}</span>
      {children ?? <span>{value}</span>}
    </span>
  );
}

function KpiTile({ label, value, delta, sub, testId, notReported }: { readonly label: string; readonly value: string; readonly delta?: ReactNode; readonly sub: ReactNode; readonly testId: string; readonly notReported?: boolean }) {
  return (
    <div
      className="flex min-w-0 flex-col gap-0.5 rounded-[14px] px-3.5 py-3"
      style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}
      data-testid={testId}
      data-not-reported={notReported ? 'true' : undefined}
    >
      <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{label}</span>
      <span className="text-[24px] font-medium tracking-[-0.4px]" style={notReported ? { color: 'var(--ae-faint)' } : undefined}>{value}</span>
      <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-faint)' }}>{delta ?? 'no prior period'}</span>
      <span className="truncate text-[11px]" style={{ color: 'var(--ae-mute)' }}>{sub}</span>
    </div>
  );
}

function StatChip({ value, label }: { readonly value: string; readonly label: string }) {
  return (
    <span className="flex flex-col rounded-[12px] px-3 py-2" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge)' }}>
      <span className="text-[18px] font-medium leading-tight">{value}</span>
      <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{label}</span>
    </span>
  );
}

function Muted({ children, className }: { readonly children: ReactNode; readonly className?: string }) {
  return <p className={`text-[13px] leading-relaxed ${className ?? ''}`} style={{ color: 'var(--ae-mute)' }}>{children}</p>;
}

function StoryCard({ eyebrow, eyebrowColor, wash, border, children, testId }: { readonly eyebrow: string; readonly eyebrowColor: string; readonly wash: string; readonly border: string; readonly children: ReactNode; readonly testId: string }) {
  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-[20px] px-5 py-[18px]" style={{ background: wash, border: `1px solid ${border}` }} data-testid={testId}>
      <Eyebrow style={{ color: eyebrowColor }}>{eyebrow}</Eyebrow>
      {children}
    </section>
  );
}

function InnerBox({ title, children }: { readonly title: string; readonly children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-[14px] px-3.5 py-3" style={{ background: 'var(--ae-card)', border: '1px solid var(--ae-edge)' }}>
      <Eyebrow>{title}</Eyebrow>
      {children}
    </div>
  );
}

function Rollup({ title, summary, rows, empty, testId }: { readonly title: string; readonly summary: ReactNode; readonly rows: readonly ReactNode[]; readonly empty: ReactNode; readonly testId: string }) {
  const [open, setOpen] = useState(false);
  const visible = open ? rows : rows.slice(0, 2);
  return (
    <section className="flex flex-col gap-1.5" data-testid={testId}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-1">
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Eyebrow style={{ color: 'var(--ae-amber)' }}>{title}</Eyebrow>
          <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>{summary}</span>
        </span>
        {rows.length > 2 && (
          <button type="button" onClick={() => setOpen(v => !v)} className="ae-focus inline-flex items-center gap-1 text-[12px]" style={{ color: 'var(--ae-blue-ink)' }} aria-expanded={open}>
            {open ? 'Hide' : `Show all ${rows.length}`}
            <Icon name={open ? 'circle-minus' : 'circle-plus'} decorative size="sm" />
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <div className="ae-card rounded-[14px] px-4 py-3 text-[13px]" style={{ color: 'var(--ae-mute)' }}>{empty}</div>
      ) : (
        visible.map((row, i) => (
          <div key={i} className="ae-card flex min-w-0 items-center gap-3 rounded-[14px] px-4 py-2.5 text-[13px]">{row}</div>
        ))
      )}
    </section>
  );
}

function DomainTile({ title, value, unit, action, onClick, accent }: { readonly title: string; readonly value: string; readonly unit: string; readonly action: string; readonly onClick: () => void; readonly accent: boolean }) {
  return (
    <div
      className="flex min-w-0 flex-col gap-1 rounded-[18px] px-4 py-3.5"
      style={{ background: accent ? 'var(--ae-blue-tint)' : 'var(--ae-glass-card)', border: `1px solid ${accent ? 'var(--ae-blue)' : 'var(--ae-edge)'}`, borderColor: accent ? 'color-mix(in srgb, var(--ae-blue) 30%, transparent)' : 'var(--ae-edge)' }}
    >
      <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{title}</span>
      <span className="flex items-baseline gap-2">
        <span className="text-[24px] font-medium">{value}</span>
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{unit}</span>
      </span>
      <span><LinkButton onClick={onClick}>{action} →</LinkButton></span>
    </div>
  );
}

const ROW_GRID = 'minmax(170px,1.8fr) 84px 76px 76px 70px 60px 64px';
const tableStyle: CSSProperties = { gridTemplateColumns: ROW_GRID };

/**
 * Home — "what changed across your network" (Claude Design frame: Aether
 * Home). Every number is a read from an existing tenant endpoint; a figure
 * the backend does not report is labelled "not reported", and a control with
 * no backing read is shown disabled rather than pretending to filter.
 */
export function HomePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  const org = useOrganizationProfile();
  const activation = useActivationStatus();
  const readiness = useTenantReadiness();
  const summary = useAnalyticsSummary({ pollInterval: 60_000 });
  const integrations = useTenantIntegrations();
  const keys = useTenantApiKeys();
  const inventory = useAccessInventory();
  const findings = useCapabilityRiskFindings({ limit: 20 });
  const [timeWindow, setWindow] = useState<EconomicWindow>('7d');
  const economic = useQuery({
    key: `home:economic:${timeWindow}`,
    fetcher: () => api.economic.overview(timeWindow),
    staleTime: 60_000,
  });
  const campaigns = useQuery({
    key: 'home:campaigns',
    fetcher: () => api.campaigns.list({ limit: 8 }),
    staleTime: 60_000,
  });

  // Since-you-last-visited: the previous visit is read once, then this visit is recorded.
  const visitScope = org.data?.tenant_id ?? user?.id ?? 'workspace';
  const [lastVisit] = useState(() => readLastVisit(visitScope));
  useEffect(() => {
    writeLastVisit(visitScope, Date.now());
  }, [visitScope]);

  const items = useMemo(() => integrations.data?.items ?? [], [integrations.data]);
  const connectedCount = items.filter(i => i.connected).length;
  const failingCount = items.filter(needsAttention).length;
  const lastSync = items
    .map(i => i.last_synced_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);
  const statuses = stageStatuses(readiness.data?.checks);
  const passed = statuses.filter(s => s === 'passed' || s === 'not_applicable').length;
  const graphReady = readiness.data?.ready === true;
  const activationComplete = activation.data?.state === 'complete';
  const rawCampaigns = useMemo(() => (campaigns.data?.campaigns ?? []) as Row[], [campaigns.data]);
  const campaignRows = useMemo(() => rawCampaigns.map(campaignSummary), [rawCampaigns]);
  const campaignCreated = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of rawCampaigns) {
      const id = String(c['id'] ?? c['campaign_id'] ?? '');
      if (id && typeof c['created_at'] === 'string') m.set(id, c['created_at']);
    }
    return m;
  }, [rawCampaigns]);
  const platforms = new Set(campaignRows.map(c => c.platform).filter(Boolean)).size;
  const kpis = economicKpis(economic.data);
  const windowLabel = WINDOWS.find(w => w.value === timeWindow)?.label.toLowerCase() ?? timeWindow;
  const campaignSpend = campaignRows.reduce<number | null>((n, c) => (c.cost === null ? n : (n ?? 0) + c.cost), null);

  const eventMix = useMemo(() => {
    const top = summary.data?.top_event_types ?? [];
    const rows = top
      .map(t => ({ label: String(t['event_type'] ?? t['type'] ?? t['name'] ?? 'event'), count: num(t['count'] ?? t['total']) ?? 0 }))
      .filter(r => r.count > 0)
      .sort((a, b) => b.count - a.count);
    const total = rows.reduce((n, r) => n + r.count, 0);
    const head = rows.slice(0, 3);
    const rest = rows.slice(3).reduce((n, r) => n + r.count, 0);
    const shown = rest > 0 ? [...head, { label: 'Other', count: rest }] : head;
    return { rows, shown, total };
  }, [summary.data]);

  const attention: Attention[] = useMemo(() => {
    const out: Attention[] = [];
    if (activation.data && !activationComplete) {
      out.push({
        key: 'activation',
        title: 'Finish workspace setup',
        why: activation.data.waiting_reason ? activation.data.waiting_reason.replace(/_/g, ' ') : 'Activation is not complete yet.',
        tag: 'setup',
        tone: 'blue',
        action: 'Continue setup',
        to: '/activation',
      });
    }
    for (const item of items) {
      if (needsAttention(item)) {
        out.push({
          key: `sync:${item.id}`,
          title: `${item.display_name} sync needs attention`,
          why: `Last status: ${item.sync_status.replace(/_/g, ' ')} · synced ${relative(item.last_synced_at)}`,
          tag: 'data delayed',
          tone: 'amber',
          action: 'Fix connection',
          to: `/settings/integrations?family=${encodeURIComponent(item.family)}`,
        });
      }
    }
    for (const check of readiness.data?.checks ?? []) {
      if (check.status === 'failed') {
        out.push({
          key: `check:${check.name}`,
          title: `${check.name.replace(/_/g, ' ')} failed`,
          why: 'A graph readiness check did not pass on its last run.',
          tag: 'check failed',
          tone: 'ember',
          action: 'Review data quality',
          to: '/data-quality',
        });
      }
    }
    return out.slice(0, 5);
  }, [activation.data, activationComplete, items, readiness.data]);

  const since = lastVisit !== null ? sinceVisit(lastVisit, rawCampaigns, items, readiness.data?.recorded_at) : null;
  const moments = activityMoments(campaignRows, campaignCreated, items, readiness.data?.recorded_at, graphReady);

  const workspaceName = org.data?.name ?? user?.displayName ?? 'Your workspace';
  const keyCount = (keys.data?.api_keys ?? []).length;
  const graphHeadline = graphReady
    ? 'Your graph is verified and current'
    : summary.data?.total_events
      ? 'Your graph is building from live events'
      : 'Your graph is waiting for its first events';
  const subline = attention.length === 0
    ? 'Nothing needs your attention right now'
    : `${attention.length} thing${attention.length === 1 ? ' is' : 's are'} worth your attention`;

  const inv = inventory.data;
  const invCounts = inv?.counts;
  const findingItems = findings.data?.items ?? [];
  const byLevel = findings.data?.counts.by_risk_level ?? {};
  const highRisk = (byLevel['critical'] ?? 0) + (byLevel['high'] ?? 0);

  return (
    <GlassPage>
      <div className="flex min-w-0 flex-col gap-[18px]" data-testid="aether-home">
        {/* 1 · Title */}
        <div className="flex flex-col gap-[5px]">
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Home · {workspaceName}</span>
          <h1 className="text-[28px] font-medium leading-tight tracking-[-0.56px]">Here is what changed across your network</h1>
          <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }} data-testid="home-subline">{subline}</span>
        </div>

        {/* 2 · Lens / Time / Perspective / Scope bar */}
        <div className="flex flex-wrap items-center gap-2" data-testid="home-controls">
          <ControlPill label="Lens" value="Value" disabled testId="home-control-lens" />
          <ControlPill label="Time" testId="home-control-time">
            <select
              aria-label="Time window for revenue and ROAS"
              value={timeWindow}
              onChange={e => setWindow(e.target.value as EconomicWindow)}
              className="ae-focus cursor-pointer bg-transparent text-[13px] outline-none"
              title="Applies to revenue and ROAS. Event totals are always the last 24 hours."
            >
              {WINDOWS.map(w => <option key={w.value} value={w.value}>{w.label}</option>)}
            </select>
          </ControlPill>
          <ControlPill label="Perspective" value="Network" disabled testId="home-control-perspective" />
          <span
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl px-3 py-2 text-[13px]"
            style={{ background: 'var(--ae-blue-tint)', border: '1px solid var(--ae-edge)' }}
            data-testid="home-control-scope"
          >
            Scope: Workspace
          </span>
          <span className="ae-card inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-2 text-[13px]" data-testid="home-live">
            <span className="h-[7px] w-[7px] rounded-full" style={{ background: lastSync ? 'var(--ae-sage)' : 'var(--ae-faint)' }} />
            {lastSync ? `Live · ${relative(lastSync)}` : 'No syncs yet'}
          </span>
          <button
            type="button"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="ae-card ae-focus whitespace-nowrap rounded-full px-3 py-2 text-[13px]"
          >
            {theme === 'dark' ? 'Stone' : 'Graphite'}
          </button>
        </div>

        {/* 3 · Query bar + interpretation (no backing read: disabled, never a fake interpretation) */}
        <div className="flex flex-col gap-2.5" data-testid="home-query">
          <label className="ae-card flex items-center gap-2.5 rounded-[18px] px-4 py-3" style={{ opacity: 0.75 }} title={NOT_AVAILABLE}>
            <Icon name="search" decorative size="sm" className="opacity-60" />
            <input
              type="text"
              disabled
              aria-label="Ask across your network"
              placeholder="Ask across your network — natural-language questions are not available yet"
              className="min-w-0 flex-1 cursor-not-allowed bg-transparent text-[14px] outline-none"
            />
          </label>
          <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
            <span className="mr-1" style={{ color: 'var(--ae-mute)' }}>Interpreted as</span>
            <span className="rounded-full px-2.5 py-1" style={{ border: '1px dashed var(--ae-edge)', color: 'var(--ae-mute)' }}>
              nothing yet — query interpretation is not available
            </span>
          </div>
        </div>

        {/* 4 · Since you last visited */}
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1.5 text-[12px]" style={{ color: 'var(--ae-mute)' }} data-testid="home-since">
          <span className="text-[11px] font-medium uppercase tracking-[.04em]">Since you last visited</span>
          {since === null ? (
            <span>This is your first visit on this device — changes since your last visit appear here next time.</span>
          ) : (
            <>
              <span>{shortStamp(lastVisit)}</span>
              {since.campaignsImported + since.connectionsSynced === 0 && !since.checksRan ? (
                <span>No new imports, syncs or checks</span>
              ) : (
                <>
                  {since.campaignsImported > 0 && <span>{since.campaignsImported} campaign{since.campaignsImported === 1 ? '' : 's'} imported</span>}
                  {since.connectionsSynced > 0 && <span>{since.connectionsSynced} connection{since.connectionsSynced === 1 ? '' : 's'} synced</span>}
                  {since.checksRan && <span>graph checks ran</span>}
                </>
              )}
              {since.connectionsFailing > 0 && <span style={{ color: 'var(--ae-amber)' }}>{since.connectionsFailing} connection{since.connectionsFailing === 1 ? '' : 's'} failing</span>}
            </>
          )}
        </div>

        {/* 5 · KPI tiles */}
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }} data-testid="home-kpis">
          <KpiTile
            testId="kpi-revenue"
            label="Revenue"
            value={kpis?.revenue != null ? usdShort(kpis.revenue) : '—'}
            notReported={kpis?.revenue == null}
            sub={economic.error ? 'unavailable right now' : !kpis ? 'loading…' : kpis.revenue != null ? `attributed · ${windowLabel}` : kpis.failed ? 'computation failed' : 'no attribution credits yet'}
          />
          <KpiTile testId="kpi-orders" label="Orders" value="—" notReported sub="not reported" delta=" " />
          <KpiTile testId="kpi-new-users" label="New users" value="—" notReported sub="not reported" delta=" " />
          <KpiTile
            testId="kpi-roas"
            label="Blended ROAS"
            value={kpis?.roas != null ? `${kpis.roas.toFixed(1)}x` : '—'}
            notReported={kpis?.roas == null}
            sub={economic.error ? 'unavailable right now' : !kpis ? 'loading…' : kpis.spend != null ? `ad spend ${usdShort(kpis.spend)}` : 'no spend reported'}
          />
          <KpiTile testId="kpi-aov" label="Average order" value="—" notReported sub="not reported" delta=" " />
          <KpiTile testId="kpi-repeat" label="Repeat purchase" value="—" notReported sub="not reported" delta=" " />
        </div>
        {summary.error && <InlineNotice tone="amber">Event totals are unavailable right now.</InlineNotice>}

        {/* 6 · Insight hero */}
        <div
          className="flex min-w-0 flex-col gap-4 rounded-3xl px-[clamp(16px,2vw,24px)] py-[22px]"
          style={{ background: 'var(--ae-solar-wash)', border: '1px solid color-mix(in srgb, var(--ae-solar) 45%, transparent)', backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)' }}
          data-testid="home-hero"
        >
          <div className="flex flex-wrap items-center justify-between gap-2.5">
            <span className="flex items-center gap-2">
              <span className="rounded-full px-2.5 py-0.5 text-[12px] font-medium" style={{ background: 'var(--ae-solar)', color: 'var(--ae-chip-on-ink)' }}>insight</span>
              <span className="text-[13px]">graph · {graphReady ? 'verified' : activationComplete ? 'activated · building' : 'setting up'}</span>
            </span>
            <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              {readiness.data?.recorded_at ? `updated ${relative(readiness.data.recorded_at)}` : 'not checked yet'}
            </span>
          </div>

          <div className="grid gap-6" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(340px, 100%), 1fr))' }}>
            <div className="flex min-w-0 flex-col gap-3">
              <h2 className="text-[24px] font-medium leading-tight tracking-[-0.4px]">{graphHeadline}</h2>
              <span className="text-[14px]">
                {connectedCount} connected source{connectedCount === 1 ? '' : 's'} · {keyCount} SDK key{keyCount === 1 ? '' : 's'} · {passed}/{GRAPH_STAGES.length} graph checks passed
              </span>
              <div className="flex flex-col gap-0.5">
                <Eyebrow style={{ color: 'var(--ae-solar-ink)' }}>Why it matters</Eyebrow>
                <span className="text-[13px] leading-snug" style={{ color: 'var(--ae-mute)' }}>
                  {graphReady
                    ? 'Every figure on this page is drawn from a graph that passed its readiness checks.'
                    : 'Figures on this page stay partial until every readiness check passes.'}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatChip value={compact(summary.data?.unique_users ?? null)} label="People seen · 24h" />
                <StatChip value={campaigns.data ? `${compact(campaigns.data.total)}${campaigns.data.has_more ? '+' : ''}` : '—'} label="Campaigns" />
                <StatChip value={kpis?.revenue != null ? usdShort(kpis.revenue) : '—'} label="Value" />
              </div>
              <div className="flex flex-wrap gap-1.5" data-testid="home-stages">
                {GRAPH_STAGES.map((stage, i) => {
                  const s = statuses[i] ?? 'waiting';
                  const color = s === 'passed' ? 'var(--ae-sage)' : s === 'failed' ? 'var(--ae-ember)' : s === 'running' ? 'var(--ae-blue-ink)' : 'var(--ae-mute)';
                  return (
                    <span
                      key={stage.check}
                      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px]"
                      style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge)' }}
                      data-stage={stage.check}
                      data-stage-status={s}
                      title={s === 'unknown' ? 'not reported' : s.replace('_', ' ')}
                    >
                      <span className="h-[6px] w-[6px] rounded-full" style={{ background: color }} />
                      {stage.label}
                    </span>
                  );
                })}
              </div>
              {readiness.error && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Readiness checks are temporarily unavailable.</span>}
            </div>

            <div className="flex min-w-0 flex-col gap-2">
              <Eyebrow>What is arriving · last 24h</Eyebrow>
              {eventMix.total > 0 ? (
                <>
                  <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-[5px]">
                    {eventMix.shown.map((r, i) => (
                      <div key={r.label} style={{ flex: r.count, background: r.label === 'Other' ? 'var(--ae-faint)' : EVENT_COLORS[i % EVENT_COLORS.length] }} />
                    ))}
                  </div>
                  <div className="flex flex-col gap-1">
                    {eventMix.shown.map((r, i) => (
                      <div key={r.label} className="flex items-center justify-between gap-2 text-[12px]">
                        <span className="flex items-center gap-1.5">
                          <span className="h-[8px] w-[8px] rounded-full" style={{ background: r.label === 'Other' ? 'var(--ae-faint)' : EVENT_COLORS[i % EVENT_COLORS.length] }} />
                          {r.label}
                        </span>
                        <span className="ae-mono" style={{ color: 'var(--ae-mute)' }}>
                          {Math.round((r.count / eventMix.total) * 100)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <Muted>No events in the last 24 hours. Install an SDK or connect a source and the mix of event types shows here.</Muted>
              )}
            </div>
          </div>

          {/* Graph growth — current totals; no time series is reported, so no chart is drawn. */}
          <div className="flex flex-col gap-3 rounded-[18px] px-4 py-4" style={{ background: 'var(--ae-card)', border: '1px solid var(--ae-edge)' }} data-testid="home-growth">
            <div className="flex flex-col">
              <Eyebrow>Graph growth</Eyebrow>
              <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>events and identities · last 24 hours</span>
            </div>
            <div className="flex flex-wrap gap-x-8 gap-y-2">
              {[
                { label: 'events', value: summary.data?.total_events, color: 'var(--ae-solar)' },
                { label: 'people seen', value: summary.data?.unique_users, color: 'var(--ae-blue)' },
                { label: 'sessions', value: summary.data?.total_sessions, color: 'var(--ae-sage)' },
              ].map(m => (
                <span key={m.label} className="flex flex-col">
                  <span className="flex items-center gap-1.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                    <span className="h-[2px] w-[10px]" style={{ background: m.color }} />
                    {m.label}
                  </span>
                  <span className="text-[22px] font-medium">{compact(m.value ?? null)}</span>
                </span>
              ))}
            </div>
            <div className="rounded-[12px] px-4 py-6 text-center text-[13px]" style={{ border: '1px dashed var(--ae-edge)', color: 'var(--ae-mute)' }}>
              Growth over time is not reported yet — the graph exposes current totals only, so no trend line is drawn.
            </div>
          </div>

          {/* Representative journeys — no workspace-level journey read exists. */}
          <div className="flex flex-col gap-2" data-testid="home-journeys">
            <Eyebrow>Representative journeys</Eyebrow>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-[14px] px-4 py-3" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge)' }}>
              <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Representative journeys are not reported for the whole workspace yet. Open one person's path from Journeys.</span>
              <LinkButton onClick={() => void navigate('/journeys')}>Open journeys →</LinkButton>
            </div>
          </div>

          {/* Activity — dated moments the reads carry */}
          <div className="flex flex-col gap-2.5" data-testid="home-activity">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Eyebrow>Activity</Eyebrow>
              {moments.length > 0 && (
                <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                  {shortStamp(moments[0]?.at)} to {shortStamp(moments.at(-1)?.at)} · {moments.length} moment{moments.length === 1 ? '' : 's'}
                </span>
              )}
            </div>
            {moments.length === 0 ? (
              <Muted>No activity recorded yet. Imports, syncs and readiness runs appear here as they happen.</Muted>
            ) : (
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
                {moments.map(m => (
                  <div key={m.key} className="flex min-w-0 flex-col gap-0.5 border-t-2 pt-2" style={{ borderColor: TONE_DOT[m.tone] }}>
                    <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{shortStamp(m.at)}</span>
                    <span className="truncate text-[13px]">{m.title}</span>
                    <span className="truncate text-[12px]" style={{ color: 'var(--ae-mute)' }}>{m.detail}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2.5 border-t pt-3" style={{ borderColor: 'color-mix(in srgb, var(--ae-solar) 40%, transparent)' }}>
            <span className="flex flex-wrap gap-x-3.5 gap-y-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              <span>Scope · workspace</span>
              <span>Time · last 24 hours</span>
              <span>evidence from tenant readiness checks</span>
            </span>
            <PrimaryButton onClick={() => void navigate('/explore')}>Open the graph →</PrimaryButton>
          </div>
        </div>

        {/* 7 · Campaigns */}
        <section className="ae-card flex min-w-0 flex-col gap-2.5 rounded-[20px] px-[clamp(14px,2vw,24px)] py-[18px]" data-testid="home-campaigns">
          <div className="flex flex-wrap items-baseline justify-between gap-2.5">
            <span className="flex flex-wrap items-baseline gap-2.5">
              <Eyebrow style={{ color: 'var(--ae-blue-ink)' }}>What is happening</Eyebrow>
              <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                {campaigns.data
                  ? `${campaigns.data.total}${campaigns.data.has_more ? '+' : ''} campaign${campaigns.data.total === 1 && !campaigns.data.has_more ? '' : 's'}${platforms > 0 ? ` across ${platforms} platform${platforms === 1 ? '' : 's'}` : ''} · imported from your systems`
                  : 'Campaigns'}
              </span>
            </span>
            <LinkButton onClick={() => void navigate('/campaigns')}>All campaigns →</LinkButton>
          </div>
          {campaigns.error && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Campaigns are unavailable right now.</span>}
          {campaigns.data && campaignRows.length === 0 && (
            <Muted>No campaigns yet. Aether imports campaigns from connected ad, email and commerce systems; it never creates them.</Muted>
          )}
          {campaignRows.length > 0 && (
            <>
              <div className="overflow-x-auto">
                <div className="flex min-w-[660px] flex-col">
                  <div className="ae-eyebrow grid gap-3 px-1 pb-1.5" style={tableStyle}>
                    <span>Campaign</span>
                    <span>Status</span>
                    <span className="text-right">Spend</span>
                    <span className="text-right">Reach</span>
                    <span className="text-right">Conv.</span>
                    <span className="text-right">ROAS</span>
                    <span className="text-right">Trend</span>
                  </div>
                  {campaignRows.map((c, index) => {
                    const platformName = platformLabel(c.platform ?? '', items);
                    const roas = c.roas ?? (c.revenue !== null && c.cost !== null && c.cost > 0 ? c.revenue / c.cost : null);
                    return (
                      <button
                        key={c.id || index}
                        type="button"
                        disabled={!c.id}
                        onClick={() => void navigate(`/campaigns/${encodeURIComponent(c.id)}`)}
                        className="ae-focus grid items-center gap-3 border-t px-1 py-[7px] text-left text-[13px] hover:bg-[var(--ae-glass-card)]"
                        style={{ ...tableStyle, borderColor: 'var(--ae-edge)' }}
                        data-campaign-row={c.id}
                      >
                        <span className="flex min-w-0 items-center gap-2.5">
                          <BrandMark token={c.platform || 'aether'} label={platformName || 'Aether'} size={22} markSize={14} />
                          <span className="flex min-w-0 flex-col leading-tight">
                            <span className="truncate">{c.name}</span>
                            <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{platformName || 'source unknown'}</span>
                          </span>
                        </span>
                        <span className="flex items-center gap-1.5 text-[12px]">
                          <span className="h-[7px] w-[7px] rounded-full" style={{ background: TONE_DOT[statusTone(c.status)] }} />
                          {c.status}
                        </span>
                        <span className="ae-mono text-right text-[12px]">{c.cost !== null ? usdShort(c.cost) : '—'}</span>
                        <span className="ae-mono text-right text-[12px]">{compact(c.reached)}</span>
                        <span className="ae-mono text-right text-[12px]">{compact(c.converted)}</span>
                        <span className="ae-mono text-right text-[12px]">{roas !== null ? `${roas.toFixed(1)}x` : '—'}</span>
                        <span className="ae-mono text-right text-[12px]" style={{ color: 'var(--ae-faint)' }} title="Per-campaign trend is not reported">—</span>
                      </button>
                    );
                  })}
                </div>
              </div>
              <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }} data-testid="home-campaigns-note">
                — not reported: {campaignRows.every(c => c.cost === null) ? 'spend and ROAS are not reported by these sources; ' : ''}trend lines need a per-campaign series, which is not reported yet.
              </span>
            </>
          )}
        </section>

        {/* 8 · Story row: Relationships · Risk · Needs attention */}
        <div className="grid gap-[18px]" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(280px, 100%), 1fr))' }}>
          <StoryCard eyebrow="Relationships" eyebrowColor="var(--ae-blue-ink)" wash="var(--ae-blue-tint)" border="color-mix(in srgb, var(--ae-blue) 30%, transparent)" testId="home-relationships">
            {inventory.error ? (
              <Muted>Relationship totals are unavailable right now.</Muted>
            ) : !inv ? (
              <Muted>Loading relationships…</Muted>
            ) : inv.observed_any === false ? (
              <Muted>No agent relationships observed yet. They appear once agents connect to servers and capabilities.</Muted>
            ) : !inv.summary_known ? (
              <Muted>Relationship totals are not known yet{inv.missing_inputs.length ? ` — waiting on ${inv.missing_inputs.join(', ').replace(/_/g, ' ')}` : ''}.</Muted>
            ) : (
              <>
                <h3 className="text-[18px] font-medium leading-snug">
                  {compact(invCounts?.agents ?? null)} agents reach {compact(invCounts?.capabilities ?? null)} capabilities
                </h3>
                {inv.summary && <span className="text-[13px] leading-snug" style={{ color: 'var(--ae-mute)' }}>{inv.summary}</span>}
                <InnerBox title="Relationships by kind">
                  {(() => {
                    const kinds = [
                      { label: 'connects to', v: invCounts?.edges_connects_to ?? null, c: 'var(--ae-blue)' },
                      { label: 'exposes', v: invCounts?.edges_exposes ?? null, c: 'var(--ae-blue)' },
                      { label: 'authorized for', v: invCounts?.edges_authorized_for ?? null, c: 'var(--ae-solar)' },
                    ];
                    const total = kinds.reduce((n, k) => n + (k.v ?? 0), 0);
                    return kinds.map(k => (
                      <div key={k.label} className="flex flex-col gap-1">
                        <span className="flex justify-between text-[12px]"><span>{k.label}</span><span className="ae-mono">{compact(k.v)}</span></span>
                        <Bar value={k.v !== null && total > 0 ? (k.v / total) * 100 : null} color={k.c} height={3} />
                      </div>
                    ));
                  })()}
                </InnerBox>
                <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                  Scope · capability graph · {inv.complete ? 'complete' : 'partial'} evidence
                </span>
              </>
            )}
            <span className="mt-auto"><LinkButton onClick={() => void navigate('/relationships')}>Explore relationships →</LinkButton></span>
          </StoryCard>

          <StoryCard eyebrow={highRisk > 0 ? 'Risk · elevated' : 'Risk'} eyebrowColor="var(--ae-ember)" wash="var(--ae-ember-tint)" border="color-mix(in srgb, var(--ae-ember) 30%, transparent)" testId="home-risk">
            {findings.error ? (
              <Muted>Risk findings are unavailable right now.</Muted>
            ) : !findings.data ? (
              <Muted>Loading risk findings…</Muted>
            ) : findingItems.length === 0 ? (
              <Muted>No capability risk findings. New findings from agent access appear here.</Muted>
            ) : (
              <>
                <h3 className="text-[18px] font-medium leading-snug">{findingItems[0]?.summary ?? findingItems[0]?.code.replace(/_/g, ' ')}</h3>
                <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                  {findings.data.counts.total ?? findingItems.length} finding{(findings.data.counts.total ?? findingItems.length) === 1 ? '' : 's'}
                  {findings.data.counts.scope === 'scanned_window_only' ? ' in the scanned window' : ''}
                  {highRisk > 0 ? ` · ${highRisk} high or critical` : ''}
                </span>
                <InnerBox title="Latest findings">
                  {findingItems.slice(0, 3).map((f, i) => (
                    <div key={`${f.code}:${f.capability_id ?? i}`} className="flex items-baseline justify-between gap-2 text-[12px]">
                      <span className="min-w-0 truncate">{f.code.replace(/_/g, ' ')}</span>
                      <TonePill tone={/critical|high/i.test(f.risk_level ?? '') ? 'ember' : /medium/i.test(f.risk_level ?? '') ? 'amber' : 'mute'}>{f.risk_level ?? 'unrated'}</TonePill>
                    </div>
                  ))}
                </InnerBox>
              </>
            )}
            <span className="mt-auto"><LinkButton tone="ember" onClick={() => void navigate('/risk')}>Open risk →</LinkButton></span>
          </StoryCard>

          <section className="ae-card flex min-w-0 flex-col gap-3 rounded-[20px] px-5 py-[18px]" data-testid="home-attention">
            <div className="flex items-baseline justify-between">
              <Eyebrow style={{ color: 'var(--ae-amber)' }}>Needs your attention</Eyebrow>
              <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>{attention.length}</span>
            </div>
            {attention.length === 0 && <Muted>Nothing needs you right now.</Muted>}
            {attention.map(item => (
              <div
                key={item.key}
                className="flex flex-col gap-1.5 rounded-[14px] border px-3.5 py-3"
                style={{
                  background: item.tone === 'ember' ? 'var(--ae-ember-tint)' : item.tone === 'amber' ? 'var(--ae-amber-tint)' : 'var(--ae-blue-tint)',
                  borderColor: 'var(--ae-edge)',
                }}
              >
                <span className="flex items-start justify-between gap-2 text-[14px] leading-snug">
                  <span className="flex items-start gap-2">
                    <span className="mt-1.5 h-[7px] w-[7px] flex-none rounded-full" style={{ background: TONE_DOT[item.tone] }} />
                    {item.title}
                  </span>
                  <span className="flex-none text-[11px]" style={{ color: TONE_DOT[item.tone] }}>{item.tag}</span>
                </span>
                <span className="pl-[15px] text-[12px] leading-snug" style={{ color: 'var(--ae-mute)' }}>{item.why}</span>
                <span className="pl-[15px]">
                  <SecondaryButton onClick={() => void navigate(item.to)}>{item.action}</SecondaryButton>
                </span>
              </div>
            ))}
          </section>
        </div>

        {/* 9 · Rollups */}
        <div className="flex flex-col gap-5">
          <Rollup
            testId="home-connections"
            title="Performance"
            summary={
              <>
                <span>{campaigns.data ? `${campaigns.data.total}${campaigns.data.has_more ? '+' : ''} campaigns` : 'campaigns —'}</span>
                <span>{campaignSpend !== null ? `${usdShort(campaignSpend)} spend` : 'spend not reported'}</span>
                {kpis?.roas != null && <span style={{ color: 'var(--ae-sage)' }}>{kpis.roas.toFixed(1)}x ROAS</span>}
                <span>{integrations.data ? `${connectedCount} connector${connectedCount === 1 ? '' : 's'}` : integrations.error ? 'Connections are unavailable right now.' : 'connectors —'}</span>
                {failingCount > 0 && <span style={{ color: 'var(--ae-amber)' }}>{failingCount} delayed</span>}
              </>
            }
            empty={
              integrations.data ? (
                <span className="flex flex-wrap items-center gap-2">No sources connected yet. <LinkButton onClick={() => void navigate('/activation')}>Connect a source →</LinkButton></span>
              ) : integrations.error ? 'Connector status is unavailable.' : 'Loading connectors…'
            }
            rows={items.map(item => (
              <>
                <BrandMark token={item.family} label={item.display_name} size={22} markSize={13} />
                <span className="truncate">{item.display_name}</span>
                <span className="hidden text-[12px] sm:inline" style={{ color: 'var(--ae-mute)' }}>connector</span>
                <span className="ae-mono ml-auto whitespace-nowrap text-[11px]" style={{ color: 'var(--ae-mute)' }}>synced {relative(item.last_synced_at)}</span>
                <TonePill tone={syncTone(item)}>{item.enabled ? item.sync_status.replace(/_/g, ' ') : 'disabled'}</TonePill>
              </>
            ))}
          />

          <Rollup
            testId="home-rollup-people"
            title="People and agents"
            summary={
              <>
                <span>{compact(summary.data?.unique_users ?? null)} people seen · 24h</span>
                <span>{compact(summary.data?.total_sessions ?? null)} sessions</span>
                <span>{inv?.summary_known ? `${compact(invCounts?.agents ?? null)} agents observed` : 'agents not known yet'}</span>
              </>
            }
            empty="No people or agents observed yet."
            rows={[
              ...(summary.data?.unique_users ? [{ k: 'People seen', d: 'profiles · last 24h', v: compact(summary.data.unique_users) }] : []),
              ...(summary.data?.total_sessions ? [{ k: 'Sessions', d: 'last 24h', v: compact(summary.data.total_sessions) }] : []),
              ...(inv?.summary_known && invCounts?.agents ? [{ k: 'Agents', d: 'observed in the capability graph', v: compact(invCounts.agents) }] : []),
              ...(inv?.summary_known && invCounts?.authorizations_active ? [{ k: 'Active authorizations', d: 'agent grants in force', v: compact(invCounts.authorizations_active) }] : []),
            ].map(r => (
              <>
                <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: 'var(--ae-sage)' }} />
                <span>{r.k}</span>
                <span className="hidden truncate text-[12px] sm:inline" style={{ color: 'var(--ae-mute)' }}>{r.d}</span>
                <span className="ae-mono ml-auto whitespace-nowrap text-[12px]">{r.v}</span>
              </>
            ))}
          />

          <Rollup
            testId="home-rollup-where"
            title="Where and what"
            summary={
              <>
                <span>{eventMix.rows.length} event type{eventMix.rows.length === 1 ? '' : 's'} · 24h</span>
                <span>locations not reported on Home</span>
              </>
            }
            empty="No events in the last 24 hours."
            rows={eventMix.rows.map(r => (
              <>
                <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: 'var(--ae-sage)' }} />
                <span className="truncate">{r.label}</span>
                <span className="hidden text-[12px] sm:inline" style={{ color: 'var(--ae-mute)' }}>event type</span>
                <span className="ae-mono ml-auto whitespace-nowrap text-[12px]">{compact(r.count)} · {Math.round((r.count / eventMix.total) * 100)}%</span>
              </>
            ))}
          />
        </div>

        {/* 10 · Domain tiles */}
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))' }} data-testid="home-domains">
          <DomainTile accent title="People and syndicates" value={compact(summary.data?.unique_users ?? null)} unit="people seen · 24h" action="Explore" onClick={() => void navigate('/users')} />
          <DomainTile accent title="Agents" value={inv?.summary_known ? compact(invCounts?.agents ?? null) : '—'} unit={inv?.summary_known ? 'observed' : 'not known yet'} action="Explore" onClick={() => void navigate('/agent-access')} />
          <DomainTile accent title="Campaigns and communications" value={campaigns.data ? `${compact(campaigns.data.total)}${campaigns.data.has_more ? '+' : ''}` : '—'} unit="imported" action="Explore" onClick={() => void navigate('/campaigns')} />
          <DomainTile accent={false} title="Value and outcomes" value={kpis?.revenue != null ? usdShort(kpis.revenue) : '—'} unit={kpis?.revenue != null ? `attributed · ${windowLabel}` : 'not reported yet'} action="Understand value" onClick={() => void navigate('/value-review')} />
        </div>
      </div>
    </GlassPage>
  );
}
