import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState, formatCount, useTimeContext, type TimeContext } from '@aether/ui';
import { SOURCE_CLASS_DEFAULTS, canonicalSourceClass, type SourceClass } from '@aether/shared/traffic-source';
import { PageWrapper } from '@kyber/components/layout';
import { useMeasurementOps } from '@kyber/features/measurement';
import { api } from '@kyber/lib/api';
import { useEffect, useState } from 'react';

type Row = Record<string, unknown>;

type RepairMode = 'dryRun' | 'live';

function createRepairRequestId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `repair-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

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
  if (status === 'healthy' || status === 'ok') return 'success';
  if (status === 'degraded') return 'warning';
  if (status === 'error' || status === 'failed') return 'danger';
  return 'default';
}

function isRow(value: unknown): value is Row {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function humanizeKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase());
}

function compactValue(value: unknown, ctx: TimeContext): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return formatCount(value, ctx);
  if (Array.isArray(value)) return value.map(item => compactValue(item, ctx)).join(', ') || '—';
  if (isRow(value)) {
    return Object.entries(value)
      .map(([key, nestedValue]) => `${humanizeKey(key)}: ${compactValue(nestedValue, ctx)}`)
      .join(' · ') || '—';
  }
  return String(value);
}

/**
 * Canonical customer-facing label for a source_class value from the generated
 * traffic-source registry. Legacy "direct" normalizes to direct_unknown and
 * renders "Direct / Unknown" — the operator surface never claims "Typed URL".
 */
function sourceClassRegistryLabel(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const canonical = canonicalSourceClass(String(value));
  return SOURCE_CLASS_DEFAULTS[canonical as SourceClass]?.label ?? String(value);
}

/**
 * Rewrite a source-class breakdown so its rows are labeled with canonical
 * registry labels while keeping counts/details untouched. Non-array input is
 * passed through unchanged (HealthBreakdown handles the rest defensively).
 */
function labeledSourceClassBreakdown(value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  return value.map(item => {
    if (!isRow(item)) return item;
    const classKey = ['source_class', 'name', 'class'].find(key => item[key] != null);
    if (!classKey) return item;
    const { [classKey]: rawClass, ...rest } = item;
    return { name: sourceClassRegistryLabel(rawClass), ...rest };
  });
}

function HealthBreakdown({ title, value }: { readonly title: string; readonly value: unknown }) {
  const timeCtx = useTimeContext();
  const rows = Array.isArray(value)
    ? value.map((item, index) => {
        if (!isRow(item)) return { label: String(index + 1), detail: compactValue(item, timeCtx) };
        const labelKey = ['provider', 'ai_provider', 'mediation', 'referral_mediation_type', 'version', 'classifier_version', 'name', 'type']
          .find(key => item[key] != null);
        const label = labelKey ? compactValue(item[labelKey], timeCtx) : String(index + 1);
        const detail = compactValue(Object.fromEntries(Object.entries(item).filter(([key]) => key !== labelKey)), timeCtx);
        return { label, detail };
      })
    : isRow(value)
      ? Object.entries(value).map(([label, detail]) => ({ label, detail: compactValue(detail, timeCtx) }))
      : [];

  return (
    <div>
      <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">{title}</h4>
      {rows.length === 0
        ? <p className="text-xs text-text-muted">No data</p>
        : (
          <div className="space-y-1">
            {rows.map((row, index) => (
              <div key={`${row.label}-${index}`} className="flex items-start justify-between gap-3 rounded border border-border-subtle bg-surface-raised px-2 py-1.5 text-xs">
                <span className="font-medium text-text-primary">{humanizeKey(row.label)}</span>
                <span className="text-right font-mono text-text-secondary break-all">{row.detail}</span>
              </div>
            ))}
          </div>
        )
      }
    </div>
  );
}

export interface SourceClassificationHealthCardProps {
  readonly health: Row;
  readonly loading: boolean;
  readonly error: string | null;
  readonly onRefresh: () => Promise<void>;
  readonly onReclassify: (params: {
    start_date: string;
    end_date: string;
    dry_run: boolean;
    limit: number;
    request_id: string;
  }) => Promise<unknown>;
  readonly requestIdFactory?: () => string;
}

export function SourceClassificationHealthCard({
  health,
  loading,
  error,
  onRefresh,
  onReclassify,
  requestIdFactory = createRepairRequestId,
}: SourceClassificationHealthCardProps) {
  const today = new Date();
  const thirtyDaysAgo = new Date(today.getTime() - 30 * 86400000);
  const [startDate, setStartDate] = useState(thirtyDaysAgo.toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(today.toISOString().slice(0, 10));
  const [limit, setLimit] = useState(500);
  const [result, setResult] = useState<string | null>(null);
  const [requestIds, setRequestIds] = useState<Record<RepairMode, string>>(() => ({
    dryRun: requestIdFactory(),
    live: requestIdFactory(),
  }));
  const timeCtx = useTimeContext();

  const summary = isRow(health.summary) ? health.summary : {};
  const status = String(health.status ?? summary.status ?? 'unknown');
  const validWindow = Boolean(
    startDate
    && endDate
    && startDate <= endDate
    && Number.isInteger(limit)
    && limit > 0
    && limit <= 10000
  );

  function rotateAllRequestIds() {
    setRequestIds({
      dryRun: requestIdFactory(),
      live: requestIdFactory(),
    });
    setResult(null);
  }

  async function runReclassification(dryRun: boolean) {
    const mode: RepairMode = dryRun ? 'dryRun' : 'live';
    const requestId = requestIds[mode];
    setResult(null);
    try {
      const response = await onReclassify({
        start_date: startDate,
        end_date: endDate,
        dry_run: dryRun,
        limit,
        request_id: requestId,
      });
      const responseRecord = isRow(response) ? response : {};
      setResult([
        `Status: ${String(responseRecord.status ?? (dryRun ? 'dry run queued' : 'repair queued'))}`,
        `Job: ${String(responseRecord.job_id ?? '—')}`,
        `Request: ${String(responseRecord.request_id ?? requestId)}`,
        `Replayed: ${responseRecord.replayed === true ? 'Yes' : 'No'}`,
      ].join(' · '));
      setRequestIds(current => ({ ...current, [mode]: requestIdFactory() }));
    } catch (e) {
      setResult(
        `Source ${dryRun ? 'dry run' : 'repair'} failed: ${e instanceof Error ? e.message : String(e)}`
        + ` · Request: ${requestId} (retry reuses this ID)`,
      );
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>Source classification health</CardTitle>
            <p className="text-xs text-text-muted mt-1">AI provider, product, actor, mediation, classifier-version, and historical repair diagnostics.</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={statusVariant(status)}>{status}</Badge>
            <button onClick={() => void onRefresh()} disabled={loading} className="text-xs text-accent underline disabled:opacity-50">Refresh</button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && <LoadingState lines={4} />}
        {error && <ErrorState title="Source classification health unavailable" message={error} />}
        {!loading && !error && Object.keys(health).length === 0 && (
          <EmptyState title="No classifier health data" description="Health appears after source classification has processed acquisition touchpoints." />
        )}
        {!loading && !error && Object.keys(health).length > 0 && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {Object.entries(summary).map(([key, value]) => (
                <div key={key} className="rounded border border-border-subtle bg-surface-raised p-2">
                  <div className="text-[10px] uppercase tracking-wide text-text-muted">{humanizeKey(key)}</div>
                  <div className="mt-1 font-mono text-sm text-text-primary break-all">{compactValue(value, timeCtx)}</div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <HealthBreakdown title="Providers" value={health.providers} />
              <HealthBreakdown title="Mediation" value={health.mediation} />
              <HealthBreakdown title="Versions" value={health.versions} />
            </div>
          </>
        )}

        <div className="border-t border-border pt-4 space-y-3">
          <p className="text-xs text-text-muted">
            Historical repair is audited and non-destructive. It reclassifies durable touchpoints and lets the existing journey, attribution, and restatement pipeline recompute downstream truth.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label htmlFor="source-repair-start" className="text-xs text-text-muted block mb-1">Start date</label>
              <input id="source-repair-start" type="date" value={startDate} onChange={event => { setStartDate(event.target.value); rotateAllRequestIds(); }} className="w-full text-sm bg-surface-secondary border border-border rounded px-2 py-1" />
            </div>
            <div>
              <label htmlFor="source-repair-end" className="text-xs text-text-muted block mb-1">End date</label>
              <input id="source-repair-end" type="date" value={endDate} onChange={event => { setEndDate(event.target.value); rotateAllRequestIds(); }} className="w-full text-sm bg-surface-secondary border border-border rounded px-2 py-1" />
            </div>
            <div>
              <label htmlFor="source-repair-limit" className="text-xs text-text-muted block mb-1">Touchpoint limit</label>
              <input id="source-repair-limit" type="number" min={1} max={10000} value={limit} onChange={event => { setLimit(Number(event.target.value)); rotateAllRequestIds(); }} className="w-full text-sm bg-surface-secondary border border-border rounded px-2 py-1" />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <ConfirmButton label="Dry-run reclassification" disabled={!validWindow} onConfirm={() => runReclassification(true)} />
            <ConfirmButton label="Run source repair" disabled={!validWindow} onConfirm={() => runReclassification(false)} />
          </div>
          {result && <p className="text-xs font-mono text-text-secondary break-all" role="status">{result}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function CommsFleetHealthCard() {
  const [tenants, setTenants] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timeCtx = useTimeContext();

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
                { key: 'facts', header: 'Comm facts', render: r => formatCount(Number(r.communication_facts ?? 0), timeCtx) },
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
  const {
    overview,
    loading,
    error,
    restartConnector,
    backfillConnector,
    recomputeConversion,
    recomputeAll,
    sourceClassificationHealth,
    sourceClassificationLoading,
    sourceClassificationError,
    refreshSourceClassificationHealth,
    reclassifySources,
  } = useMeasurementOps();
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
        <SourceClassificationHealthCard
          health={sourceClassificationHealth}
          loading={sourceClassificationLoading}
          error={sourceClassificationError}
          onRefresh={refreshSourceClassificationHealth}
          onReclassify={reclassifySources}
        />

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
