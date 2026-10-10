import { useState } from 'react';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable,
  EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { interopOpsApi } from '@kyber/lib/api/interop-ops';
import {
  FlagGate, fmtCell, implementationStatusBadge, rows, useOpsData,
} from '@kyber/components/economic-ops';

function ProvidersCard() {
  const providers = useOpsData(() => interopOpsApi.providersHealth());
  const [scanResult, setScanResult] = useState<string | null>(null);

  const runScan = async (providerId: string) => {
    try {
      const r = await interopOpsApi.runScan(providerId);
      setScanResult(`${providerId}: ${JSON.stringify(r)}`);
    } catch (e) {
      setScanResult(`${providerId} scan refused: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <Card>
      <CardHeader><CardTitle>Provider adapters</CardTitle></CardHeader>
      <CardContent>
        {providers.loading && <LoadingState lines={3} />}
        {providers.error && <ErrorState title="Provider health unavailable" message={providers.error} />}
        {providers.data && (
          rows(providers.data).length === 0
            ? <EmptyState title="No provider adapters registered" />
            : <DataTable data={rows(providers.data)} keyExtractor={r => String(r.provider_id)} columns={[
                { key: 'id', header: 'Provider', render: r => <span className="font-mono text-xs">{fmtCell(r.provider_id)}</span> },
                { key: 'kind', header: 'Kind', render: r => fmtCell(r.provider_kind) },
                { key: 'impl', header: 'Implementation status', render: r => implementationStatusBadge(r.implementation_status) },
                { key: 'checkpoints', header: 'Checkpoints', render: r => String(Array.isArray(r.checkpoints) ? r.checkpoints.length : 0) },
                {
                  key: 'actions', header: '', render: r => (
                    <button
                      className="text-xs px-2 py-1 rounded border border-border hover:bg-surface-secondary"
                      onClick={() => runScan(String(r.provider_id))}
                    >
                      Run governed scan
                    </button>
                  ),
                },
              ]} />
        )}
        {scanResult && <p className="text-xs text-text-muted mt-2 font-mono break-all">{scanResult}</p>}
        <p className="text-xs text-text-muted mt-3">
          Scans are audited read-only evidence collection. Scaffolded providers honestly refuse;
          LayerZero V2 requires its dedicated flag and RPC credentials.
        </p>
      </CardContent>
    </Card>
  );
}

function CorrelationCard() {
  const health = useOpsData(() => interopOpsApi.correlationHealth());

  return (
    <Card>
      <CardHeader><CardTitle>Correlation health</CardTitle></CardHeader>
      <CardContent>
        {health.loading && <LoadingState lines={2} />}
        {health.error && <ErrorState title="Correlation health unavailable" message={health.error} />}
        {health.data && (
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <span>{health.data.message_count} messages</span>
            <Badge variant={health.data.out_of_order_discoveries ? 'warning' : 'success'}>
              {health.data.out_of_order_discoveries} out-of-order discoveries
            </Badge>
            <Badge variant={health.data.uncorrelated_messages ? 'warning' : 'success'}>
              {health.data.uncorrelated_messages} uncorrelated
            </Badge>
            <span className="text-xs text-text-muted font-mono">
              {Object.entries(health.data.by_status).map(([s, n]) => `${s}:${n}`).join('  ')}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PolicyDriftCard() {
  const drift = useOpsData(() => interopOpsApi.policyDrift());

  return (
    <Card>
      <CardHeader><CardTitle>Security policy drift</CardTitle></CardHeader>
      <CardContent>
        {drift.loading && <LoadingState lines={2} />}
        {drift.error && <ErrorState title="Policy drift unavailable" message={drift.error} />}
        {drift.data && (
          rows(drift.data).length === 0
            ? <EmptyState title="No policy drift" description="No path has changed its verification configuration across snapshots." icon="✓" />
            : <DataTable data={rows(drift.data)} keyExtractor={r => String(r.path_id)} columns={[
                { key: 'path', header: 'Path', render: r => <span className="font-mono text-xs">{fmtCell(r.path_id)}</span> },
                { key: 'count', header: 'Distinct policies', render: r => <Badge variant="warning">{fmtCell(r.distinct_policies)}</Badge> },
                { key: 'hash', header: 'Latest hash', render: r => <span className="font-mono text-xs">{String(r.latest_hash ?? '—').slice(0, 18)}…</span> },
              ]} />
        )}
      </CardContent>
    </Card>
  );
}

export function KyberInteropOpsPage() {
  return (
    <PageWrapper
      title="Interoperability Ops"
      subtitle="Observation-only: provider adapter health, checkpoint lag, correlation quality, and security-policy drift. Aether never relays, retries, or recovers messages."
    >
      <FlagGate flag="kyberInteropOps" domainLabel="Interoperability Intelligence">
        <div className="space-y-4">
          <ProvidersCard />
          <CorrelationCard />
          <PolicyDriftCard />
        </div>
      </FlagGate>
    </PageWrapper>
  );
}
