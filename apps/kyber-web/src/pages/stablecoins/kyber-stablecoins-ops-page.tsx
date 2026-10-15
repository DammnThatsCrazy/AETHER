import { useState } from 'react';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable,
  EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { stablecoinsOpsApi } from '@kyber/lib/api/stablecoins-ops';
import {
  FlagGate, fmtCell, rows, useOpsData,
} from '@kyber/components/economic-ops';

function RegistryCard() {
  const status = useOpsData(() => stablecoinsOpsApi.registryStatus());
  const [seedResult, setSeedResult] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader><CardTitle>Canonical registry</CardTitle></CardHeader>
      <CardContent>
        {status.loading && <LoadingState lines={2} />}
        {status.error && <ErrorState title="Registry status unavailable" message={status.error} />}
        {status.data && (
          <div className="flex items-center gap-6 text-sm">
            <span>{status.data.asset_count} canonical assets</span>
            <span>{status.data.deployment_count} deployments</span>
            <button
              className="text-xs px-2 py-1 rounded border border-border hover:bg-surface-secondary"
              onClick={async () => {
                try {
                  const r = await stablecoinsOpsApi.seedRegistry();
                  setSeedResult(`Seeded: ${JSON.stringify(r)}`);
                } catch (e) {
                  setSeedResult(`Seed failed: ${e instanceof Error ? e.message : String(e)}`);
                }
              }}
            >
              Seed from verified x402 contracts
            </button>
          </div>
        )}
        {seedResult && <p className="text-xs text-text-muted mt-2 font-mono">{seedResult}</p>}
      </CardContent>
    </Card>
  );
}

function CheckpointsCard() {
  const checkpoints = useOpsData(() => stablecoinsOpsApi.finalityCheckpoints());

  return (
    <Card>
      <CardHeader><CardTitle>Finality checkpoints</CardTitle></CardHeader>
      <CardContent>
        {checkpoints.loading && <LoadingState lines={3} />}
        {checkpoints.error && <ErrorState title="Checkpoints unavailable" message={checkpoints.error} />}
        {checkpoints.data && (
          rows(checkpoints.data).length === 0
            ? <EmptyState title="No finality checkpoints" description="Checkpoints appear once per-chain finality tracking advances." />
            : <DataTable data={rows(checkpoints.data)} keyExtractor={r => String(r.checkpoint_id ?? r.chain_id)} columns={[
                { key: 'chain', header: 'Chain', render: r => <span className="font-mono text-xs">{fmtCell(r.chain_id)}</span> },
                { key: 'block', header: 'Confirmed block', render: r => fmtCell(r.confirmed_block_number ?? r.block_number) },
                { key: 'horizon', header: 'Horizon', render: r => fmtCell(r.confirmation_horizon) },
                { key: 'advanced', header: 'Advanced at', render: r => fmtCell(r.advanced_at) },
              ]} />
        )}
      </CardContent>
    </Card>
  );
}

function ReconciliationCard() {
  const reconciliation = useOpsData(() => stablecoinsOpsApi.reconciliation());
  const unresolved = useOpsData(() => stablecoinsOpsApi.unresolvedObservations());

  return (
    <Card>
      <CardHeader><CardTitle>Reconciliation & registry gaps</CardTitle></CardHeader>
      <CardContent>
        {(reconciliation.loading || unresolved.loading) && <LoadingState lines={3} />}
        {reconciliation.error && <ErrorState title="Reconciliation unavailable" message={reconciliation.error} />}
        {reconciliation.data && unresolved.data && (
          <div className="space-y-4">
            <div className="flex items-center gap-4 text-sm">
              <Badge variant={rows(reconciliation.data).length ? 'warning' : 'success'}>
                {rows(reconciliation.data).length} reconciliation records
              </Badge>
              <Badge variant={rows(unresolved.data).length ? 'warning' : 'success'}>
                {rows(unresolved.data).length} unresolved observations
              </Badge>
            </div>
            {rows(unresolved.data).length > 0 && (
              <DataTable data={rows(unresolved.data)} keyExtractor={r => String(r.observation_id)} columns={[
                { key: 'kind', header: 'Kind', render: r => fmtCell(r.observation_kind) },
                { key: 'chain', header: 'Chain', render: r => fmtCell(r.chain_id) },
                { key: 'token', header: 'Token', render: r => <span className="font-mono text-xs">{fmtCell(r.token_address)}</span> },
                { key: 'tx', header: 'Tx', render: r => <span className="font-mono text-xs">{String(r.transaction_hash ?? '—').slice(0, 18)}…</span> },
              ]} />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function KyberStablecoinsOpsPage() {
  return (
    <PageWrapper
      title="Stablecoin Ops"
      subtitle="Observation-only: registry curation, finality checkpoints, and reconciliation review. Aether never executes, mints, or moves funds."
    >
      <FlagGate flag="kyberStablecoinOps" domainLabel="Stablecoin Intelligence">
        <div className="space-y-4">
          <RegistryCard />
          <CheckpointsCard />
          <ReconciliationCard />
        </div>
      </FlagGate>
    </PageWrapper>
  );
}
