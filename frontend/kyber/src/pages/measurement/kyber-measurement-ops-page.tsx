import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useMeasurementOps } from '@kyber/features/measurement';
import { useState } from 'react';

type Row = Record<string, unknown>;

function ConfirmButton({ label, onConfirm, disabled }: { readonly label: string; readonly onConfirm: () => Promise<unknown>; readonly disabled?: boolean }) {
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <span className="flex gap-2">
        <button onClick={() => setConfirming(false)} className="text-xs px-2 py-1 rounded border border-border">Cancel</button>
        <button
          onClick={async () => { setPending(true); setConfirming(false); try { await onConfirm(); } finally { setPending(false); } }}
          className="text-xs px-2 py-1 rounded bg-danger text-white"
        >Confirm</button>
      </span>
    );
  }
  return (
    <button
      disabled={disabled || pending}
      onClick={() => setConfirming(true)}
      className="text-xs px-2 py-1 rounded border border-border hover:bg-surface-secondary disabled:opacity-50"
    >
      {pending ? '…' : label}
    </button>
  );
}

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy') return 'success';
  if (status === 'degraded') return 'warning';
  if (status === 'error' || status === 'failed') return 'danger';
  return 'default';
}

export function KyberMeasurementOpsPage() {
  const { overview, loading, error, restartConnector, backfillConnector, recomputeConversion, recomputeAll } = useMeasurementOps();
  const [recomputeTenantId, setRecomputeTenantId] = useState('');

  if (loading) return <PageWrapper title="Measurement Operations"><LoadingState lines={8} /></PageWrapper>;
  if (error) return <PageWrapper title="Measurement Operations"><ErrorState title="Unable to load operations data" message={error} /></PageWrapper>;

  const connectors: Row[] = Object.entries((overview.connectors as Record<string, Row> | undefined) ?? {}).map(([id, c]) => ({ connector_id: id, ...c }));
  const tenants = (overview.tenants as Row[] | undefined) ?? [];

  return (
    <PageWrapper
      title="Measurement Operations"
      subtitle="Connector health, tenant measurement state, and operator actions."
    >
      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>Connector health</CardTitle></CardHeader>
          <CardContent>
            {connectors.length === 0
              ? <EmptyState title="No connectors registered" description="Connectors appear here after they are configured per tenant." />
              : <DataTable data={connectors} keyExtractor={r => String(r.connector_id)} columns={[
                  { key: 'id', header: 'Connector ID', render: r => <span className="font-mono text-xs">{String(r.connector_id ?? '').slice(0, 8)}…</span> },
                  { key: 'type', header: 'Type', render: r => String(r.connector_type ?? '—') },
                  { key: 'tenant', header: 'Tenant', render: r => <span className="font-mono text-xs">{String(r.tenant_id ?? '—')}</span> },
                  { key: 'status', header: 'Health', render: r => <Badge variant={statusVariant(String(r.health_status ?? 'unknown'))}>{String(r.health_status ?? 'unknown')}</Badge> },
                  { key: 'sync', header: 'Last sync', render: r => String(r.last_success_at ?? '—') },
                  { key: 'actions', header: 'Actions', render: r => (
                    <span className="flex gap-2">
                      <ConfirmButton label="Restart" onConfirm={() => restartConnector(String(r.connector_id))} />
                      <ConfirmButton label="Backfill 30d" onConfirm={() => {
                        const end = new Date().toISOString().split('T')[0];
                        const start = new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0];
                        return backfillConnector(String(r.connector_id), { start_date: start, end_date: end });
                      }} />
                    </span>
                  )},
                ]} />
            }
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Tenant measurement state</CardTitle></CardHeader>
          <CardContent>
            {tenants.length === 0
              ? <EmptyState title="No tenant data" description="Tenant measurement state appears after at least one attribution run." />
              : <DataTable data={tenants} keyExtractor={r => String(r.tenant_id)} columns={[
                  { key: 'tenant', header: 'Tenant', render: r => <span className="font-mono text-xs">{String(r.tenant_id ?? '—')}</span> },
                  { key: 'conversions', header: 'Conversions', render: r => String(r.conversion_count ?? 0) },
                  { key: 'runs', header: 'Active runs', render: r => String(r.active_run_count ?? 0) },
                  { key: 'coverage', header: 'Attribution coverage', render: r => r.attribution_coverage != null ? `${Math.round(Number(r.attribution_coverage) * 100)}%` : '—' },
                  { key: 'actions', header: 'Actions', render: r => (
                    <ConfirmButton label="Recompute all" onConfirm={() => recomputeAll(String(r.tenant_id))} />
                  )},
                ]} />
            }
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Ad-hoc conversion recompute</CardTitle></CardHeader>
          <CardContent>
            <div className="flex gap-3 items-end">
              <div className="flex-1">
                <label className="text-xs text-text-muted block mb-1">Conversion ID</label>
                <input
                  type="text"
                  placeholder="UUID"
                  value={recomputeTenantId}
                  onChange={e => setRecomputeTenantId(e.target.value)}
                  className="w-full text-sm font-mono bg-surface-secondary border border-border rounded px-2 py-1"
                />
              </div>
              <ConfirmButton
                label="Recompute"
                disabled={!recomputeTenantId.trim()}
                onConfirm={() => recomputeConversion(recomputeTenantId.trim())}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </PageWrapper>
  );
}
