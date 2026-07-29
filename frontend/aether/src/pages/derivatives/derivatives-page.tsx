import { useNavigate } from 'react-router-dom';
import {
  Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState,
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '@aether/ui';
import {
  useDerivativesAccounts, useDerivativesPositions, useDerivativesPnl,
  useDerivativesVariances, useDerivativesVenues,
} from '@aether-app/features/derivatives';
import {
  DomainQueryState, EvidenceBoundary, NotEnabledOrError, Stat, asRecord, asList,
  fmt, queryCount,
} from '@aether-app/components/domain-intelligence';

export function DerivativesPage() {
  const navigate = useNavigate();
  const venues = useDerivativesVenues();
  const accounts = useDerivativesAccounts();
  const positions = useDerivativesPositions();
  const pnl = useDerivativesPnl();
  const variances = useDerivativesVariances();

  if (accounts.isLoading && !accounts.data) return <LoadingState lines={6} className="p-8" />;
  if (accounts.error) {
    return (
      <div className="p-8">
        <NotEnabledOrError error={accounts.error} domainLabel="Derivatives Intelligence" onRetry={accounts.refetch} />
      </div>
    );
  }

  const venueRows = asList(asRecord(venues.data).items).map(asRecord);
  const accountRows = asList(asRecord(accounts.data).items).map(asRecord);
  const positionRows = asList(asRecord(positions.data).items).map(asRecord);
  const pnlRows = asList(asRecord(pnl.data).items).map(asRecord);
  const varianceRows = asList(asRecord(variances.data).items).map(asRecord);
  const openPositions = positionRows.filter(p => p.status === 'open');
  const unresolvedVariances = varianceRows.filter(v => v.status === 'variance_detected');

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Derivatives Intelligence</h1>
        <p className="text-sm text-text-secondary mt-1">
          Observed state of read-only linked trading accounts: positions, P&amp;L snapshots,
          and reconciliation health. Aether never places, modifies, or recommends orders.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Venues" value={queryCount(venues.data, venues.isLoading, venues.error, venueRows.length)} />
        <Stat label="Linked accounts" value={accountRows.length} sub="read-only credentials" />
        <Stat
          label="Open positions"
          value={queryCount(positions.data, positions.isLoading, positions.error, openPositions.length)}
        />
        <Stat
          label="Unresolved variances"
          value={queryCount(variances.data, variances.isLoading, variances.error, unresolvedVariances.length)}
          sub={variances.error ? 'reconciliation read failed' : unresolvedVariances.length ? 'needs review' : 'none in the returned variances'}
        />
      </div>

      <Tabs defaultValue="accounts">
        <TabsList>
          <TabsTrigger value="accounts">Accounts</TabsTrigger>
          <TabsTrigger value="positions">Positions</TabsTrigger>
          <TabsTrigger value="pnl">P&amp;L snapshots</TabsTrigger>
          <TabsTrigger value="reconciliation">Reconciliation</TabsTrigger>
        </TabsList>

        <TabsContent value="accounts">
          <Card>
            <CardHeader><CardTitle>Linked trading accounts</CardTitle></CardHeader>
            <CardContent>
              {accountRows.length === 0 ? (
                <EmptyState title="No linked accounts" description="Link a venue account with read-only credentials to begin observing." />
              ) : (
                <DataTable
                  columns={[
                    { key: 'id', header: 'Account', render: r => <span className="font-mono">{fmt(r.trading_account_id)}</span> },
                    { key: 'venue', header: 'Venue', render: r => fmt(r.venue_id) },
                    { key: 'owner', header: 'Owner entity', render: r => <span className="font-mono">{fmt(r.owner_entity_id)}</span> },
                    { key: 'status', header: 'Status', render: r => <Badge variant="default">{fmt(r.status, 'linked')}</Badge> },
                  ]}
                  data={accountRows}
                  keyExtractor={r => String(r.trading_account_id)}
                  onRowClick={r => navigate(`/derivatives/accounts/${String(r.trading_account_id)}`)}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="positions">
          <Card>
            <CardHeader><CardTitle>Observed positions</CardTitle></CardHeader>
            <CardContent>
              <EvidenceBoundary>
                Source: linked venue observations. Size, entry price, and P&amp;L retain
                the venue-reported market units; Aether performs no currency conversion.
              </EvidenceBoundary>
              {DomainQueryState({
                isLoading: positions.isLoading,
                hasData: positions.data !== null,
                error: positions.error,
                domainLabel: 'Derivatives positions',
                onRetry: positions.refetch,
              }) ?? (positionRows.length === 0 ? (
                <EmptyState title="No positions observed" />
              ) : (
                <DataTable
                  columns={[
                    { key: 'market', header: 'Market', render: r => <span className="font-mono">{fmt(r.canonical_market_id)}</span> },
                    { key: 'account', header: 'Account', render: r => <span className="font-mono">{fmt(r.trading_account_id)}</span> },
                    { key: 'side', header: 'Side', render: r => fmt(r.side) },
                    { key: 'size', header: 'Size', render: r => fmt(r.size) },
                    { key: 'entry', header: 'Entry', render: r => fmt(r.entry_price) },
                    { key: 'upnl', header: 'Unrealized P&L', render: r => fmt(r.unrealized_pnl) },
                    {
                      key: 'status', header: 'Status',
                      render: r => <Badge variant={r.status === 'open' ? 'success' : 'default'}>{fmt(r.status)}</Badge>,
                    },
                  ]}
                  data={positionRows}
                  keyExtractor={r => String(r.position_id)}
                />
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="pnl">
          <Card>
            <CardHeader><CardTitle>P&L / exposure snapshots</CardTitle></CardHeader>
            <CardContent>
              <EvidenceBoundary>
                Source: backend snapshots from read-only linked venues. Values retain
                venue-reported units and are evidence as of the displayed timestamp.
              </EvidenceBoundary>
              {DomainQueryState({
                isLoading: pnl.isLoading,
                hasData: pnl.data !== null,
                error: pnl.error,
                domainLabel: 'Derivatives P&L',
                onRetry: pnl.refetch,
              }) ?? (pnlRows.length === 0 ? (
                <EmptyState title="No P&L snapshots" description="Snapshots materialize when the P&L flag is enabled." />
              ) : (
                <DataTable
                  columns={[
                    { key: 'account', header: 'Account', render: r => <span className="font-mono">{fmt(r.trading_account_id)}</span> },
                    { key: 'market', header: 'Market', render: r => fmt(r.canonical_market_id) },
                    { key: 'realized', header: 'Realized', render: r => fmt(r.realized_pnl) },
                    { key: 'unrealized', header: 'Unrealized', render: r => fmt(r.unrealized_pnl) },
                    { key: 'gross', header: 'Gross exposure', render: r => fmt(r.gross_exposure) },
                    { key: 'asof', header: 'As of', render: r => fmt(r.as_of) },
                  ]}
                  data={pnlRows}
                  keyExtractor={r => String(r.pnl_snapshot_id)}
                />
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reconciliation">
          <Card>
            <CardHeader><CardTitle>Reconciliation variances</CardTitle></CardHeader>
            <CardContent>
              <EvidenceBoundary>
                Postcondition: “no variances” means none were returned for this reconciliation
                read. It does not prove the account is globally reconciled or ready for execution.
              </EvidenceBoundary>
              {DomainQueryState({
                isLoading: variances.isLoading,
                hasData: variances.data !== null,
                error: variances.error,
                domainLabel: 'Derivatives reconciliation',
                onRetry: variances.refetch,
              }) ?? (varianceRows.length === 0 ? (
                <EmptyState title="No variances returned" description="No variance was returned for this observed reconciliation read." icon="✓" />
              ) : (
                <DataTable
                  columns={[
                    { key: 'type', header: 'Variance', render: r => fmt(r.variance_type) },
                    { key: 'expected', header: 'Expected', render: r => fmt(r.expected_value) },
                    { key: 'observed', header: 'Observed', render: r => fmt(r.observed_value) },
                    {
                      key: 'severity', header: 'Severity',
                      render: r => <Badge variant={r.severity === 'high' || r.severity === 'critical' ? 'danger' : 'warning'}>{fmt(r.severity)}</Badge>,
                    },
                    { key: 'status', header: 'Status', render: r => fmt(r.status) },
                  ]}
                  data={varianceRows}
                  keyExtractor={r => String(r.reconciliation_variance_id)}
                />
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
