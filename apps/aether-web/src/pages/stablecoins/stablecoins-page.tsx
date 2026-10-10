import { useNavigate } from 'react-router-dom';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState,
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '@aether/ui';
import {
  useStablecoinAssets, useStablecoinFlows, useStablecoinValuations,
} from '@aether-app/features/stablecoins';
import {
  DomainQueryState, EvidenceBoundary, NotEnabledOrError, Stat, asRecord, asList,
  fmt, pegStatusVariant, queryCount,
} from '@aether-app/components/domain-intelligence';

export function StablecoinsPage() {
  const navigate = useNavigate();
  const assets = useStablecoinAssets();
  const valuations = useStablecoinValuations();
  const flows = useStablecoinFlows();

  if (assets.isLoading && !assets.data) return <LoadingState lines={6} className="p-8" />;
  if (assets.error) {
    return (
      <div className="p-8">
        <NotEnabledOrError error={assets.error} domainLabel="Stablecoin Intelligence" onRetry={assets.refetch} />
      </div>
    );
  }

  const assetRows = asList(asRecord(assets.data).items).map(asRecord);
  const valuationRows = asList(asRecord(valuations.data).items).map(asRecord);
  const flowRows = asList(asRecord(flows.data).items).map(asRecord);
  const depegged = valuationRows.filter(v => v.peg_status === 'depegged');

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Stablecoin Intelligence</h1>
        <p className="text-sm text-text-secondary mt-1">
          Observation-only view of tracked stablecoin assets, peg valuations, and flow aggregates.
          Aether never executes, mints, or moves funds.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Tracked assets" value={assetRows.length} />
        <Stat
          label="Valuation snapshots"
          value={queryCount(valuations.data, valuations.isLoading, valuations.error, valuationRows.length)}
        />
        <Stat
          label="Depegged now"
          value={queryCount(valuations.data, valuations.isLoading, valuations.error, depegged.length)}
          sub={valuations.error ? 'valuation read failed' : depegged.length ? 'observed snapshots need review' : 'none in the returned snapshots'}
        />
        <Stat
          label="Flow aggregates"
          value={queryCount(flows.data, flows.isLoading, flows.error, flowRows.length)}
        />
      </div>

      <Tabs defaultValue="assets">
        <TabsList>
          <TabsTrigger value="assets">Assets</TabsTrigger>
          <TabsTrigger value="valuations">Peg valuations</TabsTrigger>
          <TabsTrigger value="flows">Flows</TabsTrigger>
        </TabsList>

        <TabsContent value="assets">
          <Card>
            <CardHeader><CardTitle>Canonical assets</CardTitle></CardHeader>
            <CardContent>
              {assetRows.length === 0 ? (
                <EmptyState title="No stablecoin assets registered" description="Assets appear here once the registry is seeded." />
              ) : (
                <DataTable
                  columns={[
                    { key: 'id', header: 'Asset', render: r => <span className="font-mono">{fmt(r.canonical_asset_id)}</span> },
                    { key: 'symbol', header: 'Symbol', render: r => fmt(r.symbol) },
                    { key: 'peg', header: 'Peg', render: r => fmt(r.peg_currency, 'USD') },
                    { key: 'issuer', header: 'Issuer', render: r => fmt(r.issuer_name) },
                  ]}
                  data={assetRows}
                  keyExtractor={r => String(r.canonical_asset_id ?? r.symbol)}
                  onRowClick={r => navigate(`/stablecoins/${String(r.canonical_asset_id)}`)}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="valuations">
          <Card>
            <CardHeader><CardTitle>Peg valuation snapshots</CardTitle></CardHeader>
            <CardContent>
              <EvidenceBoundary>
                Source: backend valuation observations. Price is provider-declared USD;
                deviation is basis points. A snapshot is evidence at its observed time,
                not a current-price guarantee.
              </EvidenceBoundary>
              {DomainQueryState({
                isLoading: valuations.isLoading,
                hasData: valuations.data !== null,
                error: valuations.error,
                domainLabel: 'Stablecoin valuations',
                onRetry: valuations.refetch,
              }) ?? (valuationRows.length === 0 ? (
                <EmptyState title="No valuation snapshots" description="Snapshots appear once valuation sources are configured." />
              ) : (
                <DataTable
                  columns={[
                    { key: 'deployment', header: 'Deployment', render: r => <span className="font-mono">{fmt(r.deployment_id)}</span> },
                    { key: 'price', header: 'Price (USD)', render: r => fmt(r.price_usd) },
                    { key: 'dev', header: 'Deviation (bps)', render: r => fmt(r.peg_deviation_bps) },
                    {
                      key: 'status', header: 'Peg status',
                      render: r => <Badge variant={pegStatusVariant(String(r.peg_status))}>{fmt(r.peg_status)}</Badge>,
                    },
                    { key: 'at', header: 'Observed', render: r => fmt(r.observed_at) },
                  ]}
                  data={valuationRows}
                  keyExtractor={r => String(r.valuation_id)}
                />
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="flows">
          <Card>
            <CardHeader><CardTitle>Flow aggregates</CardTitle></CardHeader>
            <CardContent>
              <EvidenceBoundary>
                Source: materialized observed transfers. Volumes remain in the asset unit
                returned by the backend; Aether does not convert or sum unlike assets.
              </EvidenceBoundary>
              {DomainQueryState({
                isLoading: flows.isLoading,
                hasData: flows.data !== null,
                error: flows.error,
                domainLabel: 'Stablecoin flows',
                onRetry: flows.refetch,
              }) ?? (flowRows.length === 0 ? (
                <EmptyState title="No flow aggregates materialized" description="Windowed flow metrics appear after observation ingestion." />
              ) : (
                <DataTable
                  columns={[
                    { key: 'asset', header: 'Asset', render: r => <span className="font-mono">{fmt(r.canonical_asset_id)}</span> },
                    { key: 'window', header: 'Window', render: r => `${fmt(r.window_start)} → ${fmt(r.window_end)}` },
                    { key: 'gross', header: 'Gross volume', render: r => fmt(r.gross_transfer_volume) },
                    { key: 'count', header: 'Transfers', render: r => fmt(r.transfer_count) },
                    { key: 'senders', header: 'Unique senders', render: r => fmt(r.unique_senders) },
                  ]}
                  data={flowRows}
                  keyExtractor={r => String(r.flow_aggregate_id)}
                />
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
