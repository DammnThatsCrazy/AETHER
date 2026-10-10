import { Badge, Button, Card, CardContent, CardHeader, CardTitle, formatCount, formatDateTime, useTimeContext, type TimeContext } from '@aether/ui';

interface EdgeDrawerProps {
  readonly edgeId: string;
  readonly edgeData?: Record<string, unknown>;
  readonly onClose: () => void;
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function riskVariant(score: unknown): 'default' | 'warning' | 'danger' {
  const n = Number(score ?? 0);
  if (n >= 75) return 'danger';
  if (n >= 45) return 'warning';
  return 'default';
}

function fmtDate(iso: unknown, ctx: TimeContext): string {
  if (!iso) return '—';
  try { return formatDateTime(String(iso), ctx); } catch { return String(iso); }
}

export function EdgeDrawer({ edgeId, edgeData = {}, onClose }: EdgeDrawerProps) {
  const timeCtx = useTimeContext();
  const linkType = fmt(edgeData.link_type ?? edgeData.type);
  const riskScore = edgeData.risk_score;
  const fromId = fmt(edgeData.from ?? edgeData.source ?? edgeData.from_entity_id);
  const toId = fmt(edgeData.to ?? edgeData.target ?? edgeData.to_entity_id);
  const amount = fmt(edgeData.total_amount_usd ?? edgeData.amount);
  const transferCount = fmt(edgeData.transfer_count ?? edgeData.count);
  const isCircular = Boolean(edgeData.is_circular);
  const evidenceRefs = Array.isArray(edgeData.evidence_refs) ? edgeData.evidence_refs : [];

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-80 bg-surface-raised border-l border-border-default shadow-xl flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
        <h2 className="text-sm font-semibold text-text-primary">Edge Detail</h2>
        <Button variant="ghost" size="sm" onClick={onClose}>✕</Button>
      </div>

      <div className="flex-1 overflow-auto p-4 flex flex-col gap-4">
        <Card>
          <CardHeader><CardTitle>Connection</CardTitle></CardHeader>
          <CardContent>
            <dl className="flex flex-col gap-1.5 text-xs">
              <div className="flex justify-between">
                <dt className="text-text-muted">Edge ID</dt>
                <dd className="font-mono text-[10px] truncate max-w-[160px]">{edgeId}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">Type</dt>
                <dd><Badge variant="default">{linkType}</Badge></dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">From</dt>
                <dd className="font-mono">{fromId}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">To</dt>
                <dd className="font-mono">{toId}</dd>
              </div>
              {isCircular && (
                <div className="flex justify-between">
                  <dt className="text-text-muted">Circular</dt>
                  <dd><Badge variant="danger">Yes</Badge></dd>
                </div>
              )}
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Transfer Details</CardTitle></CardHeader>
          <CardContent>
            <dl className="flex flex-col gap-1.5 text-xs">
              <div className="flex justify-between">
                <dt className="text-text-muted">Total Amount (USD)</dt>
                <dd>{amount !== '—' ? `$${formatCount(Number(amount), timeCtx)}` : '—'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">Transfer Count</dt>
                <dd>{transferCount}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">Risk Score</dt>
                <dd>
                  <Badge variant={riskVariant(riskScore)}>
                    {riskScore !== undefined ? Number(riskScore).toFixed(1) : '—'}
                  </Badge>
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        {evidenceRefs.length > 0 && (
          <Card>
            <CardHeader><CardTitle>Evidence</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-col gap-1">
                {(evidenceRefs as Record<string, unknown>[]).map((ref, i) => (
                  <div key={i} className="text-xs text-text-secondary font-mono truncate">
                    {fmt(ref.type)}: {fmt(ref.id)}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
