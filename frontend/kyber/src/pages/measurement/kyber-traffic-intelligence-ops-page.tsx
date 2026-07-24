import { useState } from 'react';
import {
  Badge, Card, CardContent, CardHeader, CardTitle,
  EmptyState, ErrorState, FreshnessIndicator, LoadingState,
  formatCount, useTimeContext,
} from '@aether/ui';
import { SOURCE_CLASS_DEFAULTS, canonicalSourceClass, type SourceClass } from '@aether/shared/traffic-source';
import { PageWrapper } from '@kyber/components/layout';
import { useSourceClassificationOps, type TrafficIntelligenceFilters } from '@kyber/features/measurement';

// ── label helpers ────────────────────────────────────────────────────────────

/**
 * Canonical customer-facing label for a source_class value from the generated
 * traffic-source registry. Legacy "direct" normalizes to direct_unknown and
 * renders "Direct / Unknown" — this surface never claims "Typed URL".
 */
function sourceClassLabel(value: string): string {
  const canonical = canonicalSourceClass(value);
  return SOURCE_CLASS_DEFAULTS[canonical as SourceClass]?.label ?? value;
}

/** Human form of registry snake_case values (proof levels, retrieval states). */
function humanize(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatRate(rate: number | undefined | null): string {
  if (rate === null || rate === undefined || !Number.isFinite(Number(rate))) return '—';
  return `${(Number(rate) * 100).toFixed(1)}%`;
}

function rateVariant(rate: number | undefined | null, warn: number, danger: number): 'success' | 'warning' | 'danger' | 'default' {
  if (rate === null || rate === undefined || !Number.isFinite(Number(rate))) return 'default';
  const n = Number(rate);
  if (n >= danger) return 'danger';
  if (n >= warn) return 'warning';
  return 'success';
}

// ── presentational primitives ────────────────────────────────────────────────

function MetricTile({ label, value, hint }: { readonly label: string; readonly value: React.ReactNode; readonly hint?: string }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary tabular-nums">{value}</div>
        {hint && <div className="mt-0.5 text-[10px] text-text-muted">{hint}</div>}
      </CardContent>
    </Card>
  );
}

function RateTile({ label, rate, warn, danger, hint }: {
  readonly label: string;
  readonly rate: number | undefined | null;
  readonly warn: number;
  readonly danger: number;
  readonly hint?: string;
}) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
          <Badge variant={rateVariant(rate, warn, danger)}>{formatRate(rate)}</Badge>
        </div>
        {hint && <div className="mt-1 text-[10px] text-text-muted">{hint}</div>}
      </CardContent>
    </Card>
  );
}

interface BarRow {
  readonly key: string;
  readonly label: string;
  readonly value: number;
}

/** Horizontal bar list — a small dataviz-appropriate rendering for count
 *  breakdowns. Widths are relative to the largest value in the set. */
function BarList({ title, rows, emptyMessage }: { readonly title: string; readonly rows: BarRow[]; readonly emptyMessage: string }) {
  const timeCtx = useTimeContext();
  const max = rows.reduce((m, r) => Math.max(m, r.value), 0);
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {rows.length === 0
          ? <p className="text-xs text-text-muted">{emptyMessage}</p>
          : (
            <div className="space-y-1.5">
              {rows.map(row => {
                const pct = max > 0 ? Math.round((row.value / max) * 100) : 0;
                return (
                  <div key={row.key} className="flex items-center gap-3 text-xs">
                    <span className="w-36 shrink-0 truncate text-text-secondary" title={row.label}>{row.label}</span>
                    <div className="flex-1 h-2 rounded-full bg-surface-subtle overflow-hidden">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-14 text-right font-mono tabular-nums text-text-primary">{formatCount(row.value, timeCtx)}</span>
                  </div>
                );
              })}
            </div>
          )
        }
      </CardContent>
    </Card>
  );
}

/** State-count tiles (e.g. handoff success/expired/failed) with per-state variant. */
function StateTiles({ title, entries, variantFor, hint }: {
  readonly title: string;
  readonly entries: [string, number][];
  readonly variantFor?: (state: string) => 'success' | 'warning' | 'danger' | 'default';
  readonly hint?: string;
}) {
  const timeCtx = useTimeContext();
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {entries.length === 0
          ? <p className="text-xs text-text-muted">No data</p>
          : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {entries.map(([state, count]) => (
                <div key={state} className="rounded border border-border-subtle bg-surface-raised p-2">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-text-muted truncate" title={humanize(state)}>{humanize(state)}</span>
                    {variantFor && <span className={`h-1.5 w-1.5 rounded-full ${dotClass(variantFor(state))}`} />}
                  </div>
                  <div className="mt-1 font-mono text-sm text-text-primary tabular-nums">{formatCount(count, timeCtx)}</div>
                </div>
              ))}
            </div>
          )
        }
        {hint && <p className="mt-2 text-[10px] text-text-muted">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function dotClass(variant: 'success' | 'warning' | 'danger' | 'default'): string {
  if (variant === 'success') return 'bg-green-500';
  if (variant === 'warning') return 'bg-yellow-400';
  if (variant === 'danger') return 'bg-red-500';
  return 'bg-text-muted';
}

function num(value: number | undefined | null): number {
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

// ── page ──────────────────────────────────────────────────────────────────────

function defaultRange(): { start: string; end: string } {
  const today = new Date();
  const start = new Date(today.getTime() - 30 * 86400000);
  return { start: start.toISOString().slice(0, 10), end: today.toISOString().slice(0, 10) };
}

export function KyberTrafficIntelligenceOpsPage() {
  const initial = defaultRange();
  const [tenant, setTenant] = useState('');
  const [platform, setPlatform] = useState('');
  const [sdk, setSdk] = useState('');
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const timeCtx = useTimeContext();

  const filters: TrafficIntelligenceFilters = { tenant, platform, sdk, start, end };
  const { data, loading, error, fetchedAt, refresh } = useSourceClassificationOps(filters);

  return (
    <PageWrapper
      title="Traffic Intelligence Operations"
      subtitle="Source-classification operations scorecard — proof integrity, classification drift, deep-link and deferred-attribution health across the fleet."
    >
      <div className="space-y-4">
        {/* Filters */}
        <Card>
          <CardContent className="p-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
              <div>
                <label htmlFor="ti-tenant" className="text-xs text-text-muted block mb-1">Tenant</label>
                <input id="ti-tenant" type="text" value={tenant} placeholder="all tenants"
                  onChange={e => setTenant(e.target.value)}
                  className="w-full text-sm font-mono bg-surface-secondary border border-border rounded px-2 py-1" />
              </div>
              <div>
                <label htmlFor="ti-platform" className="text-xs text-text-muted block mb-1">Platform</label>
                <select id="ti-platform" value={platform}
                  onChange={e => setPlatform(e.target.value)}
                  className="w-full text-sm bg-surface-secondary border border-border rounded px-2 py-1">
                  <option value="">All platforms</option>
                  <option value="web">Web</option>
                  <option value="ios">iOS</option>
                  <option value="android">Android</option>
                  <option value="server">Server</option>
                </select>
              </div>
              <div>
                <label htmlFor="ti-sdk" className="text-xs text-text-muted block mb-1">SDK</label>
                <input id="ti-sdk" type="text" value={sdk} placeholder="all SDKs"
                  onChange={e => setSdk(e.target.value)}
                  className="w-full text-sm font-mono bg-surface-secondary border border-border rounded px-2 py-1" />
              </div>
              <div>
                <label htmlFor="ti-start" className="text-xs text-text-muted block mb-1">Start</label>
                <input id="ti-start" type="date" value={start}
                  onChange={e => setStart(e.target.value)}
                  className="w-full text-sm bg-surface-secondary border border-border rounded px-2 py-1" />
              </div>
              <div>
                <label htmlFor="ti-end" className="text-xs text-text-muted block mb-1">End</label>
                <input id="ti-end" type="date" value={end}
                  onChange={e => setEnd(e.target.value)}
                  className="w-full text-sm bg-surface-secondary border border-border rounded px-2 py-1" />
              </div>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-[10px] text-text-muted">
                Window {data?.window?.start ?? start} → {data?.window?.end ?? end}
                {data?.tenant_id ? ` · tenant ${data.tenant_id}` : ''}
              </span>
              <FreshnessIndicator computedAt={fetchedAt ?? undefined} onRefresh={refresh} />
            </div>
          </CardContent>
        </Card>

        {loading && <LoadingState lines={8} />}
        {error && <ErrorState title="Traffic intelligence operations unavailable" message={error} />}

        {!loading && !error && !data && (
          <EmptyState title="No operations data" description="Metrics appear after source classification has processed acquisition touchpoints for this filter." />
        )}

        {!loading && !error && data && (
          <>
            {/* Totals */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              <MetricTile label="Touchpoints" value={formatCount(num(data.totals?.touchpoints), timeCtx)} />
              <MetricTile label="Attribution eligible" value={formatCount(num(data.totals?.attribution_eligible), timeCtx)} />
              <MetricTile label="Machine excluded" value={formatCount(num(data.totals?.machine_excluded), timeCtx)} />
            </div>

            {/* Rates */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <RateTile label="Direct / Unknown rate" rate={data.direct_unknown_rate} warn={0.4} danger={0.6}
                hint="Share of touchpoints with no referral evidence — the honest fallback, not a typed-URL claim." />
              <RateTile label="Classification drift" rate={data.classification_drift?.legacy_vs_canonical_divergence_rate} warn={0.05} danger={0.15}
                hint="Legacy vs canonical divergence rate." />
              <RateTile label="UTM inconsistency" rate={data.utm_inconsistency_rate} warn={0.1} danger={0.25}
                hint="Declared UTM parameters conflicting with observed evidence." />
            </div>

            {/* Integrity counts */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <MetricTile label="Invalid source links" value={formatCount(num(data.invalid_source_link_count), timeCtx)}
                hint="Failed proof / invalid signed source links" />
              <MetricTile label="Source-link replay attempts" value={formatCount(num(data.source_link_replay_count), timeCtx)} />
              <MetricTile label="Evidence conflicts" value={formatCount(num(data.evidence_conflict_count), timeCtx)} />
              <MetricTile label="SDK deep-link parse failures" value={formatCount(num(data.sdk_deep_link_parse_failures), timeCtx)} />
            </div>

            {/* Classification breakdowns */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <BarList
                title="Classification by source class"
                emptyMessage="No classified touchpoints in this window."
                rows={Object.entries(data.classification_by_source_class ?? {})
                  .map(([sourceClass, count]) => ({ key: sourceClass, label: sourceClassLabel(sourceClass), value: num(count) }))
                  .sort((a, b) => b.value - a.value)}
              />
              <BarList
                title="Classification by proof level"
                emptyMessage="No proof-level data in this window."
                rows={Object.entries(data.classification_by_proof_level ?? {})
                  .map(([proof, count]) => ({ key: proof, label: humanize(proof), value: num(count) }))
                  .sort((a, b) => b.value - a.value)}
              />
            </div>

            {/* Deep-link / referrer / handoff / deferred health */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <StateTiles
                title="Install-referrer retrieval"
                entries={Object.entries(data.install_referrer_retrieval ?? {}).map(([s, c]) => [s, num(c)] as [string, number])}
                variantFor={s => (s.includes('fail') || s.includes('timeout') || s.includes('error') ? 'danger' : s.includes('ok') || s.includes('success') || s.includes('retrieved') ? 'success' : 'default')}
              />
              <StateTiles
                title="Link-use / handoff correlation"
                entries={[
                  ['success', num(data.handoff_correlation?.success)],
                  ['expired', num(data.handoff_correlation?.expired)],
                  ['failed', num(data.handoff_correlation?.failed)],
                ]}
                variantFor={s => (s === 'success' ? 'success' : s === 'expired' ? 'warning' : 'danger')}
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <StateTiles
                title="Deferred attribution"
                entries={[
                  ['resolved', num(data.deferred_attribution?.resolved)],
                  ['unmatched', num(data.deferred_attribution?.unmatched)],
                  ['expired', num(data.deferred_attribution?.expired)],
                ]}
                variantFor={s => (s === 'resolved' ? 'success' : s === 'unmatched' ? 'warning' : 'danger')}
                hint={(() => {
                  const r = num(data.deferred_attribution?.resolved);
                  const total = r + num(data.deferred_attribution?.unmatched) + num(data.deferred_attribution?.expired);
                  return `Resolution rate: ${total > 0 ? `${((r / total) * 100).toFixed(1)}%` : '—'}`;
                })()}
              />
              <StateTiles
                title="Reclassification jobs"
                entries={[
                  ['running', num(data.reclassification_jobs?.running)],
                  ['completed', num(data.reclassification_jobs?.completed)],
                  ['failed', num(data.reclassification_jobs?.failed)],
                ]}
                variantFor={s => (s === 'completed' ? 'success' : s === 'running' ? 'default' : 'danger')}
              />
            </div>

            {/* Single deep-link counts */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              <MetricTile label="Universal / app-link processing" value={formatCount(num(data.universal_link_processing_count), timeCtx)} />
              <MetricTile label="AdAttributionKit ingestion" value={formatCount(num(data.adattributionkit_ingestion_count), timeCtx)} />
              <MetricTile label="Deferred handoff expirations" value={formatCount(num(data.deferred_attribution?.expired), timeCtx)} />
            </div>
          </>
        )}
      </div>
    </PageWrapper>
  );
}
