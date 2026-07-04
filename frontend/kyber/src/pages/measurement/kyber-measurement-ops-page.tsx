import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useMeasurementOps } from '@kyber/features/measurement';
import { api } from '@kyber/lib/api';
import { useEffect, useState } from 'react';

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

function CommsFleetHealthCard() {
  const [tenants, setTenants] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (api.measurement.commsFleetHealth() as Promise<Row>)
      .then(d => { if (active) setTenants(((d as Row).tenants as Row[]) ?? []); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const pct = (v: unknown) => (v == null ? '—' : `${Math.round(Number(v) * 100)}%`);
  const resolutionVariant = (v: unknown): 'success' | 'warning' | 'danger' | 'default' => {
    if (v == null) return 'default';
    const n = Number(v);
    if (n >= 0.9) return 'success';
    if (n >= 0.6) return 'warning';
    return 'danger';
  };

  return (
    <Card>
      <CardHeader><CardTitle>Communications pipeline health</CardTitle></CardHeader>
      <CardContent>
        {loading && <LoadingState lines={3} />}
        {error && <ErrorState title="Comms health unavailable" message={error} />}
        {!loading && !error && (
          tenants.length === 0
            ? <EmptyState title="No communication facts" description="Per-tenant projection and resolution health appears once communication events are ingested." />
            : <DataTable data={tenants} keyExtractor={r => String(r.tenant_id)} columns={[
                { key: 'tenant', header: 'Tenant', render: r => <span className="font-mono text-xs">{String(r.tenant_id ?? '—')}</span> },
                { key: 'facts', header: 'Comm facts', render: r => Number(r.communication_facts ?? 0).toLocaleString() },
                { key: 'resolution', header: 'Campaign resolution', render: r => (
                  <Badge variant={resolutionVariant(r.campaign_resolution_rate)}>{pct(r.campaign_resolution_rate)}</Badge>
                )},
                { key: 'machine', header: 'Machine events', render: r => pct(r.machine_event_rate) },
                { key: 'last', header: 'Last event', render: r => String(r.last_event_at ?? '—') },
              ]} />
        )}
        <CommsOperatorActions />
      </CardContent>
    </Card>
  );
}

function CommsOperatorActions() {
  const [tenantId, setTenantId] = useState('');
  const [entityId, setEntityId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  const [result, setResult] = useState<string | null>(null);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    try {
      const r = await fn();
      setResult(`${label}: ${JSON.stringify((r as Row) ?? {})}`);
    } catch (e) {
      setResult(`${label} failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="mt-4 pt-4 border-t border-border space-y-3">
      <p className="text-xs text-text-muted">
        Operator actions — audited. Rebuilds are idempotent recomputations from durable facts;
        DSR erasure deletes an entity's communication facts and derived state (suppressions are retained).
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-text-muted block mb-1" htmlFor="comms-tenant">Tenant ID</label>
          <input id="comms-tenant" type="text" value={tenantId} onChange={e => setTenantId(e.target.value)}
                 className="w-full text-sm font-mono bg-surface-secondary border border-border rounded px-2 py-1" />
        </div>
        <div>
          <label className="text-xs text-text-muted block mb-1" htmlFor="comms-entity">Entity ID</label>
          <input id="comms-entity" type="text" value={entityId} onChange={e => setEntityId(e.target.value)}
                 className="w-full text-sm font-mono bg-surface-secondary border border-border rounded px-2 py-1" />
        </div>
        <div>
          <label className="text-xs text-text-muted block mb-1" htmlFor="comms-campaign">Campaign ID</label>
          <input id="comms-campaign" type="text" value={campaignId} onChange={e => setCampaignId(e.target.value)}
                 className="w-full text-sm font-mono bg-surface-secondary border border-border rounded px-2 py-1" />
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <ConfirmButton
          label="Rebuild entity state + journey"
          disabled={!tenantId.trim() || !entityId.trim()}
          onConfirm={() => run('Rebuild', () => api.measurement.commsRebuildState({ tenant_id: tenantId.trim(), entity_id: entityId.trim() }))}
        />
        <ConfirmButton
          label="Reproject campaign graph"
          disabled={!tenantId.trim() || !campaignId.trim()}
          onConfirm={() => run('Reproject', () => api.measurement.commsReprojectGraph({ tenant_id: tenantId.trim(), campaign_id: campaignId.trim() }))}
        />
        <ConfirmButton
          label="DSR erase entity comms"
          disabled={!tenantId.trim() || !entityId.trim()}
          onConfirm={() => run('DSR erase', () => api.measurement.commsDsrErase({ tenant_id: tenantId.trim(), entity_id: entityId.trim(), confirm: true }))}
        />
      </div>
      {result && <p className="text-xs font-mono text-text-secondary break-all" role="status">{result}</p>}
    </div>
  );
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
                        const end = new Date().toISOString().split('T')[0] ?? '';
                        const start = new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0] ?? '';
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

        <CommsFleetHealthCard />

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
