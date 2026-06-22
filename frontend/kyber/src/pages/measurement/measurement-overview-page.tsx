import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useMeasurementOverview } from '@kyber/features/measurement';
import { useState } from 'react';

type Row = Record<string, unknown>;

function Metric({ label, value, sub }: { readonly label: string; readonly value: unknown; readonly sub?: string }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? '—')}</div>
        {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy') return 'success';
  if (status === 'degraded') return 'warning';
  if (status === 'error' || status === 'failed') return 'danger';
  return 'default';
}

export function MeasurementOverviewPage() {
  const [window, setWindow] = useState('30d');
  const { data, loading, error } = useMeasurementOverview(window);

  if (loading) return <PageWrapper title="Measurement Overview"><LoadingState lines={8} /></PageWrapper>;
  if (error) return <PageWrapper title="Measurement Overview"><ErrorState title="Unable to load measurement data" message={error} /></PageWrapper>;

  const overview = data.overview as Row;
  const quality = data.quality as Row;
  const health = data.health as Row;
  const connectors = Object.entries((health.connectors as Record<string, Row> | undefined) ?? {}).map(([name, c]) => ({ name, ...c }));
  const warnings = ((overview.warnings as Row[]) ?? []);

  return (
    <PageWrapper
      title="Measurement Overview"
      subtitle="Spend, attributed revenue, ROAS, and data quality across all connected sources."
      action={
        <select value={window} onChange={e => setWindow(e.target.value)} className="text-sm bg-surface-secondary border border-border rounded px-2 py-1">
          <option value="7d">7 days</option>
          <option value="30d">30 days</option>
          <option value="90d">90 days</option>
        </select>
      }
    >
      <div className="grid gap-4 md:grid-cols-4">
        <Metric label="Total spend" value={`$${Number(overview.campaign_spend?.usd_amount ?? 0).toLocaleString()}`} />
        <Metric label="Attributed revenue" value={`$${Number(overview.attributed_revenue?.usd_amount ?? 0).toLocaleString()}`} />
        <Metric label="ROAS" value={overview.roas ? `${Number(overview.roas).toFixed(2)}x` : '—'} sub="Actual spend basis" />
        <Metric label="Entities tracked" value={overview.entity_count ?? 0} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Metric label="Attribution coverage" value={`${Math.round(Number(quality.attribution_coverage ?? 0) * 100)}%`} sub="Conversions with active run" />
        <Metric label="Identity coverage" value={`${Math.round(Number(quality.identity_coverage ?? 0) * 100)}%`} sub="Touchpoints linked to profile" />
        <Metric label="Spend coverage" value={`${Math.round(Number(quality.spend_coverage ?? 0) * 100)}%`} sub="Campaign days with spend records" />
      </div>

      {warnings.length > 0 && (
        <div className="mt-4 space-y-2">
          {warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2 text-sm p-3 rounded bg-surface-secondary border border-border">
              <Badge variant={w.severity === 'error' ? 'danger' : w.severity === 'warning' ? 'warning' : 'default'}>
                {String(w.severity ?? 'info')}
              </Badge>
              <span className="text-text-secondary">{String(w.message ?? '')}</span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4">
        <Card>
          <CardHeader><CardTitle>Connector health</CardTitle></CardHeader>
          <CardContent>
            {connectors.length === 0
              ? <EmptyState title="No connectors configured" description="Connect a paid-media platform to start ingesting spend data." />
              : <DataTable data={connectors} keyExtractor={r => String(r.name)} columns={[
                  { key: 'name', header: 'Connector', render: r => String(r.name) },
                  { key: 'status', header: 'Status', render: r => <Badge variant={statusVariant(String(r.health_status ?? 'unknown'))}>{String(r.health_status ?? 'unknown')}</Badge> },
                  { key: 'last_sync', header: 'Last sync', render: r => String(r.last_success_at ?? '—') },
                  { key: 'type', header: 'Type', render: r => String(r.connector_type ?? '—') },
                ]} />
            }
          </CardContent>
        </Card>
      </div>
    </PageWrapper>
  );
}
