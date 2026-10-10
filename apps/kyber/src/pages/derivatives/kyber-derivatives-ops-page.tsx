import { useState } from 'react';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable,
  EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { derivativesOpsApi } from '@kyber/lib/api/derivatives-ops';
import {
  FlagGate, fmtCell, implementationStatusBadge, rows, useOpsData,
} from '@kyber/components/economic-ops';

function FleetCard() {
  const fleet = useOpsData(() => derivativesOpsApi.fleet());
  const [conformanceResult, setConformanceResult] = useState<string | null>(null);

  const runConformance = async (adapterId: string) => {
    try {
      const r = await derivativesOpsApi.runConformance(adapterId);
      setConformanceResult(`${adapterId}: ${JSON.stringify(r)}`);
    } catch (e) {
      setConformanceResult(`${adapterId} conformance failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <Card>
      <CardHeader><CardTitle>Adapter fleet</CardTitle></CardHeader>
      <CardContent>
        {fleet.loading && <LoadingState lines={3} />}
        {fleet.error && <ErrorState title="Fleet unavailable" message={fleet.error} />}
        {fleet.data && (
          fleet.data.items.length === 0
            ? <EmptyState title="No adapters registered" />
            : <DataTable data={fleet.data.items} keyExtractor={r => String((r as Record<string, unknown>).adapter_id ?? (r as Record<string, unknown>).venue_id)} columns={[
                { key: 'id', header: 'Adapter', render: r => <span className="font-mono text-xs">{fmtCell((r as Record<string, unknown>).adapter_id)}</span> },
                { key: 'venue', header: 'Venue', render: r => fmtCell((r as Record<string, unknown>).venue_id) },
                { key: 'impl', header: 'Implementation status', render: r => implementationStatusBadge(r.implementation_status) },
                { key: 'authority', header: 'Credential authority', render: r => <Badge variant="success">{fmtCell((r as Record<string, unknown>).authority_type, 'read_only')}</Badge> },
                {
                  key: 'actions', header: '', render: r => (
                    <button
                      className="text-xs px-2 py-1 rounded border border-border hover:bg-surface-secondary"
                      onClick={() => runConformance(String((r as Record<string, unknown>).adapter_id))}
                    >
                      Run conformance
                    </button>
                  ),
                },
              ]} />
        )}
        {conformanceResult && <p className="text-xs text-text-muted mt-2 font-mono break-all">{conformanceResult}</p>}
      </CardContent>
    </Card>
  );
}

function OpsListCard({ title, empty, fetcher, columns }: {
  readonly title: string;
  readonly empty: string;
  readonly fetcher: () => Promise<unknown>;
  readonly columns: readonly { key: string; header: string; render: (r: Record<string, unknown>) => React.ReactNode }[];
}) {
  const state = useOpsData(fetcher);
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {state.loading && <LoadingState lines={3} />}
        {state.error && <ErrorState title={`${title} unavailable`} message={state.error} />}
        {state.data != null && (
          rows(state.data).length === 0
            ? <EmptyState title={empty} icon="✓" />
            : <DataTable data={rows(state.data)} keyExtractor={r => JSON.stringify(r).slice(0, 80)} columns={columns} />
        )}
      </CardContent>
    </Card>
  );
}

export function KyberDerivativesOpsPage() {
  return (
    <PageWrapper
      title="Derivatives Ops"
      subtitle="Observation-only: adapter fleet health, stream gaps, and reconciliation variances. Aether never places, modifies, or cancels orders."
    >
      <FlagGate flag="kyberDerivativesOps" domainLabel="Derivatives Intelligence">
        <div className="space-y-4">
          <FleetCard />
          <OpsListCard
            title="Connector checkpoints"
            empty="No checkpoints recorded"
            fetcher={() => derivativesOpsApi.checkpoints()}
            columns={[
              { key: 'connector', header: 'Connector', render: r => <span className="font-mono text-xs">{fmtCell(r.connector_id)}</span> },
              { key: 'value', header: 'Checkpoint', render: r => fmtCell(r.checkpoint_value) },
              { key: 'advanced', header: 'Advanced at', render: r => fmtCell(r.advanced_at) },
            ]}
          />
          <OpsListCard
            title="Stream gaps"
            empty="No open stream gaps"
            fetcher={() => derivativesOpsApi.streamGaps()}
            columns={[
              { key: 'market', header: 'Market', render: r => <span className="font-mono text-xs">{fmtCell(r.canonical_market_id)}</span> },
              { key: 'expected', header: 'Expected seq', render: r => fmtCell(r.expected_sequence) },
              { key: 'received', header: 'Received seq', render: r => fmtCell(r.received_sequence) },
              { key: 'status', header: 'Status', render: r => <Badge variant={r.status === 'open' ? 'danger' : 'success'}>{fmtCell(r.status)}</Badge> },
              { key: 'detected', header: 'Detected', render: r => fmtCell(r.detected_at) },
            ]}
          />
          <OpsListCard
            title="Reconciliation variances"
            empty="No variances — venue and projected state agree"
            fetcher={() => derivativesOpsApi.variances()}
            columns={[
              { key: 'type', header: 'Variance', render: r => fmtCell(r.variance_type) },
              { key: 'expected', header: 'Expected', render: r => fmtCell(r.expected_value) },
              { key: 'observed', header: 'Observed', render: r => fmtCell(r.observed_value) },
              { key: 'severity', header: 'Severity', render: r => <Badge variant={r.severity === 'high' || r.severity === 'critical' ? 'danger' : 'warning'}>{fmtCell(r.severity)}</Badge> },
              { key: 'status', header: 'Status', render: r => fmtCell(r.status) },
            ]}
          />
        </div>
      </FlagGate>
    </PageWrapper>
  );
}
