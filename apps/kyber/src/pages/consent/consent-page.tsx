import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent,
  Badge, Button,
  EmptyState, LoadingState, ScrollArea,
} from '@aether/ui';
import { formatRelativeTime } from '@kyber/lib/utils';
import { useConsentDsrView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asList(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }

function dsrStatusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'completed') return 'success';
  if (status === 'pending') return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

export function ConsentPage() {
  const { requests, complete } = useConsentDsrView();

  const dsrData = asRecord(requests.data);
  const dsrList = asList(dsrData.requests ?? requests.data);

  const pending = dsrList.filter(r => fmt(asRecord(r).status) === 'pending');
  const completed = dsrList.filter(r => fmt(asRecord(r).status) === 'completed');

  return (
    <PageWrapper
      title="Consent & DSR"
      subtitle="Data subject requests and consent management"
    >
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[
          { label: 'Total Requests', value: dsrList.length },
          { label: 'Pending', value: pending.length },
          { label: 'Completed', value: completed.length },
        ].map(({ label, value }) => (
          <div key={label} className="bg-surface-raised border border-border-default rounded px-3 py-2">
            <p className="text-[10px] text-text-muted font-mono">{label}</p>
            <p className="text-xl font-bold font-mono text-text-primary">{value}</p>
          </div>
        ))}
      </div>

      {requests.isLoading ? <LoadingState lines={5} /> : (
        <ScrollArea maxHeight="600px">
          {dsrList.length === 0 ? (
            <EmptyState title="No DSR requests" description="No data subject requests on record." icon="✓" />
          ) : (
            <div className="space-y-2">
              {dsrList.map((req) => {
                const r = asRecord(req);
                const id = fmt(r.request_id ?? r.id);
                const status = fmt(r.status, 'pending');
                return (
                  <Card key={id}>
                    <CardContent className="flex items-center justify-between py-2">
                      <div className="space-y-0.5">
                        <div className="text-xs font-mono font-bold text-text-primary">{fmt(r.request_type, 'deletion')} — {fmt(r.user_id ?? r.entity_id)}</div>
                        <div className="text-[10px] text-text-muted font-mono">
                          {id} · {formatRelativeTime(fmt(r.created_at))}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={dsrStatusVariant(status)}>{status}</Badge>
                        {status === 'pending' && (
                          <Button
                            size="sm"
                            variant="primary"
                            onClick={() => complete.mutate({ requestId: id })}
                            disabled={complete.isLoading}
                          >
                            Complete
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </ScrollArea>
      )}
    </PageWrapper>
  );
}
