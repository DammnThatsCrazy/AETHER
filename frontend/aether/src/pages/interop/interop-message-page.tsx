import { useParams, Link } from 'react-router-dom';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState } from '@aether/ui';
import { useInteropMessageDetail } from '@aether-app/features/interop';
import {
  EvidenceBoundary, NotEnabledOrError, asRecord, asList, fmt, messageStatusVariant,
} from '@aether-app/components/domain-intelligence';

export function InteropMessagePage() {
  const { messageId = '' } = useParams();
  const detail = useInteropMessageDetail(messageId);

  if (detail.isLoading && !detail.data) return <LoadingState lines={6} className="p-8" />;
  if (detail.error) {
    return (
      <div className="p-8">
        <NotEnabledOrError error={detail.error} domainLabel="Interoperability Intelligence" onRetry={detail.refetch} />
      </div>
    );
  }

  const payload = asRecord(detail.data);
  const message = asRecord(payload.message);
  const transitions = asList(payload.transitions).map(asRecord);
  const attempts = asList(payload.delivery_attempts).map(asRecord);
  const legs = asList(payload.asset_legs).map(asRecord);

  return (
    <div className="p-6 space-y-6">
      <div>
        <Link to="/interoperability" className="text-xs text-accent hover:underline">← All messages</Link>
        <div className="flex items-center gap-3 mt-1">
          <h1 className="text-xl font-semibold text-text-primary font-mono">{messageId}</h1>
          <Badge variant={messageStatusVariant(String(message.status))}>{fmt(message.status)}</Badge>
        </div>
        <p className="text-sm text-text-secondary mt-1 font-mono">
          {fmt(message.correlation_key)} · {fmt(message.provider_kind)} · path {fmt(message.path_id)}
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Lifecycle timeline</CardTitle></CardHeader>
        <CardContent>
          <EvidenceBoundary>
            Postcondition: lifecycle labels reproduce correlated backend observations.
            “Delivered”, “executed”, or “settled” is not independently verified by this page.
          </EvidenceBoundary>
          {transitions.length === 0 ? (
            <EmptyState title="No lifecycle transitions recorded" />
          ) : (
            <ol className="space-y-2">
              {transitions.map(t => (
                <li key={String(t.transition_id)} className="flex items-center gap-3 text-sm">
                  <span className="text-text-muted font-mono text-xs w-44 flex-shrink-0">{fmt(t.observed_at)}</span>
                  <Badge variant="default">{fmt(t.from_status)}</Badge>
                  <span className="text-text-muted">→</span>
                  <Badge variant={messageStatusVariant(String(t.to_status))}>{fmt(t.to_status)}</Badge>
                  {typeof t.provider_native_stage === 'string' && t.provider_native_stage && (
                    <span className="text-xs text-text-muted font-mono">({t.provider_native_stage})</span>
                  )}
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Delivery attempts</CardTitle></CardHeader>
        <CardContent>
          {attempts.length === 0 ? (
            <EmptyState title="No delivery attempts observed" />
          ) : (
            <DataTable
              columns={[
                { key: 'n', header: '#', render: r => fmt(r.attempt_number) },
                { key: 'status', header: 'Status', render: r => fmt(r.status) },
                { key: 'actor', header: 'Delivery actor', render: r => <span className="font-mono">{fmt(r.delivery_actor_id)}</span> },
                { key: 'tx', header: 'Tx', render: r => <span className="font-mono">{String(r.transaction_hash ?? '—').slice(0, 18)}…</span> },
                { key: 'at', header: 'Observed', render: r => fmt(r.observed_at) },
              ]}
              data={attempts}
              keyExtractor={r => String(r.delivery_attempt_id)}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Asset legs</CardTitle></CardHeader>
        <CardContent>
          <EvidenceBoundary>
            Amounts use the asset and network units returned by the backend; Aether does
            not convert, net, or sum unlike asset legs.
          </EvidenceBoundary>
          {legs.length === 0 ? (
            <EmptyState title="No asset legs attributed" />
          ) : (
            <DataTable
              columns={[
                { key: 'type', header: 'Leg', render: r => <Badge variant="default">{fmt(r.leg_type)}</Badge> },
                { key: 'network', header: 'Network', render: r => fmt(r.network_id) },
                { key: 'asset', header: 'Asset', render: r => fmt(r.asset_id) },
                { key: 'amount', header: 'Amount', render: r => fmt(r.amount_decimal ?? r.amount_atomic) },
                { key: 'from', header: 'From', render: r => <span className="font-mono">{String(r.from_address ?? '—').slice(0, 14)}…</span> },
                { key: 'to', header: 'To', render: r => <span className="font-mono">{String(r.to_address ?? '—').slice(0, 14)}…</span> },
              ]}
              data={legs}
              keyExtractor={r => String(r.asset_leg_id)}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
