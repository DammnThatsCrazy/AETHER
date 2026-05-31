import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, ErrorState, GlyphIcon, LoadingState, Skeleton,
  TerminalSeparator, TimeWindowSelector,
} from '@aether/ui';
import type { TimeWindow } from '@aether/ui';
import { useGeoSummary, useGeoEntities } from '@aether-app/features/geo/use-geo';

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

// ── Breadcrumb ─────────────────────────────────────────────────────────────────

const GEO_LEVELS = ['global', 'country', 'state', 'metro', 'city'] as const;
type GeoLevel = typeof GEO_LEVELS[number];

function nextLevel(current: GeoLevel): GeoLevel | null {
  const idx = GEO_LEVELS.indexOf(current);
  if (idx < 0 || idx >= GEO_LEVELS.length - 1) return null;
  return GEO_LEVELS[idx + 1] ?? null;
}

interface BreadcrumbItem {
  level: GeoLevel;
  geo_id: string | null;
  label: string;
}

function Breadcrumb({ items, onNavigate }: { items: BreadcrumbItem[]; onNavigate: (level: GeoLevel, geoId: string | null) => void }) {
  return (
    <div className="flex items-center gap-1 font-mono text-xs text-text-muted">
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <span>›</span>}
          {i < items.length - 1 ? (
            <button
              onClick={() => onNavigate(item.level, item.geo_id)}
              className="text-accent underline hover:no-underline"
            >
              {item.label}
            </button>
          ) : (
            <span className="text-text-primary">{item.label}</span>
          )}
        </span>
      ))}
    </div>
  );
}

// ── Metric chips ───────────────────────────────────────────────────────────────

type GeoMetric = 'entity_count' | 'conversion_rate' | 'anomaly_flags';
const METRICS: { value: GeoMetric; label: string }[] = [
  { value: 'entity_count', label: 'Entity Density' },
  { value: 'conversion_rate', label: 'Attribution' },
  { value: 'anomaly_flags', label: 'Anomaly Distribution' },
];

// ── Main page ──────────────────────────────────────────────────────────────────

export function GeoPage() {
  const navigate = useNavigate();
  const params = useParams<{ level?: string; geoId?: string }>();

  const currentLevel = (params.level as GeoLevel) ?? 'global';
  const currentGeoId = params.geoId ?? null;

  const [window, setWindow] = useState<TimeWindow>('30d');
  const [metric, setMetric] = useState<GeoMetric>('entity_count');
  const [entityOffset, setEntityOffset] = useState(0);

  const { data: summary, isLoading: summaryLoading, error: summaryError } = useGeoSummary({
    level: currentLevel,
    ...(currentGeoId ? { geo_id: currentGeoId } : {}),
    window,
  });

  const { data: entitiesData, isLoading: entitiesLoading } = useGeoEntities({
    level: currentLevel,
    geo_id: currentGeoId ?? 'global',
    window,
    limit: 20,
    offset: entityOffset,
  });

  // Build breadcrumb trail from URL
  const breadcrumbItems: BreadcrumbItem[] = [{ level: 'global', geo_id: null, label: 'Global' }];
  if (currentLevel !== 'global' && currentGeoId) {
    breadcrumbItems.push({ level: currentLevel, geo_id: currentGeoId, label: summary?.geo_name ?? currentGeoId });
  }

  function handleNavigate(level: GeoLevel, geoId: string | null) {
    if (!geoId) {
      navigate('/geo');
    } else {
      navigate(`/geo/${level}/${geoId}`);
    }
    setEntityOffset(0);
  }

  function handleDrillDown(child: { geo_id: string; geo_name: string }) {
    const next = nextLevel(currentLevel);
    if (!next) return;
    navigate(`/geo/${next}/${child.geo_id}`);
    setEntityOffset(0);
  }

  type EntityRow = Record<string, unknown>;
  type ChildRow = Record<string, unknown>;

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-sm font-mono text-text-muted">Geographic Intelligence</span>
          <div className="mt-1">
            <Breadcrumb items={breadcrumbItems} onNavigate={handleNavigate} />
          </div>
        </div>
        <TimeWindowSelector value={window} onChange={setWindow} />
      </div>

      {/* Metric selector */}
      <div className="flex gap-2 mb-6">
        {METRICS.map(m => (
          <button
            key={m.value}
            onClick={() => setMetric(m.value)}
            className={`font-mono text-xs px-3 py-1 rounded border transition-colors ${
              metric === m.value
                ? 'bg-accent/20 text-accent border-accent/40'
                : 'text-text-muted border-border-default hover:text-text-secondary'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {summaryLoading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-20" />)}
        </div>
      )}

      {summaryError && <ErrorState message="Failed to load geographic data" />}

      {!summaryLoading && !summary && !summaryError && (
        <div className="rounded border border-border-subtle bg-surface-raised px-4 py-6 text-center mb-6">
          <p className="text-sm font-mono text-text-muted">
            Geographic intelligence is being provisioned for your account.
            Data will appear here once your geo pipeline is active.
          </p>
        </div>
      )}

      {!summaryLoading && summary && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-text-muted font-mono">Entities</p>
                <p className="text-2xl font-mono text-accent mt-1">
                  {(summary.entity_count ?? 0).toLocaleString()}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-text-muted font-mono">Avg edges / entity</p>
                <p className="text-2xl font-mono text-text-primary mt-1">
                  {summary.avg_edges_per_entity?.toFixed(1) ?? '—'}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-text-muted font-mono">Conversion rate</p>
                <p className="text-2xl font-mono text-text-primary mt-1">
                  {fmtPct(summary.conversion_rate)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-text-muted font-mono">Anomaly flags</p>
                <p className={`text-2xl font-mono mt-1 ${(summary.anomaly_flags ?? 0) > 0 ? 'text-warning' : 'text-text-primary'}`}>
                  {summary.anomaly_flags ?? 0}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Tier distribution */}
          {summary.tier_distribution && Object.keys(summary.tier_distribution).length > 0 && (
            <>
              <TerminalSeparator label="tier distribution" className="mb-3" />
              <div className="flex gap-3 mb-6 flex-wrap">
                {Object.entries(summary.tier_distribution).map(([tier, count]) => (
                  <div key={tier} className="bg-surface-raised border border-border-default rounded px-3 py-2 text-xs font-mono">
                    <span className="text-text-muted">{tier}: </span>
                    <span className="text-text-primary">{(count as number).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Drill-down table */}
          {summary.children && summary.children.length > 0 && (
            <>
              <TerminalSeparator label={`drill down → ${nextLevel(currentLevel) ?? 'N/A'}`} className="mb-3" />
              <DataTable<ChildRow>
                keyExtractor={c => String(c.geo_id)}
                data={summary.children as ChildRow[]}
                emptyMessage="No sub-regions"
                columns={[
                  {
                    key: 'name',
                    header: 'Region',
                    render: c => (
                      <button
                        onClick={() => handleDrillDown(c as { geo_id: string; geo_name: string })}
                        className="text-accent underline hover:no-underline font-mono text-sm"
                      >
                        {fmt(c.geo_name)}
                      </button>
                    ),
                  },
                  { key: 'entities', header: 'Entities', render: c => <span className="font-mono">{(c.entity_count as number ?? 0).toLocaleString()}</span> },
                  { key: 'conv', header: 'Conv. rate', render: c => fmtPct(c.conversion_rate as number | null) },
                  {
                    key: 'anomaly',
                    header: 'Anomalies',
                    render: c => {
                      const flags = c.anomaly_flags as number ?? 0;
                      return flags > 0 ? <Badge variant="warning" size="sm">{flags}</Badge> : <span className="text-text-muted">—</span>;
                    },
                  },
                ]}
              />
            </>
          )}
        </>
      )}

      {/* Entity list */}
      <TerminalSeparator label="entities at this level" className="my-6" />

      {entitiesLoading && <LoadingState lines={5} />}

      {!entitiesLoading && entitiesData && (
        <>
          <DataTable<EntityRow>
            keyExtractor={e => String(e.entity_id)}
            data={entitiesData.entities as EntityRow[]}
            emptyMessage="No entities found at this location"
            columns={[
              {
                key: 'name',
                header: 'Entity',
                render: e => (
                  <button
                    onClick={() => navigate(`/users/${String(e.entity_id)}`)}
                    className="text-accent underline hover:no-underline text-sm"
                  >
                    {fmt(e.display_name) !== '—' ? fmt(e.display_name) : fmt(e.entity_id)}
                  </button>
                ),
              },
              {
                key: 'tier',
                header: 'Tier',
                render: e => e.tier ? <Badge variant="default" size="sm">{fmt(e.tier)}</Badge> : <span className="text-text-muted">—</span>,
              },
              {
                key: 'ltv',
                header: 'LTV',
                render: e => e.ltv != null
                  ? <span className="font-mono">${(e.ltv as number).toLocaleString()}</span>
                  : <span className="text-text-muted">—</span>,
              },
              {
                key: 'risk',
                header: 'Risk',
                render: e => e.risk_score != null ? (
                  <Badge variant={Number(e.risk_score) > 0.7 ? 'danger' : Number(e.risk_score) > 0.4 ? 'warning' : 'success'} size="sm">
                    {Math.round(Number(e.risk_score) * 100)}
                  </Badge>
                ) : <span className="text-text-muted">—</span>,
              },
              { key: 'last_active', header: 'Last active', render: e => relTime(e.last_active_at as string) },
              {
                key: 'action',
                header: '',
                render: e => (
                  <Button variant="ghost" size="sm" onClick={() => navigate(`/users/${String(e.entity_id)}`)}>
                    <GlyphIcon glyph="[>]" />
                  </Button>
                ),
              },
            ]}
          />

          {/* Pagination */}
          {entitiesData.total > 20 && (
            <div className="flex items-center justify-between mt-3 font-mono text-xs text-text-muted">
              <span>{entityOffset + 1}–{Math.min(entityOffset + 20, entitiesData.total)} of {entitiesData.total}</span>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => setEntityOffset(Math.max(0, entityOffset - 20))} disabled={entityOffset === 0}>
                  {'<'} Prev
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setEntityOffset(entityOffset + 20)} disabled={entityOffset + 20 >= entitiesData.total}>
                  Next {'>'}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
