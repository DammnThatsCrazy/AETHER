import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useTheme } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import { BrandMark } from '@aether-app/components/brand-mark';
import { Bar, Eyebrow, InlineNotice, LinkButton, MetricTile, PrimaryButton, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { DecisionIntelligencePanel } from '@aether-app/components/decision-intelligence-panel';
import { OutcomeLedgerPanel } from '@aether-app/components/outcome-ledger-panel';
import { useActivationStatus } from '@aether-app/features/activation/use-activation';
import { useTenantReadiness } from '@aether-app/features/activation/use-tenant-readiness';
import { useAuth } from '@aether-app/features/auth';
import { useTenantIntegrations, type TenantIntegrationItem } from '@aether-app/features/integrations';
import { ModelSelectionPanel } from '@aether-app/features/model-selection';
import {
  useAnalyticsSummary,
  useOrganizationProfile,
  useTenantApiKeys,
} from '@aether-app/features/onboarding/use-workspace-setup';
import { api } from '@aether-app/lib/api/endpoints';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';
import { GRAPH_STAGES, stageStatuses } from '@aether-app/pages/onboarding/onboarding-model';

type Row = Record<string, unknown>;

function num(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

function compact(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toLocaleString('en-US');
}

function relative(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const mins = Math.round((Date.now() - t) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function needsAttention(item: TenantIntegrationItem): boolean {
  return item.enabled && /fail|error|degraded/i.test(item.sync_status);
}

function syncTone(item: TenantIntegrationItem): Tone {
  if (!item.enabled) return 'mute';
  if (needsAttention(item)) return 'amber';
  if (item.connected) return 'sage';
  return 'blue';
}

const TONE_DOT: Record<Tone, string> = {
  blue: 'var(--ae-blue)',
  sage: 'var(--ae-sage)',
  amber: 'var(--ae-amber)',
  ember: 'var(--ae-ember)',
  solar: 'var(--ae-solar)',
  mute: 'var(--ae-mute)',
};

const EVENT_COLORS = ['var(--ae-blue)', 'var(--ae-solar)', 'var(--ae-sage)', 'var(--ae-violet)', 'var(--ae-teal)', 'var(--ae-amber)'];

interface Attention {
  readonly key: string;
  readonly title: string;
  readonly why: string;
  readonly tone: Tone;
  readonly action: string;
  readonly to: string;
}

/**
 * Home — "what matters now" for the workspace (Claude Design handoff: Aether
 * Home). Every number is a read from an existing tenant endpoint; a section
 * whose read is empty says so rather than showing illustrative data.
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
  const campaigns = useQuery({
    key: 'home:campaigns',
    fetcher: () => api.campaigns.list({ limit: 8 }),
    staleTime: 60_000,
  });

  const items = useMemo(() => integrations.data?.items ?? [], [integrations.data]);
  const connectedCount = items.filter(i => i.connected).length;
  const anyFailing = items.some(needsAttention);
  const keyCount = (keys.data?.api_keys ?? []).length;
  const lastSync = items
    .map(i => i.last_synced_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);
  const statuses = stageStatuses(readiness.data?.checks);
  const passed = statuses.filter(s => s === 'passed' || s === 'not_applicable').length;
  const graphReady = readiness.data?.ready === true;
  const activationComplete = activation.data?.state === 'complete';
  const campaignRows = (campaigns.data?.campaigns ?? []) as Row[];

  const eventMix = useMemo(() => {
    const top = summary.data?.top_event_types ?? [];
    const rows = top
      .map(t => ({ label: String(t['event_type'] ?? t['type'] ?? t['name'] ?? 'event'), count: num(t['count'] ?? t['total']) ?? 0 }))
      .filter(r => r.count > 0)
      .slice(0, 6);
    const total = rows.reduce((n, r) => n + r.count, 0);
    return { rows, total };
  }, [summary.data]);

  const attention: Attention[] = useMemo(() => {
    const out: Attention[] = [];
    if (activation.data && !activationComplete) {
      out.push({
        key: 'activation',
        title: 'Finish workspace setup',
        why: activation.data.waiting_reason ? activation.data.waiting_reason.replace(/_/g, ' ') : 'Activation is not complete yet.',
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
          tone: 'ember',
          action: 'Review data quality',
          to: '/data-quality',
        });
      }
    }
    return out.slice(0, 5);
  }, [activation.data, activationComplete, items, readiness.data]);

  const workspaceName = org.data?.name ?? user?.displayName ?? 'Your workspace';
  const headline = graphReady
    ? 'Your graph is verified and current'
    : summary.data?.total_events
      ? 'Your graph is building from live events'
      : 'Your graph is waiting for its first events';

  return (
    <GlassPage>
      <div className="flex flex-col gap-[18px]" data-testid="aether-home">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Home · {workspaceName}</span>
            <h1 className="text-[28px] font-medium leading-tight tracking-[-0.56px]">{headline}</h1>
            <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>
              {connectedCount} connected source{connectedCount === 1 ? '' : 's'} · {keyCount} SDK key{keyCount === 1 ? '' : 's'} · last 24 hours
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="ae-card whitespace-nowrap rounded-xl px-3 py-2 text-[13px]">
              <span style={{ color: 'var(--ae-mute)' }}>Window</span> 24h
            </span>
            <span className="ae-card whitespace-nowrap rounded-full px-3 py-2 text-[13px]">
              <span style={{ color: lastSync ? 'var(--ae-sage)' : 'var(--ae-faint)' }}>●</span>{' '}
              {lastSync ? `synced ${relative(lastSync)}` : 'no syncs yet'}
            </span>
            <button
              type="button"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="ae-card ae-focus whitespace-nowrap rounded-full px-3 py-2 text-[13px]"
            >
              {theme === 'dark' ? 'Stone' : 'Graphite'}
            </button>
          </div>
        </div>

        {/* KPI tiles */}
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }} data-testid="home-kpis">
          <MetricTile label="Events" value={compact(summary.data?.total_events ?? null)} sub="last 24h" />
          <MetricTile label="People seen" value={compact(summary.data?.unique_users ?? null)} sub="last 24h" />
          <MetricTile label="Sessions" value={compact(summary.data?.total_sessions ?? null)} sub="last 24h" />
          <MetricTile label="Campaigns" value={campaigns.data ? `${compact(campaigns.data.total)}${campaigns.data.has_more ? '+' : ''}` : '—'} sub="imported" />
          {anyFailing ? (
            <MetricTile label="Connections" value={`${connectedCount}/${items.length}`} sub="one needs attention" tone="amber" />
          ) : (
            <MetricTile label="Connections" value={integrations.data ? `${connectedCount}/${items.length}` : '—'} sub="connected" />
          )}
          <MetricTile label="Graph checks" value={readiness.data ? `${passed}/${GRAPH_STAGES.length}` : '—'} sub={graphReady ? 'verified' : 'in progress'} />
        </div>
        {summary.error && <InlineNotice tone="amber">Event totals are unavailable right now.</InlineNotice>}

        {/* Hero — graph status (solar glass) */}
        <div
          className="flex flex-col gap-4 rounded-3xl px-6 py-[22px]"
          style={{
            background: 'var(--ae-solar-wash)',
            border: '1px solid rgba(202,138,4,.45)',
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)',
          }}
          data-testid="home-hero"
        >
          <div className="flex flex-wrap items-center justify-between gap-2.5">
            <span className="flex items-center gap-2">
              <span className="rounded-full px-2.5 py-0.5 text-[12px] font-medium" style={{ background: 'var(--ae-solar)', color: '#1a1a1e' }}>graph</span>
              <span className="text-[13px]">{graphReady ? 'verified' : activationComplete ? 'activated · building' : 'setting up'}</span>
            </span>
            <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              {readiness.data?.recorded_at ? `checked ${relative(readiness.data.recorded_at)}` : 'not checked yet'}
            </span>
          </div>

          <div className="grid gap-6" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(340px, 100%), 1fr))' }}>
            <div className="flex min-w-0 flex-col gap-3">
              <Eyebrow style={{ color: 'var(--ae-solar-ink)' }}>How the graph is built</Eyebrow>
              {GRAPH_STAGES.map((stage, i) => {
                const s = statuses[i] ?? 'waiting';
                const color = s === 'passed' ? 'var(--ae-sage)' : s === 'failed' ? 'var(--ae-ember)' : s === 'running' ? 'var(--ae-blue-ink)' : 'var(--ae-faint)';
                return (
                  <div key={stage.check} className="flex flex-col gap-1.5" data-stage={stage.check} data-stage-status={s}>
                    <span className="flex items-baseline justify-between gap-2 text-[13px]">
                      <span className="flex items-center gap-2">
                        <span className="ae-mono w-4 text-center" style={{ color }}>{s === 'passed' ? '✓' : stage.glyph}</span>
                        {stage.label}
                      </span>
                      <span className="ae-mono text-[11px]" style={{ color }}>{s === 'unknown' ? 'not reported' : s.replace('_', ' ')}</span>
                    </span>
                    <Bar value={s === 'passed' || s === 'not_applicable' ? 100 : s === 'running' ? null : 0} color={s === 'failed' ? 'var(--ae-ember)' : 'var(--ae-sage)'} height={3} />
                  </div>
                );
              })}
              {readiness.error && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Readiness checks are temporarily unavailable.</span>}
            </div>

            <div className="flex min-w-0 flex-col gap-2">
              <Eyebrow>What is arriving · last 24h</Eyebrow>
              {eventMix.total > 0 ? (
                <>
                  <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-[5px]">
                    {eventMix.rows.map((r, i) => (
                      <div key={r.label} style={{ flex: r.count, background: EVENT_COLORS[i % EVENT_COLORS.length] }} />
                    ))}
                  </div>
                  <div className="flex flex-col gap-1">
                    {eventMix.rows.map((r, i) => (
                      <div key={r.label} className="flex justify-between text-[12px]">
                        <span>
                          <span style={{ color: EVENT_COLORS[i % EVENT_COLORS.length] }}>●</span> {r.label}
                        </span>
                        <span className="ae-mono" style={{ color: 'var(--ae-mute)' }}>
                          {compact(r.count)} · {Math.round((r.count / eventMix.total) * 100)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-[13px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
                  No events in the last 24 hours. Install an SDK or connect a source and the mix of event types shows here.
                </p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2.5 border-t pt-3" style={{ borderColor: 'rgba(202,138,4,.4)' }}>
            <span className="flex flex-wrap gap-x-3.5 gap-y-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              <span>Scope · workspace</span>
              <span>Time · last 24 hours</span>
              <span>◉ evidence from tenant readiness checks</span>
            </span>
            <PrimaryButton onClick={() => void navigate('/explore')}>Open the graph →</PrimaryButton>
          </div>
        </div>

        {/* Attention + connections */}
        <div className="grid gap-[18px]" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))' }}>
          <section className="ae-card flex flex-col gap-3.5 rounded-[20px] px-6 py-[22px]" data-testid="home-attention">
            <div className="flex items-baseline justify-between">
              <Eyebrow style={{ color: 'var(--ae-amber)' }}>Needs your attention</Eyebrow>
              <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>{attention.length}</span>
            </div>
            {attention.length === 0 && (
              <p className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Nothing needs you right now.</p>
            )}
            {attention.map(item => (
              <div
                key={item.key}
                className="flex flex-col gap-1.5 rounded-[14px] border px-3.5 py-3"
                style={{
                  background: item.tone === 'ember' ? 'var(--ae-ember-tint)' : item.tone === 'amber' ? 'var(--ae-amber-tint)' : 'var(--ae-glass-card)',
                  borderColor: 'var(--ae-edge)',
                }}
              >
                <span className="flex items-start gap-2 text-[14px] leading-snug">
                  <span className="mt-1.5 h-[7px] w-[7px] flex-none rounded-full" style={{ background: TONE_DOT[item.tone] }} />
                  {item.title}
                </span>
                <span className="pl-[15px] text-[12px] leading-snug" style={{ color: 'var(--ae-mute)' }}>{item.why}</span>
                <span className="pl-[15px]">
                  <LinkButton onClick={() => void navigate(item.to)} tone={item.tone}>{item.action} →</LinkButton>
                </span>
              </div>
            ))}
          </section>

          <section className="ae-card flex flex-col gap-3 rounded-[20px] px-6 py-[22px]" data-testid="home-connections">
            <div className="flex items-baseline justify-between">
              <Eyebrow style={{ color: 'var(--ae-blue-ink)' }}>Connections</Eyebrow>
              <LinkButton onClick={() => void navigate('/settings/integrations')}>Manage</LinkButton>
            </div>
            {integrations.error && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Connections are unavailable right now.</span>}
            {integrations.data && items.length === 0 && (
              <div className="flex flex-col items-start gap-2">
                <p className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No sources connected yet.</p>
                <LinkButton onClick={() => void navigate('/activation')}>Connect a source →</LinkButton>
              </div>
            )}
            {items.slice(0, 8).map(item => (
              <div key={item.id} className="flex items-center gap-3 border-t pt-2.5 text-[13px]" style={{ borderColor: 'var(--ae-edge)' }}>
                <BrandMark token={item.family} label={item.display_name} size={26} markSize={15} />
                <span className="flex min-w-0 flex-1 flex-col leading-tight">
                  <span className="truncate">{item.display_name}</span>
                  <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>synced {relative(item.last_synced_at)}</span>
                </span>
                <TonePill tone={syncTone(item)}>{item.enabled ? item.sync_status.replace(/_/g, ' ') : 'disabled'}</TonePill>
              </div>
            ))}
          </section>
        </div>

        {/* Campaigns */}
        <section className="ae-card flex flex-col gap-2.5 rounded-[20px] px-6 py-[18px]" data-testid="home-campaigns">
          <div className="flex flex-wrap items-baseline justify-between gap-2.5">
            <span className="flex flex-wrap items-baseline gap-2.5">
              <Eyebrow style={{ color: 'var(--ae-blue-ink)' }}>What is happening</Eyebrow>
              <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                {campaigns.data ? `${campaigns.data.total}${campaigns.data.has_more ? '+' : ''} campaign${campaigns.data.total === 1 && !campaigns.data.has_more ? '' : 's'} imported from your systems` : 'Campaigns'}
              </span>
            </span>
            <LinkButton onClick={() => void navigate('/campaigns')}>All campaigns →</LinkButton>
          </div>
          {campaigns.error && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Campaigns are unavailable right now.</span>}
          {campaigns.data && campaignRows.length === 0 && (
            <p className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              No campaigns yet. Aether imports campaigns from connected ad, email and commerce systems; it never creates them.
            </p>
          )}
          {campaignRows.length > 0 && (
            <div className="overflow-x-auto">
              <div className="flex min-w-[560px] flex-col">
                <div className="ae-eyebrow grid gap-3 px-1 pb-1.5" style={{ gridTemplateColumns: 'minmax(160px,1.8fr) 90px 80px 80px 80px' }}>
                  <span>Campaign</span>
                  <span>Status</span>
                  <span className="text-right">Reach</span>
                  <span className="text-right">Clicks</span>
                  <span className="text-right">Conv.</span>
                </div>
                {campaignRows.map((c, index) => {
                  const metrics = (c['metrics'] ?? {}) as Row;
                  const funnel = (c['funnel'] ?? metrics['funnel'] ?? {}) as Row;
                  const id = String(c['id'] ?? c['campaign_id'] ?? '');
                  const platform = String(c['platform'] ?? c['origin'] ?? c['source'] ?? '');
                  const status = String(c['status'] ?? '—');
                  return (
                    <button
                      key={id || index}
                      type="button"
                      disabled={!id}
                      onClick={() => void navigate(`/campaigns/${encodeURIComponent(id)}`)}
                      className="ae-focus grid items-center gap-3 border-t px-1 py-[7px] text-left text-[13px] hover:bg-[var(--ae-glass-card)]"
                      style={{ gridTemplateColumns: 'minmax(160px,1.8fr) 90px 80px 80px 80px', borderColor: 'var(--ae-edge)' }}
                    >
                      <span className="flex min-w-0 items-center gap-2.5">
                        <BrandMark token={platform || 'aether'} label={platform || 'Aether'} size={22} markSize={14} />
                        <span className="flex min-w-0 flex-col leading-tight">
                          <span className="truncate">{String(c['name'] ?? id)}</span>
                          <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{platform || 'source unknown'}</span>
                        </span>
                      </span>
                      <span className="text-[12px]" style={{ color: /active|live|running/i.test(status) ? 'var(--ae-sage)' : 'var(--ae-mute)' }}>● {status}</span>
                      <span className="ae-mono text-right text-[12px]">{compact(num(funnel['entered'] ?? c['impressions']))}</span>
                      <span className="ae-mono text-right text-[12px]">{compact(num(funnel['clicked'] ?? c['clicks']))}</span>
                      <span className="ae-mono text-right text-[12px]">{compact(num(funnel['converted'] ?? c['conversions']))}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        {/* Outcomes and decisions (existing evidence panels) */}
        <div className="ae-legacy grid gap-[18px]" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(360px, 100%), 1fr))' }}>
          <OutcomeLedgerPanel />
          <DecisionIntelligencePanel />
        </div>

        {/* ADR-008 D9: tenant model-routing preference. Feature-flag gated (D8). */}
        {isFeatureEnabled('enableModelHarness') && (
          <div className="ae-legacy">
            <ModelSelectionPanel {...(user?.id ? { tenantId: user.id } : {})} />
          </div>
        )}
      </div>
    </GlassPage>
  );
}
