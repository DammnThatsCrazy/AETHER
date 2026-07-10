import { useParams, Link } from 'react-router-dom';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState } from '@aether/ui';
import {
  useDerivativesFills, useDerivativesOrders, useDerivativesPositions,
} from '@aether-app/features/derivatives';
import {
  NotEnabledOrError, Stat, asRecord, asList, fmt,
} from '@aether-app/components/domain-intelligence';

export function DerivativesAccountPage() {
  const { accountId = '' } = useParams();
  const orders = useDerivativesOrders(accountId);
  const fills = useDerivativesFills(accountId);
  const positions = useDerivativesPositions({ trading_account_id: accountId });

  if (orders.isLoading && !orders.data) return <LoadingState lines={6} className="p-8" />;
  if (orders.error) {
    return (
      <div className="p-8">
        <NotEnabledOrError error={orders.error} domainLabel="Derivatives Intelligence" onRetry={orders.refetch} />
      </div>
    );
  }

  const orderRows = asList(asRecord(orders.data).items).map(asRecord);
  const fillRows = asList(asRecord(fills.data).items).map(asRecord);
  const positionRows = asList(asRecord(positions.data).items).map(asRecord);

  return (
    <div className="p-6 space-y-6">
      <div>
        <Link to="/derivatives" className="text-xs text-accent hover:underline">← All derivatives</Link>
        <h1 className="text-xl font-semibold text-text-primary mt-1 font-mono">{accountId}</h1>
        <p className="text-sm text-text-secondary mt-1">
          Observed orders, fills, and positions for this read-only linked account.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Stat label="Orders" value={orderRows.length} />
        <Stat label="Fills" value={fillRows.length} />
        <Stat label="Positions" value={positionRows.length} />
      </div>

      <Card>
        <CardHeader><CardTitle>Orders</CardTitle></CardHeader>
        <CardContent>
          {orderRows.length === 0 ? (
            <EmptyState title="No orders observed" />
          ) : (
            <DataTable
              columns={[
                { key: 'id', header: 'Order', render: r => <span className="font-mono">{String(r.order_id ?? '').slice(0, 16)}</span> },
                { key: 'market', header: 'Market', render: r => fmt(r.canonical_market_id) },
                { key: 'side', header: 'Side', render: r => fmt(r.side) },
                { key: 'qty', header: 'Quantity', render: r => fmt(r.quantity) },
                { key: 'price', header: 'Price', render: r => fmt(r.price) },
                { key: 'status', header: 'Status', render: r => <Badge variant="default">{fmt(r.status)}</Badge> },
              ]}
              data={orderRows}
              keyExtractor={r => String(r.order_id)}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Fills</CardTitle></CardHeader>
        <CardContent>
          {fillRows.length === 0 ? (
            <EmptyState title="No fills observed" />
          ) : (
            <DataTable
              columns={[
                { key: 'id', header: 'Fill', render: r => <span className="font-mono">{String(r.fill_id ?? '').slice(0, 16)}</span> },
                { key: 'market', header: 'Market', render: r => fmt(r.canonical_market_id) },
                { key: 'qty', header: 'Quantity', render: r => fmt(r.quantity) },
                { key: 'price', header: 'Price', render: r => fmt(r.price) },
                { key: 'fee', header: 'Fee', render: r => fmt(r.fee_amount) },
                { key: 'at', header: 'Executed', render: r => fmt(r.executed_at) },
              ]}
              data={fillRows}
              keyExtractor={r => String(r.fill_id)}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Positions</CardTitle></CardHeader>
        <CardContent>
          {positionRows.length === 0 ? (
            <EmptyState title="No positions observed" />
          ) : (
            <DataTable
              columns={[
                { key: 'market', header: 'Market', render: r => fmt(r.canonical_market_id) },
                { key: 'side', header: 'Side', render: r => fmt(r.side) },
                { key: 'size', header: 'Size', render: r => fmt(r.size) },
                { key: 'entry', header: 'Entry', render: r => fmt(r.entry_price) },
                { key: 'rpnl', header: 'Realized P&L', render: r => fmt(r.realized_pnl) },
                { key: 'upnl', header: 'Unrealized P&L', render: r => fmt(r.unrealized_pnl) },
                {
                  key: 'status', header: 'Status',
                  render: r => <Badge variant={r.status === 'open' ? 'success' : 'default'}>{fmt(r.status)}</Badge>,
                },
              ]}
              data={positionRows}
              keyExtractor={r => String(r.position_id)}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
