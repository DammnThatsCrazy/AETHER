import { appHref } from '@aether-app/lib/app-path';
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, Icon, LoadingState, formatCount, formatDate, formatDateTime, formatDecimal, useQuery, useTimeContext, type TimeContext } from '@aether/ui';
import { CardLinkedOutcomesTab } from './card-linked-outcomes-tab';
import { api } from '@aether-app/lib/api/endpoints';
import {
  useCampaign360Overview,
  useCampaign360Population,
  useCampaign360Clusters,
  useCampaign360Conversions,
  useCampaign360Attribution,
} from '@aether-app/features/campaigns/use-campaign-360';
import {
  attentionReasonLabel,
  contextualReadiness,
  useTenantIntegrationReadiness,
} from '@aether-app/features/integrations';
import type { TenantReadinessItem } from '@aether-app/features/integrations';
import { CampaignTargetingIntelligenceTab } from '@aether-app/features/targeting-intelligence';
import {
  encodeExplorationContext,
  useExplorationClient,
  useExplorationContext,
} from '@aether/ui/exploration';
import { campaignExplorationContext } from '@aether-app/features/campaigns/use-campaign-exploration';
import { ProjectionSurfacePanel } from '@aether-app/features/projection-360';
import { GlassPage } from '@aether-app/components/app-shell';
import { BrandMark } from '@aether-app/components/brand-mark';
import { Bar, Eyebrow, InlineNotice, LinkButton, TonePill, type Tone } from '@aether-app/components/ae-ui';
import {
  GlassSection, LoadingRow, OutlineChip, SegmentedTabs, ShareRow, type SegmentOption,
} from '@aether-app/components/ae-campaigns-geo-ui';
import { asList, asRecord, num, pct, ratio, shortDate, statusTone, text, usd } from './campaign-model';

type AnyRecord = Record<string, unknown>;

// ── Contextual integration readiness (WS-4) ─────────────────────────────────
// A Campaign 360 page only has a "needed integration" to propose when the
// campaign's own channel evidences the dependency. Paid/channel campaigns need
// an advertising source; lifecycle/outbound campaigns need a communications
// source. Unknown/organic channels propose nothing (only tenant-wide attention
// items still surface — those are facts about the tenant's own records).
const AD_CHANNELS = new Set([
  'ads', 'social', 'paid_social', 'paid_search', 'search', 'display', 'video',
  'shopping', 'retargeting',
]);
const COMMS_CHANNELS = new Set([
  'email', 'sms', 'push', 'lifecycle', 'transactional', 'in_app', 'in-app',
  'outbound',
]);

function dependentCategoriesForCampaignChannel(channel: string): string[] {
  const c = (channel ?? '').toLowerCase();
  if (AD_CHANNELS.has(c)) return ['advertising_campaigns'];
  if (COMMS_CHANNELS.has(c)) return ['communications_lifecycle'];
  return [];
}

const CONNECT_COPY: Record<string, { dataKinds: string }> = {
  advertising_campaigns: { dataKinds: 'spend, attribution and conversions' },
  communications_lifecycle: { dataKinds: 'messages, recipients and replies' },
};

function integrationsHref(): string {
  return `/integrations?return=${encodeURIComponent(window.location.pathname + window.location.search)}`;
}

function CampaignIntegrationBanner({ channel }: { channel: string }) {
  const { data, isLoading, error } = useTenantIntegrationReadiness();
  if (isLoading || error) return null;
  const model = contextualReadiness(
    data?.items as TenantReadinessItem[] | undefined,
    dependentCategoriesForCampaignChannel(channel),
  );
  if (!model.connect && model.attention.length === 0) return null;
  const href = integrationsHref();

  return (
    <div className="flex flex-col gap-2">
      {model.connect && (
        <InlineNotice tone="blue">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-medium">{model.connect.categoryLabel}</span>{' '}
              isn't connected yet — connect it under Integrations to start
              populating this campaign's{' '}
              {CONNECT_COPY[model.connect.category]?.dataKinds ?? 'data'}.
            </span>
            <Link to={href} className="ae-focus font-medium hover:underline">
              Connect {model.connect.categoryLabel}
            </Link>
          </span>
        </InlineNotice>
      )}
      {model.attention.length > 0 && (
        <InlineNotice tone="amber">
          <span className="block font-medium">Integrations need attention</span>
          {model.attention.map((item) => (
            <span key={item.key} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                <span className="font-medium">{item.display_name}</span>
                {item.attention_reasons.length > 0
                  ? ` — ${item.attention_reasons.map(attentionReasonLabel).join(', ')}`
                  : ''}
              </span>
              <Link to={href} className="ae-focus font-medium hover:underline">
                Fix in Integrations
              </Link>
            </span>
          ))}
        </InlineNotice>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="text-xl font-semibold text-text-primary mt-0.5">{value}</p>
    </div>
  );
}

// A canonical USD figure that is absent is unknown, not zero. Render "—"
// instead of coercing a missing value into a misleading "$0.00". A real,
// priced zero still formats as "$0.00".
function fmtUSD(v: unknown, ctx: TimeContext) {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return '—';
  return `$${formatDecimal(n, ctx, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

function CampaignJourneyContextLink({
  campaignId,
  profileId,
}: {
  campaignId: string;
  profileId: string;
}) {
  const navigate = useNavigate();
  const client = useExplorationClient();
  const base = useExplorationContext();
  const [blocked, setBlocked] = useState(false);

  async function openJourney() {
    setBlocked(false);
    const context = campaignExplorationContext(base, campaignId);
    const resolved = await client.resolveLink({
      context,
      to: 'journeys',
      focus: { kind: 'profile', id: profileId },
    });
    if (!resolved.adapter_available) {
      setBlocked(true);
      return;
    }
    navigate(`/users/${encodeURIComponent(profileId)}/journey?${encodeExplorationContext(resolved.link.context)}`);
  }

  return blocked ? (
    <span className="text-xs text-text-muted">Journey exploration unavailable</span>
  ) : (
    <button type="button" className="text-xs text-accent hover:underline" onClick={() => void openJourney()}>
      Open journey
    </button>
  );
}

// ── Overview tab (design: selectable KPIs → breakdown) ───────────────────────

type Kpi = 'obs' | 'eng' | 'cv' | 'inf';
type Dim = 'source_class' | 'provider' | 'actor' | 'role';

const DIMS: readonly { value: Dim; label: string }[] = [
  { value: 'source_class', label: 'Source class' },
  { value: 'provider', label: 'Provider' },
  { value: 'actor', label: 'Actor' },
  { value: 'role', label: 'Journey role' },
];

const BREAKDOWN_COLORS = ['var(--ae-blue)', 'var(--ae-teal)', 'var(--ae-violet)', 'var(--ae-solar)', 'var(--ae-faint)'];

function rollupDimValue(row: AnyRecord, dim: Dim): string {
  const v = dim === 'source_class' ? row.source_class
    : dim === 'provider' ? (row.ai_provider ?? row.provider)
      : dim === 'actor' ? (row.actor_type ?? row.actor)
        : (row.journey_role ?? row.role);
  return v === null || v === undefined || v === '' ? 'Not classified' : String(v).replace(/_/g, ' ');
}

function dimensionRollups(attribution: AnyRecord | null): AnyRecord[] {
  const raw = attribution?.dimension_rollups;
  if (Array.isArray(raw)) return raw as AnyRecord[];
  const items = asRecord(raw).items;
  return Array.isArray(items) ? (items as AnyRecord[]) : [];
}

interface Insight { readonly color: string; readonly icon: string; readonly text: string }

function KpiTile({ label, value, sub, selected, onClick, tone }: {
  label: string; value: string; sub: string; selected: boolean; onClick: () => void; tone?: Tone;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className="ae-glass-card ae-focus flex flex-col gap-0.5 rounded-[20px] px-4 py-3.5 text-left transition-colors"
      style={{ borderColor: selected ? 'var(--ae-blue)' : undefined }}
      data-testid={`campaign-kpi-${label.toLowerCase().replace(/\s+/g, '-')}`}
    >
      <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{label}</span>
      <span className="ae-mono text-[22px] font-medium" style={{ color: selected ? 'var(--ae-blue-ink)' : value === '—' ? 'var(--ae-faint)' : 'var(--ae-ink)' }}>{value}</span>
      <span className="text-[11px]" style={{ color: tone === 'sage' ? 'var(--ae-sage)' : 'var(--ae-mute)' }}>{sub}</span>
    </button>
  );
}

function BreakdownMetric({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-2xl border px-3.5 py-3" style={{ background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge-soft)' }}>
      <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{label}</span>
      <span className="ae-mono text-[19px] font-medium" style={{ color: value === '—' ? 'var(--ae-faint)' : undefined }}>{value}</span>
      <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{sub}</span>
    </div>
  );
}

const STAGES = [
  { key: 'observed_count', label: 'Observed', population: 'observed' },
  { key: 'resolved_count', label: 'Resolved', population: 'resolved' },
  { key: 'engaged_count', label: 'Engaged', population: 'engaged' },
  { key: 'converted_count', label: 'Converted', population: 'converted' },
  { key: 'attributed_count', label: 'Attributed', population: 'attributed' },
] as const;

function OverviewTab({ campaignId, timeStart, timeEnd, attributionModel, onOpenPopulation, onOpenTab }: {
  campaignId: string;
  timeStart?: string;
  timeEnd?: string;
  attributionModel: string;
  onOpenPopulation: (population: string) => void;
  onOpenTab: (tab: string) => void;
}) {
  const timeCtx = useTimeContext();
  const [kpi, setKpi] = useState<Kpi>('obs');
  const [dim, setDim] = useState<Dim>('source_class');
  const { data, loading, error } = useCampaign360Overview(campaignId, {
    ...(timeStart !== undefined ? { time_start: timeStart } : {}),
    ...(timeEnd !== undefined ? { time_end: timeEnd } : {}),
    attribution_model: attributionModel,
  });
  const attribution = useCampaign360Attribution(campaignId, { model: attributionModel });

  const d = (data ?? {}) as AnyRecord;
  const observed = num(d.observed_count);
  const resolved = num(d.resolved_count);
  const engaged = num(d.engaged_count);
  const converted = num(d.converted_count);
  const attributed = num(d.attributed_count);
  const spend = num(d.spend_usd);
  const impressions = num(d.impressions);
  const clicks = num(d.clicks);
  const roas = num(d.roas);
  const gross = num(d.gross_attributed_revenue);
  const net = num(d.net_attributed_revenue);
  const touchpoints = num(d.touchpoint_count);
  const resolution = num(d.identity_resolution_rate) ?? ratio(resolved, observed);
  const model = String(d.attribution_model ?? attributionModel).replace(/_/g, ' ');
  const count = (n: number | null) => (n === null ? '—' : formatCount(n, timeCtx));

  const rollups = useMemo(() => dimensionRollups(attribution.data as AnyRecord | null), [attribution.data]);
  const breakdown = useMemo(() => {
    const byValue = kpi === 'inf';
    const totals = new Map<string, number>();
    for (const row of rollups) {
      const key = rollupDimValue(row, dim);
      const v = byValue
        ? num(row.attributed_net_revenue ?? row.net_revenue)
        : num(row.conversions ?? row.attributed_conversions);
      if (v === null) continue;
      totals.set(key, (totals.get(key) ?? 0) + v);
    }
    const rows = [...totals.entries()].sort((a, b) => b[1] - a[1]);
    const sum = rows.reduce((n, [, v]) => n + v, 0);
    return { rows: rows.slice(0, 6), sum, byValue };
  }, [rollups, dim, kpi]);

  if (loading) return <LoadingRow label="Loading campaign overview…" />;
  if (error) {
    return (
      <InlineNotice tone="ember">
        <span className="block font-medium">Overview unavailable</span>
        <span className="block">{error}</span>
      </InlineNotice>
    );
  }
  if (!data) return null;

  const kpis: Record<Kpi, { label: string; value: string; sub: string; tone?: Tone }> = {
    obs: { label: 'Reached', value: count(observed), sub: 'observed people and entities' },
    eng: { label: 'Engaged', value: count(engaged), sub: engaged !== null && observed ? `${pct(ratio(engaged, observed))} of reached` : 'observed engagement' },
    cv: { label: 'Conversions', value: count(converted), sub: 'observed conversions', tone: 'sage' },
    inf: { label: 'Attributed value', value: usd(gross), sub: `gross · ${model}` },
  };

  const metrics: Record<Kpi, { title: string; cards: { label: string; value: string; sub: string }[] }> = {
    obs: {
      title: 'Reached',
      cards: [
        { label: 'People reached', value: count(observed), sub: 'in range' },
        { label: 'Resolved to a profile', value: count(resolved), sub: resolution !== null ? `${pct(resolution)} resolution rate` : 'resolution not reported' },
        { label: 'Impressions', value: count(impressions), sub: 'reported by the source' },
        { label: 'Cost per 1,000', value: spend !== null && impressions ? usd((spend / impressions) * 1000, 2) : '—', sub: 'spend over impressions' },
      ],
    },
    eng: {
      title: 'Engaged',
      cards: [
        { label: 'Engaged', value: count(engaged), sub: `${pct(ratio(engaged, observed))} of reached` },
        { label: 'Clicks', value: count(clicks), sub: 'reported by the source' },
        { label: 'Click-through', value: pct(ratio(clicks, impressions), 2), sub: 'clicks over impressions' },
        { label: 'Touchpoints', value: count(touchpoints), sub: 'observed exposures and actions' },
      ],
    },
    cv: {
      title: 'Conversions',
      cards: [
        { label: 'Conversions', value: count(converted), sub: `${pct(ratio(converted, observed))} of reached` },
        { label: 'Of engaged', value: pct(ratio(converted, engaged)), sub: 'conversion from engagement' },
        { label: 'Attributed', value: count(attributed), sub: `credited under ${model}` },
        { label: 'Value per conversion', value: gross !== null && converted ? usd(gross / converted, 2) : '—', sub: 'gross attributed over conversions' },
      ],
    },
    inf: {
      title: 'Attributed value',
      cards: [
        { label: 'Gross attributed', value: usd(gross), sub: model },
        { label: 'Net attributed', value: usd(net), sub: 'after refunds and adjustments' },
        { label: 'Return', value: roas !== null ? `${roas.toFixed(2)}x` : '—', sub: 'attributed revenue over spend' },
        { label: 'Cost per conversion', value: spend !== null && converted ? usd(spend / converted, 2) : '—', sub: `spend ${usd(spend)}` },
      ],
    },
  };

  const insights: Insight[] = [];
  if (resolution !== null) insights.push({ color: 'var(--ae-blue-ink)', icon: 'fingerprint', text: `${pct(resolution, 0)} of the people this campaign reached are resolved to a known profile.` });
  const engagedToConv = ratio(converted, engaged);
  if (engagedToConv !== null) insights.push({ color: 'var(--ae-sage)', icon: 'circle-check', text: `${pct(engagedToConv)} of engaged people went on to convert.` });
  if (gross !== null && net !== null && gross > 0 && net < gross) insights.push({ color: 'var(--ae-amber)', icon: 'triangle-alert', text: `Refunds and adjustments remove ${pct(1 - net / gross)} of gross attributed revenue.` });
  if (breakdown.rows.length > 0 && breakdown.sum > 0) {
    const [top, value] = breakdown.rows[0]!;
    insights.push({ color: 'var(--ae-violet)', icon: 'lightbulb', text: `${top} carries ${pct(value / breakdown.sum, 0)} of attributed ${breakdown.byValue ? 'net revenue' : 'conversions'} by ${DIMS.find(x => x.value === dim)?.label.toLowerCase()}.` });
  }
  insights.push({ color: 'var(--ae-amber)', icon: 'info', text: `Attribution is observed under the ${model} model, not proven causal.` });

  const first = observed ?? 0;
  const dimLabel = DIMS.find(x => x.value === dim)?.label ?? '';

  return (
    <div className="flex flex-col gap-3.5" data-testid="campaign-overview">
      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(170px, 100%), 1fr))' }}>
        {(Object.keys(kpis) as Kpi[]).map(k => (
          <KpiTile key={k} {...kpis[k]} selected={kpi === k} onClick={() => setKpi(k)} />
        ))}
      </div>

      {/* Breakdown */}
      <GlassSection className="gap-3.5" testId="campaign-breakdown">
        <span className="flex flex-wrap items-center justify-between gap-2.5">
          <span className="flex flex-col gap-0.5">
            <Eyebrow>Breakdown</Eyebrow>
            <span className="text-[20px] font-medium tracking-[-0.33px]">{metrics[kpi].title}</span>
          </span>
          <span className="flex flex-wrap gap-1.5">
            {DIMS.map(x => (
              <OutlineChip key={x.value} selected={dim === x.value} onClick={() => setDim(x.value)}>{x.label}</OutlineChip>
            ))}
          </span>
        </span>
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(150px, 100%), 1fr))' }}>
          {metrics[kpi].cards.map(card => <BreakdownMetric key={card.label} {...card} />)}
        </div>
        <div className="grid items-start gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(300px, 100%), 1fr))' }}>
          <div className="flex flex-col gap-2">
            <Eyebrow>{breakdown.byValue ? 'Attributed net revenue' : 'Attributed conversions'} by {dimLabel.toLowerCase()}</Eyebrow>
            {attribution.loading && <LoadingRow label="Loading attribution credits…" />}
            {!attribution.loading && attribution.error && (
              <span className="text-[12px]" style={{ color: 'var(--ae-amber)' }}>Attribution credits are unavailable right now.</span>
            )}
            {!attribution.loading && !attribution.error && breakdown.rows.length === 0 && (
              <span className="text-[12px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
                No dimension credits yet. They appear after classified touchpoints are attributed.
              </span>
            )}
            {breakdown.rows.map(([label, value], i) => (
              <ShareRow
                key={label}
                label={label}
                value={breakdown.byValue ? usd(value) : formatCount(value, timeCtx)}
                share={breakdown.sum > 0 ? (value / breakdown.sum) * 100 : null}
                color={BREAKDOWN_COLORS[i % BREAKDOWN_COLORS.length] ?? 'var(--ae-blue)'}
              />
            ))}
          </div>
          <div className="flex flex-col gap-2">
            <Eyebrow>What this tells you</Eyebrow>
            {insights.map(ins => (
              <div key={ins.text} className="flex items-start gap-2.5 rounded-[14px] border px-3 py-2.5" style={{ borderColor: 'var(--ae-edge-soft)', background: 'var(--ae-glass-card)' }}>
                <span className="mt-0.5" style={{ color: ins.color }}>
                  <Icon name={ins.icon} decorative size="sm" />
                </span>
                <span className="text-[13px] leading-normal">{ins.text}</span>
              </div>
            ))}
            <span className="flex flex-wrap gap-3 pt-1">
              <LinkButton onClick={() => onOpenTab('population')}>Participants →</LinkButton>
              <LinkButton onClick={() => onOpenTab('attribution')}>Influence →</LinkButton>
              <LinkButton onClick={() => onOpenTab('economic360')}>Value →</LinkButton>
            </span>
          </div>
        </div>
      </GlassSection>

      {/* Population funnel (design: participant stages) */}
      <GlassSection testId="campaign-funnel">
        <span className="flex flex-wrap items-baseline justify-between gap-2">
          <Eyebrow>Population funnel</Eyebrow>
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Select a stage to see who is in it</span>
        </span>
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(150px, 100%), 1fr))' }}>
          {STAGES.map((stage, i) => {
            const n = num(d[stage.key]);
            const prev = i > 0 ? num(d[STAGES[i - 1]!.key]) : null;
            return (
              <button
                key={stage.key}
                type="button"
                onClick={() => onOpenPopulation(stage.population)}
                className="ae-focus flex flex-col gap-0.5 rounded-2xl border px-3.5 py-3 text-left hover:border-[var(--ae-blue)]"
                style={{ background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge-soft)' }}
              >
                <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{stage.label}</span>
                <span className="ae-mono text-[19px] font-medium">{count(n)}</span>
                <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>
                  {i === 0 ? 'everyone observed' : prev ? `${pct(ratio(n, prev))} of previous` : '—'}
                </span>
                <span className="mt-1"><Bar value={first > 0 && n !== null ? (n / first) * 100 : 0} height={5} /></span>
              </button>
            );
          })}
        </div>
        <span className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          <span>Model · {model}</span>
          <span>Resolution rate · {pct(resolution)}</span>
          <span>Touchpoints · {count(touchpoints)}</span>
          <span>Spend · {usd(spend)}</span>
        </span>
      </GlassSection>
    </div>
  );
}

// ── Population tab (design: Participants) ─────────────────────────────────────

const POPULATIONS = ['observed', 'resolved', 'engaged', 'converted', 'attributed'] as const;

function PopulationTab({ campaignId, timeStart, timeEnd, population, onPopulation }: {
  campaignId: string;
  timeStart?: string;
  timeEnd?: string;
  population: string;
  onPopulation: (population: string) => void;
}) {
  const timeCtx = useTimeContext();
  const { data, loading, error } = useCampaign360Population(campaignId, {
    population,
    ...(timeStart !== undefined ? { time_start: timeStart } : {}),
    ...(timeEnd !== undefined ? { time_end: timeEnd } : {}),
    limit: 50,
  });
  const items = (data as AnyRecord)?.items as AnyRecord[] | undefined;
  const options: SegmentOption<string>[] = POPULATIONS.map(p => ({ value: p, label: p[0]!.toUpperCase() + p.slice(1) }));

  return (
    <div className="flex flex-col gap-3">
      <SegmentedTabs label="Population stage" options={options} value={population} onChange={onPopulation} className="self-start" />
      <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Showing the {population} stage. Select a stage above to change the list.</span>
      {loading && <LoadingState lines={4} />}
      {error && <ErrorState title="Population unavailable" message={error} />}
      {!loading && !error && (
        <GlassSection>
          <Eyebrow>Participants at this stage</Eyebrow>
          <div className="ae-legacy">
            {!items?.length
              ? <EmptyState title="No entities" description={`No ${population} entities found.`} />
              : (
                <DataTable
                  data={items}
                  keyExtractor={r => String(r.entity_id)}
                  columns={[
                    { key: 'entity_id', header: 'Entity', render: r => <span className="font-mono text-xs">{String(r.entity_id ?? '').slice(0, 16)}…</span> },
                    { key: 'entity_type', header: 'Type', render: r => String(r.entity_type ?? '—') },
                    { key: 'touchpoint_count', header: 'Touchpoints', render: r => formatCount(Number(r.touchpoint_count ?? 0), timeCtx) },
                    { key: 'conversion_count', header: 'Conversions', render: r => formatCount(Number(r.conversion_count ?? 0), timeCtx) },
                    { key: 'attributed_revenue', header: 'Attributed $', render: r => fmtUSD(r.attributed_revenue, timeCtx) },
                    { key: 'last_activity_at', header: 'Last active', render: r => r.last_activity_at ? formatDate(String(r.last_activity_at), timeCtx) : '—' },
                    {
                      key: 'journey',
                      header: 'Journey',
                      render: r => r.entity_id ? (
                        <CampaignJourneyContextLink
                          campaignId={campaignId}
                          profileId={String(r.entity_id)}
                        />
                      ) : <span className="text-xs text-text-muted">unresolved</span>,
                    },
                  ]}
                />
              )
            }
          </div>
        </GlassSection>
      )}
    </div>
  );
}

// ── Sources tab (design: read-only source parts) ──────────────────────────────

function sourceStatus(v: unknown): 'missing' | 'empty' | 'available' | null {
  return v === 'missing' || v === 'empty' || v === 'available' ? v : null;
}

function SourcesTab({ campaignId }: { campaignId: string }) {
  const refs = useQuery({
    key: `campaign:${campaignId}:external-refs`,
    fetcher: () => api.campaigns.externalRefs(campaignId),
    staleTime: 60_000,
  });
  const aliases = useQuery({
    key: `campaign:${campaignId}:aliases`,
    fetcher: () => api.campaigns.aliases(campaignId),
    staleTime: 60_000,
  });
  const refItems = asList(asRecord(refs.data).items).map(asRecord);
  const aliasItems = asList(asRecord(aliases.data).items).map(asRecord);
  const refsDegraded = sourceStatus(asRecord(refs.data).source_status) === 'missing';
  const aliasesDegraded = sourceStatus(asRecord(aliases.data).source_status) === 'missing';

  return (
    <div className="flex flex-col gap-3" data-testid="campaign-sources">
      <span className="max-w-[640px] text-[12px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
        Read-only copies from the systems that run this campaign. Aether never edits, pauses or launches anything there. Source classification is not campaign identity, so every part below was grouped by evidence.
      </span>

      <GlassSection>
        <Eyebrow>Source campaigns</Eyebrow>
        {refs.isLoading && !refs.data && <LoadingRow label="Loading source campaigns…" />}
        {(refs.error || refsDegraded) && (
          <InlineNotice tone="amber">Source campaign references are unavailable right now.</InlineNotice>
        )}
        {!refs.error && !refsDegraded && refs.data !== undefined && refs.data !== null && refItems.length === 0 && (
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No source campaigns are linked to this campaign yet.</span>
        )}
        {refItems.map((ref, i) => {
          const platform = text(ref.platform, 'source');
          const status = ref.external_status ? String(ref.external_status) : null;
          const synced = shortDate(ref.last_synced_at ?? ref.updated_at ?? ref.last_seen_at);
          return (
            <div key={`${platform}-${text(ref.external_campaign_id, String(i))}`} className="flex flex-wrap items-center gap-3 border-t pt-2.5 text-[13px]" style={{ borderColor: 'var(--ae-edge)' }}>
              <BrandMark token={platform} label={platform} size={30} markSize={17} />
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="truncate">{text(ref.external_campaign_name ?? ref.external_campaign_id)}</span>
                <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>
                  {platform} · {text(ref.external_campaign_id)}{ref.external_account_id ? ` · account ${String(ref.external_account_id)}` : ''}
                </span>
              </span>
              {synced && <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>seen {synced}</span>}
              {status && <TonePill tone={statusTone(status)}>source: {status}</TonePill>}
            </div>
          );
        })}
      </GlassSection>

      <GlassSection>
        <Eyebrow>Grouping evidence (aliases)</Eyebrow>
        {aliases.isLoading && !aliases.data && <LoadingRow label="Loading aliases…" />}
        {(aliases.error || aliasesDegraded) && (
          <InlineNotice tone="amber">Campaign aliases are unavailable right now.</InlineNotice>
        )}
        {!aliases.error && !aliasesDegraded && aliases.data !== undefined && aliases.data !== null && aliasItems.length === 0 && (
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No aliases recorded. Resolved mapping reviews add aliases here.</span>
        )}
        {aliasItems.length > 0 && (
          <span className="flex flex-wrap gap-1.5">
            {aliasItems.map((alias, i) => (
              <span key={text(alias.alias_id ?? alias.id, String(i))} className="ae-mono inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
                <span style={{ color: 'var(--ae-faint)' }}>{text(alias.alias_type)}</span>
                {text(alias.alias_value)}
                {alias.platform ? <span style={{ color: 'var(--ae-mute)' }}>· {String(alias.platform)}</span> : null}
              </span>
            ))}
          </span>
        )}
      </GlassSection>
    </div>
  );
}

// ── Clusters tab ──────────────────────────────────────────────────────────────

function ClustersTab({ campaignId }: { campaignId: string }) {
  const timeCtx = useTimeContext();
  const { data, loading, error } = useCampaign360Clusters(campaignId, { limit: 50 });
  const items = (data as AnyRecord)?.items as AnyRecord[] | undefined;

  if (loading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title="Clusters unavailable" message={error} />;

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Identity clusters</CardTitle></CardHeader>
      <CardContent>
        {!items?.length
          ? <EmptyState title="No clusters" description="No identity clusters found for this campaign." />
          : (
            <DataTable
              data={items}
              keyExtractor={r => String(r.cluster_id ?? Math.random())}
              columns={[
                { key: 'cluster_id', header: 'Cluster', render: r => r.cluster_id ? <span className="font-mono text-xs">{String(r.cluster_id).slice(0, 16)}…</span> : <span className="text-text-muted text-xs">unresolved</span> },
                { key: 'conversion_count', header: 'Conversions', render: r => formatCount(Number(r.conversion_count ?? 0), timeCtx) },
                { key: 'attributed_gross_revenue', header: 'Gross $', render: r => fmtUSD(r.attributed_gross_revenue, timeCtx) },
                { key: 'attributed_net_revenue', header: 'Net $', render: r => fmtUSD(r.attributed_net_revenue, timeCtx) },
              ]}
            />
          )
        }
      </CardContent>
    </Card>
  );
}

// ── Conversions tab ───────────────────────────────────────────────────────────

function ConversionsTab({ campaignId, timeStart, timeEnd }: { campaignId: string; timeStart?: string; timeEnd?: string }) {
  const timeCtx = useTimeContext();
  const { data, loading, error } = useCampaign360Conversions(campaignId, {
    ...(timeStart !== undefined ? { after: timeStart } : {}),
    ...(timeEnd !== undefined ? { before: timeEnd } : {}),
    limit: 50,
  });
  const items = (data as AnyRecord)?.items as AnyRecord[] | undefined;

  if (loading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title="Conversions unavailable" message={error} />;

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Conversions</CardTitle></CardHeader>
      <CardContent>
        {!items?.length
          ? <EmptyState title="No conversions" description="No attributed conversions found for this campaign." />
          : (
            <DataTable
              data={items}
              keyExtractor={r => String(r.conversion_id)}
              columns={[
                { key: 'conversion_id', header: 'ID', render: r => <span className="font-mono text-xs">{String(r.conversion_id ?? '').slice(0, 16)}…</span> },
                { key: 'conversion_type', header: 'Type', render: r => String(r.conversion_type ?? '—') },
                { key: 'gross_value', header: 'Gross $', render: r => fmtUSD(r.gross_value, timeCtx) },
                { key: 'net_value', header: 'Net $', render: r => fmtUSD(r.net_value, timeCtx) },
                { key: 'occurred_at', header: 'Date', render: r => r.occurred_at ? formatDate(String(r.occurred_at), timeCtx) : '—' },
              ]}
            />
          )
        }
      </CardContent>
    </Card>
  );
}

// ── Messages tab (Communications Intelligence) ────────────────────────────────

function MessageDetailDrawer({ campaignId, externalMessageId, onClose }: {
  campaignId: string;
  externalMessageId: string;
  onClose: () => void;
}) {
  const timeCtx = useTimeContext();
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    (api.campaigns.messageDetail(campaignId, externalMessageId) as Promise<AnyRecord>)
      .then(d => { if (active) setDetail(d as AnyRecord); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [campaignId, externalMessageId]);

  const message = (detail?.message as AnyRecord) ?? {};
  const stats = (detail?.stats as AnyRecord) ?? {};
  const links = (detail?.links as AnyRecord[]) ?? [];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Message detail: ${externalMessageId}`}
      className="fixed inset-y-0 right-0 z-40 w-full max-w-lg bg-surface-base border-l border-border-default shadow-xl overflow-y-auto"
    >
      <div className="flex items-center justify-between px-5 py-4 border-b border-border-default sticky top-0 bg-surface-base">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">{String(message.name ?? externalMessageId)}</h2>
          <p className="text-xs text-text-muted font-mono">{externalMessageId}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close message detail"
          className="text-xs px-2 py-1 rounded border border-border-default text-text-secondary hover:text-text-primary"
        >
          Close
        </button>
      </div>
      <div className="p-5 space-y-5">
        {loading && <LoadingState lines={6} />}
        {error && <ErrorState title="Message detail unavailable" message={error} />}
        {!loading && !error && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="Delivered" value={formatCount(Number(stats.delivered ?? 0), timeCtx)} />
              <Metric label="Human clicks" value={formatCount(Number(stats.human_clicks ?? 0), timeCtx)} />
              <Metric label="Replies" value={formatCount(Number(stats.replies ?? 0), timeCtx)} />
              <Metric label="Bounces" value={formatCount(Number(stats.bounces ?? 0), timeCtx)} />
              <Metric label="Machine events" value={formatCount(Number(stats.machine_events ?? 0), timeCtx)} />
              <Metric label="Sequence step" value={message.sequence_step != null ? String(message.sequence_step) : '—'} />
            </div>
            <div className="text-xs text-text-secondary space-y-1">
              <p>Provider: <span className="text-text-primary">{String(message.provider ?? '—')}</span></p>
              <p>Template: <span className="font-mono">{String(message.external_template_id ?? '—')}</span></p>
              <p>Variant: <span className="font-mono">{String(message.variant_id ?? '—')}</span></p>
              <p>Status: <Badge variant={message.status === 'active' ? 'success' : 'default'}>{String(message.status ?? '—')}</Badge></p>
              <p>First seen: {message.first_seen_at ? formatDateTime(String(message.first_seen_at), timeCtx) : '—'}</p>
            </div>
            <div>
              <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-2">Links</h3>
              {!links.length
                ? <EmptyState title="No link activity" description="No human-qualified clicks recorded for this message yet." />
                : (
                  <DataTable
                    data={links}
                    keyExtractor={r => String(r.link_id)}
                    columns={[
                      { key: 'link_id', header: 'Link', render: r => <span className="font-mono text-xs break-all">{String(r.link_id ?? '')}</span> },
                      { key: 'human_clicks', header: 'Human clicks', render: r => formatCount(Number(r.human_clicks ?? 0), timeCtx) },
                    ]}
                  />
                )
              }
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const POPULATION_STAGES = ['all', 'attempted', 'delivered', 'engaged', 'replied'] as const;

function CommsRecipientsSection({ campaignId }: { campaignId: string }) {
  const timeCtx = useTimeContext();
  const [stage, setStage] = useState<(typeof POPULATION_STAGES)[number]>('all');
  const [rows, setRows] = useState<AnyRecord[]>([]);
  const [stageCounts, setStageCounts] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    (api.campaigns.commsPopulation(campaignId, stage === 'all' ? { limit: 100 } : { stage, limit: 100 }) as Promise<AnyRecord>)
      .then(d => {
        if (!active) return;
        setRows(((d as AnyRecord).items as AnyRecord[]) ?? []);
        setStageCounts(((d as AnyRecord).stage_counts as AnyRecord) ?? {});
      })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [campaignId, stage]);

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Recipients</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-1 border border-border-default rounded-md p-0.5 w-fit" role="tablist" aria-label="Recipient stage">
          {POPULATION_STAGES.map(s => (
            <button
              key={s}
              role="tab"
              aria-selected={stage === s}
              onClick={() => setStage(s)}
              className={`px-3 py-1 text-xs rounded capitalize transition-colors ${stage === s ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'}`}
            >
              {s}{s !== 'all' && stageCounts[s] != null ? ` (${stageCounts[s]})` : ''}
            </button>
          ))}
        </div>
        {loading && <LoadingState lines={4} />}
        {error && <ErrorState title="Recipients unavailable" message={error} />}
        {!loading && !error && (
          !rows.length
            ? <EmptyState title="No recipients" description="No recipients match this stage yet." />
            : (
              <DataTable
                data={rows}
                keyExtractor={r => String(r.recipient_key)}
                columns={[
                  { key: 'recipient_display', header: 'Recipient', render: r => <span className="font-mono text-xs">{String(r.recipient_display ?? r.recipient_key ?? '').slice(0, 24)}</span> },
                  { key: 'stage', header: 'Stage', render: r => <Badge variant={r.stage === 'replied' ? 'success' : r.stage === 'engaged' ? 'success' : 'default'}>{String(r.stage)}</Badge> },
                  { key: 'delivered', header: 'Delivered', render: r => formatCount(Number(r.delivered ?? 0), timeCtx) },
                  { key: 'human_clicks', header: 'Human clicks', render: r => formatCount(Number(r.human_clicks ?? 0), timeCtx) },
                  { key: 'replies', header: 'Replies', render: r => formatCount(Number(r.replies ?? 0), timeCtx) },
                  {
                    key: 'flags', header: 'Flags',
                    render: r => (
                      <span className="flex gap-1">
                        {Boolean(r.bounced) && <Badge variant="danger" size="sm">bounced</Badge>}
                        {Boolean(r.complained) && <Badge variant="danger" size="sm">complained</Badge>}
                        {Boolean(r.unsubscribed) && <Badge variant="warning" size="sm">unsubscribed</Badge>}
                        {Boolean(r.suppressed) && <Badge variant="warning" size="sm">suppressed</Badge>}
                      </span>
                    ),
                  },
                  {
                    key: 'profile', header: 'Profile360',
                    render: r => r.entity_id
                      ? <a className="text-xs text-accent hover:underline" href={appHref(`/users/${String(r.entity_id)}`)}>Open</a>
                      : <span className="text-text-muted text-xs">unresolved</span>,
                  },
                ]}
              />
            )
        )}
      </CardContent>
    </Card>
  );
}

function MessagesTab({ campaignId }: { campaignId: string }) {
  const timeCtx = useTimeContext();
  const [funnel, setFunnel] = useState<AnyRecord | null>(null);
  const [messages, setMessages] = useState<AnyRecord[] | null>(null);
  const [links, setLinks] = useState<AnyRecord[] | null>(null);
  const [mode, setMode] = useState<'provider_reported' | 'human_qualified'>('human_qualified');
  const [selectedMessage, setSelectedMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Contextual comms-empty-state: when no Communications source is connected,
  // the empty Messages state tells the operator how to start populating it.
  const { data: readinessData } = useTenantIntegrationReadiness();
  const comms = contextualReadiness(
    readinessData?.items as TenantReadinessItem[] | undefined,
    ['communications_lifecycle'],
  );
  const commsUnconnected = comms.connect !== null;
  const messagesEmptyAction = commsUnconnected ? (
    <Link
      to={integrationsHref()}
      className="text-xs font-medium text-accent hover:underline"
    >
      Connect a Communications source
    </Link>
  ) : undefined;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      api.campaigns.commsFunnel(campaignId) as Promise<AnyRecord>,
      api.campaigns.messages(campaignId) as Promise<AnyRecord>,
      api.campaigns.links(campaignId) as Promise<AnyRecord>,
    ])
      .then(([f, m, l]) => {
        if (!active) return;
        setFunnel(f as AnyRecord);
        setMessages(((m as AnyRecord)?.items as AnyRecord[]) ?? []);
        setLinks(((l as AnyRecord)?.items as AnyRecord[]) ?? []);
      })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [campaignId]);

  if (loading) return <LoadingState lines={6} />;
  if (error) return <ErrorState title="Messages unavailable" message={error} />;

  const modes = (funnel?.modes as AnyRecord) ?? {};
  const selected = (modes[mode] as AnyRecord) ?? {};
  const delivery = (funnel?.delivery as AnyRecord) ?? {};
  const quality = (funnel?.quality as AnyRecord) ?? {};
  const rateResults = [
    selected.open_rate_result,
    selected.click_rate_result,
    mode === 'human_qualified' ? selected.reply_rate_result : null,
  ].filter(Boolean) as AnyRecord[];
  const limitedRates = rateResults.filter(
    result => String(result.value_state ?? 'observed') !== 'observed',
  );

  return (
    <div className="space-y-4">
      <div
        className="flex gap-1 border border-border-default rounded-md p-0.5 w-fit"
        role="tablist"
        aria-label="Engagement funnel mode"
      >
        {([
          ['human_qualified', 'Human qualified'],
          ['provider_reported', 'Provider reported'],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={mode === value}
            onClick={() => setMode(value)}
            className={`px-3 py-1 text-xs rounded transition-colors ${mode === value ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="text-xs text-text-muted">
        {mode === 'human_qualified'
          ? 'Human-qualified engagement excludes suspected machine activity (security scanners, image proxies) and automated replies.'
          : 'Provider-reported numbers count every provider event, including machine-generated opens and clicks.'}
      </p>

      {limitedRates.length > 0 && (
        <div className="rounded-md border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-xs text-text-secondary">
          Rate values are withheld until the governed minimum sample is met.
          Current states: {limitedRates.map(result => String(result.value_state)).join(', ')}.
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Metric label="Sent" value={formatCount(Number(selected.sent ?? 0), timeCtx)} />
        <Metric label="Delivered" value={formatCount(Number(selected.delivered ?? 0), timeCtx)} />
        <Metric label={mode === 'human_qualified' ? 'Human opens' : 'Reported opens'} value={formatCount(Number(selected.opens ?? 0), timeCtx)} />
        <Metric label={mode === 'human_qualified' ? 'Human clicks' : 'Reported clicks'} value={formatCount(Number(selected.clicks ?? 0), timeCtx)} />
        <Metric label="Replies" value={formatCount(Number(((modes.human_qualified as AnyRecord) ?? {}).replies ?? 0), timeCtx)} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Metric label="Open rate" value={fmtPct(selected.open_rate as number | null)} />
        <Metric label="Click rate" value={fmtPct(selected.click_rate as number | null)} />
        <Metric label="Reply rate" value={fmtPct(selected.reply_rate as number | null)} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric label="Hard bounces" value={formatCount(Number(delivery.hard_bounces ?? 0), timeCtx)} />
        <Metric label="Complaints" value={formatCount(Number(delivery.complaints ?? 0), timeCtx)} />
        <Metric label="Unsubscribes" value={formatCount(Number(delivery.unsubscribes ?? 0), timeCtx)} />
        <Metric label="Suspected machine events" value={fmtPct(quality.machine_event_rate as number | null)} />
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">Messages</CardTitle></CardHeader>
        <CardContent>
          {!messages?.length
            ? <EmptyState
                title="No messages"
                description={commsUnconnected
                  ? 'No provider messages yet — connect a Communications source under Integrations to start populating Messages.'
                  : 'No provider messages observed for this campaign yet.'}
                action={messagesEmptyAction}
              />
            : (
              <DataTable
                data={messages}
                keyExtractor={r => String(r.external_message_id)}
                columns={[
                  { key: 'name', header: 'Message', render: r => String(r.name ?? r.external_message_id ?? '—') },
                  { key: 'sequence_step', header: 'Step', render: r => r.sequence_step != null ? String(r.sequence_step) : '—' },
                  { key: 'status', header: 'Status', render: r => <Badge variant={r.status === 'active' ? 'success' : 'default'}>{String(r.status ?? '—')}</Badge> },
                  { key: 'delivered', header: 'Delivered', render: r => formatCount(Number(r.delivered ?? 0), timeCtx) },
                  { key: 'human_clicks', header: 'Human clicks', render: r => formatCount(Number(r.human_clicks ?? 0), timeCtx) },
                  { key: 'replies', header: 'Replies', render: r => formatCount(Number(r.replies ?? 0), timeCtx) },
                  { key: 'bounces', header: 'Bounces', render: r => formatCount(Number(r.bounces ?? 0), timeCtx) },
                  { key: 'machine_events', header: 'Machine', render: r => formatCount(Number(r.machine_events ?? 0), timeCtx) },
                  {
                    key: 'detail', header: '',
                    render: r => (
                      <button
                        onClick={() => setSelectedMessage(String(r.external_message_id))}
                        className="text-xs text-accent hover:underline"
                        aria-label={`Open detail for message ${String(r.name ?? r.external_message_id)}`}
                      >
                        Detail
                      </button>
                    ),
                  },
                ]}
              />
            )
          }
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Link performance</CardTitle></CardHeader>
        <CardContent>
          {!links?.length
            ? <EmptyState title="No link activity" description="No human-qualified link clicks observed yet." />
            : (
              <DataTable
                data={links}
                keyExtractor={r => String(r.link_id)}
                columns={[
                  { key: 'link_id', header: 'Link', render: r => <span className="font-mono text-xs break-all">{String(r.link_id ?? '')}</span> },
                  { key: 'external_message_id', header: 'Message', render: r => String(r.external_message_id ?? '—') },
                  { key: 'human_clicks', header: 'Human clicks', render: r => formatCount(Number(r.human_clicks ?? 0), timeCtx) },
                  { key: 'unique_clickers', header: 'Unique clickers', render: r => r.unique_clickers != null ? formatCount(Number(r.unique_clickers), timeCtx) : '—' },
                ]}
              />
            )
          }
        </CardContent>
      </Card>

      <CommsRecipientsSection campaignId={campaignId} />

      {selectedMessage && (
        <MessageDetailDrawer
          campaignId={campaignId}
          externalMessageId={selectedMessage}
          onClose={() => setSelectedMessage(null)}
        />
      )}
    </div>
  );
}

// ── Attribution tab ───────────────────────────────────────────────────────────

function AttributionTab({ campaignId }: { campaignId: string }) {
  const timeCtx = useTimeContext();
  const { data, loading, error } = useCampaign360Attribution(campaignId, { model: 'last_touch' });
  if (loading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title="Attribution unavailable" message={error} />;
  if (!data) return null;

  const d = data as AnyRecord;
  const rawDimensionRollups = d.dimension_rollups;
  const dimensionRollups = (
    Array.isArray(rawDimensionRollups)
      ? rawDimensionRollups
      : Array.isArray((rawDimensionRollups as AnyRecord | null)?.items)
        ? (rawDimensionRollups as AnyRecord).items
        : []
  ) as AnyRecord[];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-sm">Attribution credits</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
            <Metric label="Conversions" value={String(d.conversions ?? '—')} />
            <Metric label="Gross revenue" value={d.attributed_gross_revenue != null ? fmtUSD(Number(d.attributed_gross_revenue), timeCtx) : '—'} />
            <Metric label="Net revenue" value={d.attributed_net_revenue != null ? fmtUSD(Number(d.attributed_net_revenue), timeCtx) : '—'} />
          </div>
          <div className="text-xs text-text-muted">
            Model: <strong>{String(d.model ?? 'last_touch')}</strong>
            {' · '}
            Quality: <strong>{String((d.quality as AnyRecord)?.status ?? d.data_quality ?? '—')}</strong>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">AI referral attribution dimensions</CardTitle></CardHeader>
        <CardContent>
          {dimensionRollups.length === 0
            ? <EmptyState title="No dimension rollups" description="Provider, product, mediation, actor, and journey-role credits appear after classified touchpoints are attributed." />
            : (
              <DataTable
                data={dimensionRollups}
                keyExtractor={r => String(r.dimension_key ?? [
                  r.source_class,
                  r.ai_provider ?? r.provider,
                  r.ai_product ?? r.product,
                  r.referral_mediation_type ?? r.mediation,
                  r.actor_type ?? r.actor,
                  r.journey_role ?? r.role,
                  r.verification_level,
                ].join('|'))}
                columns={[
                  { key: 'source_class', header: 'Source class', render: r => String(r.source_class ?? '—') },
                  { key: 'provider', header: 'Provider', render: r => String(r.ai_provider ?? r.provider ?? '—') },
                  { key: 'product', header: 'Product', render: r => String(r.ai_product ?? r.product ?? '—') },
                  { key: 'mediation', header: 'Mediation', render: r => String(r.referral_mediation_type ?? r.mediation ?? '—') },
                  { key: 'actor', header: 'Actor', render: r => String(r.actor_type ?? r.actor ?? '—') },
                  { key: 'role', header: 'Journey role', render: r => String(r.journey_role ?? r.role ?? '—') },
                  { key: 'verification', header: 'Verification', render: r => String(r.verification_level ?? '—') },
                  { key: 'conversions', header: 'Conversions', render: r => formatCount(Number(r.conversions ?? r.attributed_conversions ?? 0), timeCtx) },
                  { key: 'net_revenue', header: 'Net revenue', render: r => fmtUSD(r.attributed_net_revenue ?? r.net_revenue, timeCtx) },
                ]}
              />
            )
          }
        </CardContent>
      </Card>
    </div>
  );
}


// ── Page ──────────────────────────────────────────────────────────────────────

const TABS: readonly { value: string; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'population', label: 'Participants' },
  { value: 'messages', label: 'Communications' },
  { value: 'conversions', label: 'Conversions' },
  { value: 'attribution', label: 'Influence' },
  { value: 'clusters', label: 'Clusters' },
  { value: 'outcome360', label: 'Outcomes' },
  { value: 'economic360', label: 'Value' },
  { value: 'targeting', label: 'Targeting' },
  { value: 'card-linked', label: 'Card-linked' },
  { value: 'sources', label: 'Sources' },
];

/**
 * Campaign 360 (Claude Design handoff: Aether Campaigns, open view). A merged,
 * read-only view of one canonical campaign; every figure is a read from the
 * Campaign 360 endpoints (overview, population, attribution, messages, …).
 */
export function Campaign360Page() {
  const { id: campaignId } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const rawTab = searchParams.get('tab') ?? 'overview';
  const tab = TABS.some(t => t.value === rawTab) ? rawTab : 'overview';
  const timeStart = searchParams.get('start') ?? undefined;
  const timeEnd = searchParams.get('end') ?? undefined;
  const attributionModel = searchParams.get('attribution_model') ?? 'last_touch';
  const population = searchParams.get('population') ?? 'observed';

  const [campaign, setCampaign] = useState<AnyRecord | null>(null);
  const [campaignLoading, setCampaignLoading] = useState(true);
  const [campaignError, setCampaignError] = useState<string | null>(null);

  useEffect(() => {
    if (!campaignId) return;
    setCampaignLoading(true);
    setCampaignError(null);
    (api.campaigns.get(campaignId) as Promise<AnyRecord>)
      .then(d => setCampaign((d as AnyRecord)?.data as AnyRecord ?? d))
      .catch(error => setCampaignError(error instanceof Error ? error.message : String(error)))
      .finally(() => setCampaignLoading(false));
  }, [campaignId]);

  function setTab(value: string, extra?: Record<string, string>) {
    setSearchParams(prev => {
      prev.set('tab', value);
      for (const [k, v] of Object.entries(extra ?? {})) prev.set(k, v);
      return prev;
    }, { replace: true });
  }

  if (!campaignId) return null;

  const name = campaign ? String(campaign.name ?? campaignId) : campaignId;
  const status = campaign ? String(campaign.status ?? 'unknown') : null;
  const channel = campaign?.channel ? String(campaign.channel) : null;
  const platform = campaign ? (campaign.platform ?? campaign.origin ?? campaign.source) : null;
  const start = shortDate(campaign?.start_date ?? campaign?.created_at);
  const end = shortDate(campaign?.end_date);
  const subtitle = [
    start ? `${start}${end ? ` – ${end}` : ''}` : end ? `ends ${end}` : null,
    'read-only copy of the source',
  ].filter(Boolean).join(' · ');

  return (
    <GlassPage>
      <div className="flex flex-col gap-3.5" data-testid="aether-campaign-360">
        <button
          type="button"
          onClick={() => void navigate('/campaigns')}
          className="ae-focus self-start text-[13px] hover:underline"
          style={{ color: 'var(--ae-mute)' }}
        >
          ← Campaigns / <span style={{ color: 'var(--ae-ink)' }}>{name}</span>
        </button>

        {campaignError ? (
          <InlineNotice tone="ember">
            <span className="block font-medium">Failed to load campaign</span>
            <span className="block">{campaignError}</span>
          </InlineNotice>
        ) : (
          <>
            {/* Header card */}
            <div className="ae-glass-card flex flex-wrap items-center justify-between gap-3.5 rounded-[26px]" style={{ padding: 'clamp(14px, 2.6vw, 22px)' }}>
              <span className="flex min-w-0 flex-col gap-1.5">
                <span className="flex flex-wrap items-center gap-2.5">
                  <h1 className="text-[clamp(22px,4.6vw,28px)] font-medium leading-[1.1] tracking-[-0.56px]">{name}</h1>
                  {status && <TonePill tone={statusTone(status)}>{status}</TonePill>}
                  {campaignLoading && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Loading…</span>}
                </span>
                {campaign && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{subtitle}</span>}
                {campaign && (platform || channel) && (
                  <span className="flex flex-wrap items-center gap-1.5">
                    {platform ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-1 pr-2.5 text-[11px]" style={{ borderColor: 'var(--ae-edge-soft)', background: 'var(--ae-glass-card)' }}>
                        <BrandMark token={String(platform)} label={String(platform)} size={16} markSize={11} shape="round" />
                        {String(platform)}
                      </span>
                    ) : null}
                    {channel && <span className="rounded-full border px-2.5 py-0.5 text-[11px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>{channel}</span>}
                  </span>
                )}
              </span>
              <span className="flex flex-wrap gap-2">
                {[['population', 'Participants'], ['messages', 'Communications'], ['sources', 'Sources'], ['economic360', 'Value']].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setTab(value!)}
                    className="ae-focus whitespace-nowrap rounded-full border px-3.5 py-[7px] text-[12px] hover:bg-[var(--ae-glass-card)]"
                    style={{ borderColor: 'var(--ae-edge)' }}
                  >
                    {label} →
                  </button>
                ))}
              </span>
            </div>

            <CampaignIntegrationBanner channel={channel ?? ''} />

            <SegmentedTabs label="Campaign 360 sections" options={TABS} value={tab} onChange={value => setTab(value)} className="self-start" />

            <div key={tab} className="ae-rise flex flex-col gap-3.5" role="tabpanel" aria-label={TABS.find(t => t.value === tab)?.label}>
              {tab === 'overview' && (
                <OverviewTab
                  campaignId={campaignId}
                  {...(timeStart !== undefined ? { timeStart } : {})}
                  {...(timeEnd !== undefined ? { timeEnd } : {})}
                  attributionModel={attributionModel}
                  onOpenPopulation={p => setTab('population', { population: p })}
                  onOpenTab={value => setTab(value)}
                />
              )}
              {tab === 'population' && (
                <PopulationTab
                  campaignId={campaignId}
                  {...(timeStart !== undefined ? { timeStart } : {})}
                  {...(timeEnd !== undefined ? { timeEnd } : {})}
                  population={population}
                  onPopulation={p => setTab('population', { population: p })}
                />
              )}
              {tab === 'messages' && <div className="ae-legacy"><MessagesTab campaignId={campaignId} /></div>}
              {tab === 'clusters' && <div className="ae-legacy"><ClustersTab campaignId={campaignId} /></div>}
              {tab === 'conversions' && (
                <div className="ae-legacy">
                  <ConversionsTab
                    campaignId={campaignId}
                    {...(timeStart !== undefined ? { timeStart } : {})}
                    {...(timeEnd !== undefined ? { timeEnd } : {})}
                  />
                </div>
              )}
              {tab === 'attribution' && <div className="ae-legacy"><AttributionTab campaignId={campaignId} /></div>}
              {tab === 'targeting' && <div className="ae-legacy"><CampaignTargetingIntelligenceTab campaignId={campaignId} /></div>}
              {tab === 'card-linked' && <div className="ae-legacy"><CardLinkedOutcomesTab campaignId={campaignId} /></div>}
              {tab === 'outcome360' && <div className="ae-legacy"><ProjectionSurfacePanel surface="outcome360" focus={{ kind: 'campaign', id: campaignId }} /></div>}
              {tab === 'economic360' && <div className="ae-legacy"><ProjectionSurfacePanel surface="economic360" focus={{ kind: 'campaign', id: campaignId }} /></div>}
              {tab === 'sources' && <SourcesTab campaignId={campaignId} />}
            </div>
          </>
        )}
      </div>
    </GlassPage>
  );
}
