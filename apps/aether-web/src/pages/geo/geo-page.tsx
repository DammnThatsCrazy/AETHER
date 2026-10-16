import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  DataTable, ErrorState, LoadingState, Skeleton,
  formatCount, useTimeContext,
} from '@aether/ui';
import type { TimeWindow } from '@aether/ui';
import { TruthBanner, encodeExplorationContext } from '@aether/ui/exploration';
import { GlassPage } from '@aether-app/components/app-shell';
import { Eyebrow, InlineNotice, LinkButton, SecondaryButton, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { GlassSection, SegmentedTabs, ShareRow, type SegmentOption } from '@aether-app/components/ae-campaigns-geo-ui';
import { useGeoSummary, useGeoEntities } from '@aether-app/features/geo/use-geo';
import {
  useGeoExploration,
  type GeoExplorationRow,
} from '@aether-app/features/geo/use-geo-exploration';
import { GeoDotMap, geoPosition, type MapMarker } from './geo-dot-map';

// ── helpers ────────────────────────────────────────────────────────────────────

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return `${(v * 100).toFixed(1)}%`;
}

function relTime(iso: string | undefined | null): string {
  if (!iso) return '—';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? '');
}

// ── Levels ─────────────────────────────────────────────────────────────────────

const GEO_LEVELS = ['global', 'country', 'state', 'metro', 'city'] as const;
type GeoLevel = typeof GEO_LEVELS[number];

const LEVEL_LABEL: Record<GeoLevel, string> = {
  global: 'World',
  country: 'Country',
  state: 'State / Province',
  metro: 'Metro area',
  city: 'City',
};

function nextLevel(current: GeoLevel): GeoLevel | null {
  const idx = GEO_LEVELS.indexOf(current);
  if (idx < 0 || idx >= GEO_LEVELS.length - 1) return null;
  return GEO_LEVELS[idx + 1] ?? null;
}

// ── Lens (metric) and window ───────────────────────────────────────────────────

type GeoMetric = 'entity_count' | 'conversion_rate' | 'anomaly_flags';

const LENS_LABEL: Record<GeoMetric, string> = {
  entity_count: 'Entity density',
  conversion_rate: 'Conversion',
  anomaly_flags: 'Anomalies',
};

const LENSES: readonly SegmentOption<GeoMetric>[] = (Object.keys(LENS_LABEL) as GeoMetric[]).map(value => ({ value, label: LENS_LABEL[value] }));

const LENS_COLOR: Record<GeoMetric, string> = {
  entity_count: 'var(--ae-blue)',
  conversion_rate: 'var(--ae-sage)',
  anomaly_flags: 'var(--ae-amber)',
};

const WINDOWS: readonly SegmentOption<TimeWindow>[] = [
  { value: '30d', label: '30 days' },
  { value: '60d', label: '60 days' },
  { value: '90d', label: '90 days' },
  { value: 'lifetime', label: 'All time' },
];

interface GeoChild {
  readonly geo_id: string;
  readonly geo_name: string;
  readonly entity_count: number | null;
  readonly conversion_rate: number | null;
  readonly anomaly_flags: number | null;
  readonly raw: Record<string, unknown>;
}

function lensValue(child: GeoChild, metric: GeoMetric): number | null {
  return child[metric];
}

// ── Graph-backed exploration (unchanged contract) ─────────────────────────────

export function GeoExplorationPanel() {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<readonly string[]>([]);
  const [linkError, setLinkError] = useState<string | null>(null);
  const { data: envelope, isLoading, error, client, context } = useGeoExploration(cursor);
  const rows = envelope?.data?.countries ?? [];
  const adapterAvailable = envelope?.execution.adapters.includes('geo') ?? false;

  async function openCountry(row: GeoExplorationRow) {
    setLinkError(null);
    try {
      const resolved = await client.resolveLink({
        context,
        to: 'geo',
        focus: { kind: 'geography.country', id: row.country },
      });
      if (!resolved.adapter_available) {
        setLinkError('Geographic exploration is unavailable in this release.');
        return;
      }
      navigate(`/geo/country/${encodeURIComponent(row.country)}?${encodeExplorationContext(resolved.link.context)}`);
    } catch (reason) {
      setLinkError(reason instanceof Error ? reason.message : 'Unable to preserve exploration context.');
    }
  }

  if (error) return <ErrorState title="Geographic exploration unavailable" message={error} />;
  if (isLoading && !envelope) return <LoadingState lines={5} />;
  if (envelope && !adapterAvailable) {
    return <TruthBanner status="not_enabled" surfaceLabel="Geographic exploration" />;
  }

  return (
    <div className="space-y-3 rounded border border-border-default p-4">
      {envelope && (
        <TruthBanner
          status="ready"
          truth={envelope.truth}
          completeness={envelope.completeness}
          applicability={envelope.applicability}
        />
      )}
      {linkError && <ErrorState title="Unable to open geography" message={linkError} />}
      <DataTable<GeoExplorationRow>
        caption="Graph-backed geographic exploration results"
        columns={[
          { key: 'country', header: 'Country', render: (row) => <code>{row.country}</code> },
          { key: 'count', header: 'Entities returned', render: (row) => formatCount(row.count, timeCtx) },
        ]}
        data={rows}
        keyExtractor={(row) => row.country}
        onRowClick={(row) => void openCountry(row)}
        loading={isLoading}
        selection={{ selectedKeys, onSelectionChange: setSelectedKeys }}
        page={{
          returned: rows.length,
          ...(envelope?.pagination?.total_estimate !== undefined
            ? { total: envelope.pagination.total_estimate }
            : {}),
          ...(envelope?.pagination?.cursor !== undefined
            ? { nextCursor: envelope.pagination.cursor }
            : {}),
          onNext: setCursor,
        }}
        emptyMessage="No graph entities with asserted country data match this exploration."
      />
      {(envelope?.data?.without_geo_count ?? 0) > 0 && (
        <p className="text-xs text-text-muted">
          {envelope!.data!.without_geo_count} returned entities have no asserted country.
        </p>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

function riskTone(score: number): Tone {
  if (score > 0.7) return 'ember';
  if (score > 0.4) return 'amber';
  return 'sage';
}

/**
 * Geography (Claude Design handoff: Aether Geography — stylized dot map and
 * location insights). Every count, rate and marker comes from the tenant geo
 * summary and geo entities endpoints; the land dots are static base geography.
 */
export function GeoPage() {
  const navigate = useNavigate();
  const params = useParams<{ level?: string; geoId?: string }>();
  const timeCtx = useTimeContext();

  const currentLevel: GeoLevel = (GEO_LEVELS as readonly string[]).includes(params.level ?? '') ? (params.level as GeoLevel) : 'global';
  const currentGeoId = params.geoId ?? null;

  const [timeWindow, setTimeWindow] = useState<TimeWindow>('30d');
  const [metric, setMetric] = useState<GeoMetric>('entity_count');
  const [entityOffset, setEntityOffset] = useState(0);
  const [showExploration, setShowExploration] = useState(false);

  const { data: summary, isLoading: summaryLoading, error: summaryError, refetch: refetchSummary } = useGeoSummary({
    level: currentLevel,
    ...(currentGeoId ? { geo_id: currentGeoId } : {}),
    window: timeWindow,
  });

  const { data: entitiesData, isLoading: entitiesLoading, error: entitiesError, refetch: refetchEntities } = useGeoEntities({
    level: currentLevel,
    geo_id: currentGeoId ?? 'global',
    window: timeWindow,
    limit: 20,
    offset: entityOffset,
  });

  const children: GeoChild[] = useMemo(() => (summary?.children ?? []).map(c => {
    const raw = c as unknown as Record<string, unknown>;
    const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
    return {
      geo_id: String(c.geo_id),
      geo_name: fmt(c.geo_name, String(c.geo_id)),
      entity_count: n(c.entity_count),
      conversion_rate: n(c.conversion_rate),
      anomaly_flags: n(c.anomaly_flags),
      raw,
    };
  }), [summary]);

  const next = nextLevel(currentLevel);
  const placeName = currentLevel === 'global' ? 'World' : summary?.geo_name ?? currentGeoId ?? 'World';

  function goTo(level: GeoLevel, geoId: string | null) {
    navigate(geoId ? `/geo/${level}/${encodeURIComponent(geoId)}` : '/geo');
    setEntityOffset(0);
  }

  function drill(child: GeoChild) {
    if (!next) return;
    goTo(next, child.geo_id);
  }

  // Map markers: children that carry or resolve to a position.
  const lensMax = Math.max(0, ...children.map(c => lensValue(c, metric) ?? 0));
  const lensTotal = children.reduce((n, c) => n + (lensValue(c, metric) ?? 0), 0);
  const valueLabel = (v: number | null) => metric === 'conversion_rate' ? fmtPct(v) : v === null ? '—' : formatCount(v, timeCtx);
  const markers: MapMarker[] = [];
  let unplaced = 0;
  for (const c of children) {
    const position = geoPosition(c.raw);
    if (!position) { unplaced += 1; continue; }
    const v = lensValue(c, metric);
    markers.push({
      id: c.geo_id,
      label: c.geo_name,
      position,
      weight: lensMax > 0 && v !== null ? v / lensMax : 0,
      valueLabel: valueLabel(v),
      ...(next ? { onSelect: () => drill(c) } : {}),
    });
  }
  const focus = currentLevel === 'global'
    ? null
    : geoPosition({ ...(summary as unknown as Record<string, unknown> ?? {}), geo_id: currentGeoId ?? '', geo_name: summary?.geo_name ?? '' });

  const tiers = Object.entries(summary?.tier_distribution ?? {}).filter(([, v]) => typeof v === 'number');
  const tierTotal = tiers.reduce((n, [, v]) => n + (v as number), 0);
  const entities = (entitiesData?.entities ?? []) as Array<Record<string, unknown>>;

  return (
    <GlassPage>
      <div className="flex flex-col gap-4" data-testid="aether-geo">
        {/* Header */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <span className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Geography</h1>
            <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>Understand where activity is happening.</span>
          </span>
          <nav aria-label="Geography breadcrumb" className="ae-mono flex flex-wrap items-center gap-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
            {currentLevel === 'global' ? (
              <span style={{ color: 'var(--ae-ink)' }}>World</span>
            ) : (
              <>
                <button type="button" onClick={() => goTo('global', null)} className="ae-focus hover:underline" style={{ color: 'var(--ae-blue-ink)' }}>World</button>
                <span aria-hidden="true">›</span>
                <span style={{ color: 'var(--ae-ink)' }}>{placeName}</span>
              </>
            )}
          </nav>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedTabs label="Time window" options={WINDOWS} value={timeWindow} onChange={v => { setTimeWindow(v); setEntityOffset(0); }} />
          <SegmentedTabs label="Map lens" options={LENSES} value={metric} onChange={setMetric} />
          <button
            type="button"
            onClick={() => setShowExploration(value => !value)}
            aria-expanded={showExploration}
            className="ae-focus whitespace-nowrap rounded-full border px-3.5 py-1.5 text-[13px]"
            style={{ borderColor: 'var(--ae-edge)' }}
          >
            {showExploration ? 'Hide graph exploration' : 'Explore graph-backed geography'}
          </button>
        </div>

        {showExploration && <div className="ae-legacy"><GeoExplorationPanel /></div>}

        {summaryError && (
          <InlineNotice tone="ember">
            <span className="flex flex-wrap items-center justify-between gap-2">
              <span>
                <span className="block font-medium">Failed to load geographic data</span>
                <span className="block">{errorText(summaryError)}</span>
              </span>
              <LinkButton onClick={() => refetchSummary()} tone="ember">Retry</LinkButton>
            </span>
          </InlineNotice>
        )}

        {/* Map + location insights */}
        <div className="grid items-start gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))' }}>
          <div className="ae-glass-card relative flex min-w-0 flex-col gap-2 overflow-hidden rounded-[20px] p-3 sm:p-4" style={{ gridColumn: 'span 1 / span 1' }}>
            <span className="flex flex-wrap items-center justify-between gap-2 px-1">
              <Eyebrow>{LENS_LABEL[metric]} · {placeName}</Eyebrow>
              <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>
                {summary?.computed_at ? `computed ${relTime(summary.computed_at)}` : summary ? 'computed time not reported' : ''}
              </span>
            </span>
            {summaryLoading ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (
              <GeoDotMap
                markers={markers}
                focus={focus}
                color={LENS_COLOR[metric]}
                label={`Map of ${placeName} by ${LENS_LABEL[metric].toLowerCase()}`}
              />
            )}
            {!summaryLoading && !summary && !summaryError && (
              <p className="px-1 text-[13px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
                Geographic intelligence is being provisioned for your account.
                Data will appear here once your geo pipeline is active.
              </p>
            )}
            {summary && children.length > 0 && (unplaced > 0 || markers.length === 0) && (
              <p className="px-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                {markers.length === 0
                  ? `Sub-regions at the ${next ? LEVEL_LABEL[next].toLowerCase() : 'next'} level have no map position; they are listed alongside.`
                  : `${unplaced} region${unplaced === 1 ? '' : 's'} without a map position ${unplaced === 1 ? 'is' : 'are'} listed alongside.`}
              </p>
            )}
          </div>

          <div className="flex min-w-0 flex-col gap-3">
            {/* Drill list */}
            <GlassSection testId="geo-drill">
              <Eyebrow>Drill: {next ? LEVEL_LABEL[next] : 'finest available precision'}</Eyebrow>
              {currentLevel !== 'global' && (
                <button type="button" onClick={() => goTo('global', null)} className="ae-focus flex justify-between rounded-xl px-2.5 py-2 text-left text-[14px] hover:bg-[var(--ae-glass-card)]">
                  <span>← World</span>
                </button>
              )}
              {summaryLoading && <Skeleton className="h-24 w-full" />}
              {!summaryLoading && summary && children.length === 0 && (
                <span className="px-1 text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                  {next ? 'No sub-regions reported at this level.' : 'This is the finest level the evidence supports.'}
                </span>
              )}
              {children.map(child => {
                const v = lensValue(child, metric);
                const share = metric !== 'conversion_rate' && lensTotal > 0 && v !== null ? `${((v / lensTotal) * 100).toFixed(1)}% · ` : '';
                return (
                  <button
                    key={child.geo_id}
                    type="button"
                    onClick={() => drill(child)}
                    disabled={!next}
                    className="ae-focus flex items-center justify-between gap-2.5 rounded-xl px-2.5 py-2 text-left text-[14px] hover:bg-[var(--ae-glass-card)] disabled:cursor-default"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate">{child.geo_name}</span>
                      {(child.anomaly_flags ?? 0) > 0 && <TonePill tone="amber">{child.anomaly_flags} anomal{child.anomaly_flags === 1 ? 'y' : 'ies'}</TonePill>}
                    </span>
                    <span className="ae-mono shrink-0 text-[12px]" style={{ color: 'var(--ae-mute)' }}>{share}{valueLabel(v)}</span>
                  </button>
                );
              })}
            </GlassSection>

            {/* Current place */}
            <GlassSection testId="geo-current">
              <span className="text-[20px] font-medium tracking-[-0.3px]">{placeName}</span>
              {summaryLoading ? (
                <div className="flex flex-col gap-2">
                  {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-6 w-full" />)}
                </div>
              ) : summary ? (
                <>
                  {([
                    ['Entities', summary.entity_count == null ? '—' : formatCount(summary.entity_count, timeCtx)],
                    ['Avg edges / entity', summary.avg_edges_per_entity?.toFixed(1) ?? '—'],
                    ['Conversion rate', fmtPct(summary.conversion_rate)],
                    ['Anomaly flags', summary.anomaly_flags == null ? '—' : String(summary.anomaly_flags)],
                  ] as const).map(([k, v]) => (
                    <div key={k} className="flex justify-between border-t py-1.5 text-[13px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
                      <span style={{ color: 'var(--ae-mute)' }}>{k}</span>
                      <span className="ae-mono text-[12px]" style={k === 'Anomaly flags' && (summary.anomaly_flags ?? 0) > 0 ? { color: 'var(--ae-amber)' } : undefined}>{v}</span>
                    </div>
                  ))}
                  {tiers.length > 0 && (
                    <div className="flex flex-col gap-2 pt-1.5">
                      <Eyebrow>Tier distribution</Eyebrow>
                      {tiers.map(([tier, count]) => (
                        <ShareRow key={tier} label={tier} value={formatCount(count as number, timeCtx)} share={tierTotal > 0 ? ((count as number) / tierTotal) * 100 : null} />
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                  {summaryError ? 'Location figures are unavailable right now.' : 'No location figures yet.'}
                </span>
              )}
              <span className="pt-1 text-[12px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
                Precision: {LEVEL_LABEL[currentLevel].toLowerCase()}. Aether does not show finer detail than the evidence supports.
              </span>
            </GlassSection>
          </div>
        </div>

        {/* Entities at this level */}
        <GlassSection testId="geo-entities">
          <span className="flex flex-wrap items-baseline justify-between gap-2">
            <Eyebrow>People and entities here</Eyebrow>
            {entitiesData && entitiesData.total > 0 && (
              <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>{formatCount(entitiesData.total, timeCtx)} total</span>
            )}
          </span>
          {entitiesLoading && !entitiesData && <Skeleton className="h-24 w-full" />}
          {entitiesError && (
            <InlineNotice tone="ember">
              <span className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">Failed to load geographic entities</span>
                <LinkButton onClick={() => refetchEntities()} tone="ember">Retry</LinkButton>
              </span>
            </InlineNotice>
          )}
          {!entitiesError && entitiesData && entities.length === 0 && (
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No entities found at this location</span>
          )}
          {!entitiesError && entities.length > 0 && (
            <div className="flex flex-col">
              {entities.map(e => {
                const id = String(e.entity_id);
                const name = fmt(e.display_name) !== '—' ? fmt(e.display_name) : fmt(e.entity_id);
                const risk = typeof e.risk_score === 'number' ? e.risk_score : null;
                const ltv = typeof e.ltv === 'number' ? e.ltv : null;
                return (
                  <div key={id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t py-2 text-[13px]" style={{ borderColor: 'var(--ae-edge)' }}>
                    <button
                      type="button"
                      onClick={() => void navigate(`/users/${encodeURIComponent(id)}`)}
                      className="ae-focus min-w-0 flex-1 truncate text-left hover:underline"
                      style={{ color: 'var(--ae-blue-ink)' }}
                    >
                      {name}
                    </button>
                    {e.tier ? <TonePill tone="blue">{fmt(e.tier)}</TonePill> : null}
                    <span className="ae-mono w-20 text-right text-[12px]">{ltv !== null ? `$${formatCount(ltv, timeCtx)}` : '—'}</span>
                    <span className="w-14 text-right">{risk !== null ? <TonePill tone={riskTone(risk)}>risk {Math.round(risk * 100)}</TonePill> : <span style={{ color: 'var(--ae-faint)' }}>—</span>}</span>
                    <span className="w-20 text-right text-[12px]" style={{ color: 'var(--ae-mute)' }}>{relTime(e.last_active_at as string | null)}</span>
                  </div>
                );
              })}
            </div>
          )}
          {entitiesData && entitiesData.total > 20 && (
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              <span className="ae-mono">{entityOffset + 1}–{Math.min(entityOffset + 20, entitiesData.total)} of {entitiesData.total}</span>
              <span className="flex gap-2">
                <SecondaryButton onClick={() => setEntityOffset(Math.max(0, entityOffset - 20))} disabled={entityOffset === 0}>Previous</SecondaryButton>
                <SecondaryButton onClick={() => setEntityOffset(entityOffset + 20)} disabled={entityOffset + 20 >= entitiesData.total}>Next</SecondaryButton>
              </span>
            </div>
          )}
        </GlassSection>
      </div>
    </GlassPage>
  );
}
