import { useCallback, useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';

function useKyberFetch<T>(url: string | null): { data: T | null; loading: boolean; error: string | null; refetch: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const refetch = useCallback(() => setTick(t => t + 1), []);
  useEffect(() => {
    if (!url) return;
    let active = true;
    setLoading(true);
    setError(null);
    fetch(url, { credentials: 'include' })
      .then(r => r.ok ? r.json() as Promise<{ data: T }> : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(json => { if (active) setData(json.data ?? (json as unknown as T)); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [url, tick]);
  return { data, loading, error, refetch };
}

type Row = Record<string, unknown>;

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtPct(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function Gauge({ label, value }: { label: string; value: number | null }) {
  const pct = value !== null ? Math.min(100, Math.max(0, value * 100)) : 0;
  const color = pct >= 90 ? 'bg-success' : pct >= 70 ? 'bg-warning' : 'bg-danger';
  const textColor = pct >= 90 ? 'text-success' : pct >= 70 ? 'text-warning' : 'text-danger';
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className={`font-semibold ${textColor}`}>{value !== null ? `${pct.toFixed(1)}%` : '—'}</span>
      </div>
      <div className="h-2 bg-surface-overlay rounded-full">
        <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function QualityPanel({ quality }: { quality: Row }) {
  return (
    <div className="space-y-4">
      <Gauge label="Spend mapping rate" value={quality.spend_mapping_rate as number | null} />
      <Gauge label="Touchpoint mapping rate" value={quality.touchpoint_mapping_rate as number | null} />
      <div className="grid grid-cols-3 gap-3 pt-2">
        <div className="bg-surface-raised border border-border-default rounded px-3 py-2">
          <p className="text-xs text-text-secondary">Open reviews</p>
          <p className="text-lg font-semibold text-text-primary">{fmt(quality.open_reviews)}</p>
        </div>
        <div className="bg-surface-raised border border-border-default rounded px-3 py-2">
          <p className="text-xs text-text-secondary">Total campaigns</p>
          <p className="text-lg font-semibold text-text-primary">{fmt(quality.total_campaigns)}</p>
        </div>
        <div className="bg-surface-raised border border-border-default rounded px-3 py-2">
          <p className="text-xs text-text-secondary">External campaigns</p>
          <p className="text-lg font-semibold text-text-primary">{fmt(quality.external_campaigns)}</p>
        </div>
      </div>
    </div>
  );
}

export function CampaignRegistryHealthPage() {
  const [tenantId, setTenantId] = useState('');
  const [submittedTenant, setSubmittedTenant] = useState('');
  const [reprocessing, setReprocessing] = useState(false);
  const [reprocessResult, setReprocessResult] = useState<string | null>(null);

  const { data: fleetData, loading: fleetLoading, error: fleetError } =
    useKyberFetch<{ quality: Row }>('/v1/kyber/measurement/campaign/fleet-health');

  const { data: tenantData, loading: tenantLoading, error: tenantError, refetch: refetchTenant } =
    useKyberFetch<{ tenant_id: string; quality: Row; open_reviews_sample: Row[] }>(
      submittedTenant ? `/v1/kyber/measurement/campaign/tenant/${submittedTenant}` : null,
    );

  const { data: auditData, loading: auditLoading } =
    useKyberFetch<{ audit_entries: Row[]; count: number }>('/v1/kyber/measurement/campaign/audit');

  async function handleReprocess(dryRun: boolean) {
    if (!submittedTenant) return;
    setReprocessing(true);
    setReprocessResult(null);
    try {
      const res = await fetch(`/v1/kyber/measurement/campaign/tenant/${submittedTenant}/reprocess`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 500, dry_run: dryRun }),
      });
      const json = await res.json() as { data?: { status?: string; message?: string } };
      setReprocessResult(json.data?.message ?? json.data?.status ?? 'Queued');
      refetchTenant?.();
    } catch (err) {
      setReprocessResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setReprocessing(false);
    }
  }

  const quality = (fleetData?.quality ?? {}) as Row;
  const tenantQuality = (tenantData?.quality ?? {}) as Row;
  const reviews = (tenantData?.open_reviews_sample ?? []) as Row[];
  const auditEntries = (auditData?.audit_entries ?? []) as Row[];

  return (
    <PageWrapper
      title="Campaign Registry Health"
      subtitle="Fleet-wide campaign resolution metrics, per-tenant drill-down, and operator actions."
    >
      <div className="space-y-6">
        {/* Fleet health */}
        <Card>
          <CardHeader>
            <CardTitle>Fleet-wide resolution health</CardTitle>
          </CardHeader>
          <CardContent>
            {fleetLoading && <LoadingState lines={3} />}
            {fleetError && <ErrorState title="Failed to load fleet health" message={fleetError} />}
            {!fleetLoading && !fleetError && <QualityPanel quality={quality} />}
          </CardContent>
        </Card>

        {/* Tenant drill-down */}
        <Card>
          <CardHeader>
            <CardTitle>Tenant drill-down</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <input
                value={tenantId}
                onChange={e => setTenantId(e.target.value)}
                placeholder="Tenant ID…"
                className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 flex-1"
                aria-label="Tenant ID for drill-down"
              />
              <button
                onClick={() => setSubmittedTenant(tenantId)}
                disabled={!tenantId.trim()}
                className="px-4 py-1.5 text-sm bg-accent text-white rounded disabled:opacity-50"
              >
                Load
              </button>
              {submittedTenant && (
                <button
                  onClick={() => { setTenantId(''); setSubmittedTenant(''); setReprocessResult(null); }}
                  className="px-4 py-1.5 text-sm border border-border rounded"
                >
                  Clear
                </button>
              )}
            </div>

            {tenantLoading && <LoadingState lines={3} />}
            {tenantError && <ErrorState title="Failed to load tenant health" message={tenantError} />}

            {tenantData && !tenantLoading && (
              <div className="space-y-4">
                <QualityPanel quality={tenantQuality} />

                {/* Operator actions */}
                <div className="flex items-center gap-2 pt-2">
                  <button
                    onClick={() => handleReprocess(true)}
                    disabled={reprocessing}
                    className="px-3 py-1.5 text-xs border border-border rounded hover:bg-surface-raised disabled:opacity-50"
                    aria-label="Dry-run reprocessing for this tenant"
                  >
                    Dry-run reprocess
                  </button>
                  <button
                    onClick={() => {
                      if (window.confirm(`Trigger campaign resolution reprocessing for tenant ${submittedTenant}?`)) {
                        handleReprocess(false);
                      }
                    }}
                    disabled={reprocessing}
                    className="px-3 py-1.5 text-xs bg-accent text-white rounded disabled:opacity-50"
                    aria-label="Trigger reprocessing for this tenant"
                  >
                    {reprocessing ? 'Queuing…' : 'Trigger reprocess'}
                  </button>
                </div>
                {reprocessResult && (
                  <p className="text-xs text-text-secondary" aria-live="polite">{reprocessResult}</p>
                )}

                {/* Open reviews sample */}
                {reviews.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-2">
                      Open mapping reviews (up to 20)
                    </p>
                    <DataTable<Row>
                      keyExtractor={r => fmt(r.review_id ?? r.id)}
                      data={reviews}
                      columns={[
                        { key: 'id', header: 'Review ID', render: r => <code className="text-xs font-mono">{fmt(r.review_id ?? r.id).slice(0, 8)}</code> },
                        { key: 'count', header: 'Observed', render: r => fmt(r.observed_count) },
                        { key: 'affected', header: 'Touchpoints', render: r => fmt(r.affected_touchpoints) },
                        { key: 'first', header: 'First seen', render: r => fmt(r.first_seen_at) },
                        { key: 'last', header: 'Last seen', render: r => fmt(r.last_seen_at) },
                      ]}
                    />
                  </div>
                )}
                {reviews.length === 0 && submittedTenant && !tenantLoading && (
                  <EmptyState title="No open mapping reviews" description="All campaign evidence has been resolved for this tenant." />
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Audit log */}
        <Card>
          <CardHeader>
            <CardTitle>Resolution audit log</CardTitle>
          </CardHeader>
          <CardContent>
            {auditLoading && <LoadingState lines={3} />}
            {auditEntries.length === 0 && !auditLoading && (
              <EmptyState title="No resolved reviews" description="Manual resolution actions will appear here." />
            )}
            {auditEntries.length > 0 && (
              <DataTable<Row>
                keyExtractor={r => fmt(r.review_id ?? r.id)}
                data={auditEntries}
                columns={[
                  { key: 'id', header: 'Review ID', render: r => <code className="text-xs font-mono">{fmt(r.review_id ?? r.id).slice(0, 8)}</code> },
                  { key: 'resolved_campaign', header: 'Campaign UUID', render: r => <code className="text-xs font-mono">{fmt(r.resolved_campaign_id).slice(0, 8)}</code> },
                  { key: 'resolved_by', header: 'Resolved by', render: r => fmt(r.resolved_by) },
                  { key: 'resolved_at', header: 'Resolved at', render: r => fmt(r.resolved_at) },
                  { key: 'note', header: 'Note', render: r => r.resolution_note ? <span className="text-xs text-text-secondary">{fmt(r.resolution_note)}</span> : <span className="text-text-muted">—</span> },
                ]}
              />
            )}
          </CardContent>
        </Card>
      </div>
    </PageWrapper>
  );
}
