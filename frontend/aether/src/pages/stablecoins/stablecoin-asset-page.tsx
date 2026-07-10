import { useParams, Link } from 'react-router-dom';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState } from '@aether/ui';
import {
  useStablecoinDeployments, useStablecoinObservations,
} from '@aether-app/features/stablecoins';
import {
  NotEnabledOrError, Stat, asRecord, asList, fmt,
} from '@aether-app/components/domain-intelligence';

export function StablecoinAssetPage() {
  const { assetId = '' } = useParams();
  const deployments = useStablecoinDeployments(assetId);
  const observations = useStablecoinObservations({ canonical_asset_id: assetId });

  if (deployments.isLoading && !deployments.data) return <LoadingState lines={6} className="p-8" />;
  if (deployments.error) {
    return (
      <div className="p-8">
        <NotEnabledOrError error={deployments.error} domainLabel="Stablecoin Intelligence" onRetry={deployments.refetch} />
      </div>
    );
  }

  const deploymentRows = asList(asRecord(deployments.data).items).map(asRecord);
  const observationRows = asList(asRecord(observations.data).items).map(asRecord);
  const finalized = observationRows.filter(o => o.finality_status === 'finalized');

  return (
    <div className="p-6 space-y-6">
      <div>
        <Link to="/stablecoins" className="text-xs text-accent hover:underline">← All stablecoins</Link>
        <h1 className="text-xl font-semibold text-text-primary mt-1 font-mono">{assetId}</h1>
        <p className="text-sm text-text-secondary mt-1">
          Chain deployments and observed activity for this canonical asset.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Stat label="Deployments" value={deploymentRows.length} />
        <Stat label="Observations" value={observationRows.length} />
        <Stat label="Finalized" value={finalized.length} />
      </div>

      <Card>
        <CardHeader><CardTitle>Deployments</CardTitle></CardHeader>
        <CardContent>
          {deploymentRows.length === 0 ? (
            <EmptyState title="No deployments" description="Per-chain contract deployments appear once registered." />
          ) : (
            <DataTable
              columns={[
                { key: 'id', header: 'Deployment', render: r => <span className="font-mono">{fmt(r.deployment_id)}</span> },
                { key: 'chain', header: 'Chain', render: r => fmt(r.chain_id) },
                { key: 'addr', header: 'Contract', render: r => <span className="font-mono">{fmt(r.contract_address)}</span> },
                { key: 'decimals', header: 'Decimals', render: r => fmt(r.decimals) },
              ]}
              data={deploymentRows}
              keyExtractor={r => String(r.deployment_id)}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Recent observations</CardTitle></CardHeader>
        <CardContent>
          {observationRows.length === 0 ? (
            <EmptyState title="No observations" description="On-chain observations appear after ingestion is enabled." />
          ) : (
            <DataTable
              columns={[
                { key: 'kind', header: 'Kind', render: r => <Badge variant="default">{fmt(r.observation_kind)}</Badge> },
                { key: 'chain', header: 'Chain', render: r => fmt(r.chain_id) },
                { key: 'amount', header: 'Amount', render: r => fmt(r.amount_decimal ?? r.amount_atomic) },
                { key: 'tx', header: 'Tx', render: r => <span className="font-mono">{String(r.transaction_hash ?? '—').slice(0, 18)}…</span> },
                { key: 'finality', header: 'Finality', render: r => fmt(r.finality_status) },
                { key: 'at', header: 'Observed', render: r => fmt(r.observed_at) },
              ]}
              data={observationRows}
              keyExtractor={r => String(r.observation_id)}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
