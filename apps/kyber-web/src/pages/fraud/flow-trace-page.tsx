import { useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  EmptyState, LoadingState, useToast,
} from '@aether/ui';
import { PermissionGate } from '@kyber/features/permissions';
import {
  useFlowTraces,
  useFlowTraceDetail,
  useCreateFlowTrace,
} from '@kyber/features/fraud/use-fraud';
import { FlowTracePaths } from '@kyber/components/fraud/flow-trace-paths';

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

type Direction = 'upstream' | 'downstream' | 'both';

export function FlowTracePage() {
  const { traceId = '' } = useParams<{ traceId?: string }>();
  const { toast } = useToast();
  const [form, setForm] = useState({
    anchor_entity_id: '',
    direction: 'downstream' as Direction,
    max_hops: 5,
    min_amount_usd: 0,
  });

  const { data: traces, isLoading: tracesLoading, refetch } = useFlowTraces({ limit: 50 });
  const { data: traceDetail, isLoading: detailLoading } = useFlowTraceDetail(traceId);
  const createTrace = useCreateFlowTrace();

  const rawTraces = asRec(traces as unknown);
  const traceList = Array.isArray(rawTraces.traces) ? rawTraces.traces as Record<string, unknown>[] : [];

  async function handleCreate() {
    if (!form.anchor_entity_id.trim()) {
      toast.error('Anchor entity ID is required');
      return;
    }
    await createTrace.mutate({
      anchor_entity_id: form.anchor_entity_id.trim(),
      direction: form.direction,
      max_hops: form.max_hops,
      ...(form.min_amount_usd > 0 ? { min_amount_usd: form.min_amount_usd } : {}),
    });
    if (createTrace.error) {
      toast.error('Trace failed');
    } else {
      toast.success('Trace created');
      setForm({ anchor_entity_id: '', direction: 'downstream', max_hops: 5, min_amount_usd: 0 });
      refetch();
    }
  }

  const trace = asRec(traceDetail);

  return (
    <PermissionGate>
      <div className="flex flex-col gap-4 p-6">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Flow of Funds Trace</h1>
          <p className="text-sm text-text-muted mt-0.5">
            Trace money movement from an anchor entity
          </p>
        </div>

        <Card>
          <CardHeader><CardTitle>New Trace</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3 items-end">
              <div>
                <label className="text-xs text-text-muted block">Anchor Entity ID</label>
                <input
                  className="mt-1 border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary w-48"
                  value={form.anchor_entity_id}
                  onChange={e => setForm(f => ({ ...f, anchor_entity_id: e.target.value }))}
                  placeholder="e.g. entity-123"
                />
              </div>
              <div>
                <label className="text-xs text-text-muted block">Direction</label>
                <select
                  className="mt-1 border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary"
                  value={form.direction}
                  onChange={e => setForm(f => ({ ...f, direction: e.target.value as Direction }))}
                >
                  <option value="downstream">Downstream</option>
                  <option value="upstream">Upstream</option>
                  <option value="both">Both</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-text-muted block">Max Hops</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  className="mt-1 border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary w-20"
                  value={form.max_hops}
                  onChange={e => setForm(f => ({ ...f, max_hops: Number(e.target.value) }))}
                />
              </div>
              <div>
                <label className="text-xs text-text-muted block">Min Amount USD</label>
                <input
                  type="number"
                  min={0}
                  className="mt-1 border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary w-24"
                  value={form.min_amount_usd}
                  onChange={e => setForm(f => ({ ...f, min_amount_usd: Number(e.target.value) }))}
                />
              </div>
              <PermissionGate>
                <Button onClick={handleCreate} disabled={createTrace.isLoading}>
                  {createTrace.isLoading ? 'Tracing…' : 'Trace'}
                </Button>
              </PermissionGate>
            </div>
          </CardContent>
        </Card>

        {traceId && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Trace Result
                {!!trace.cycle_detected && (
                  <Badge variant="danger">Cycle Detected</Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {detailLoading ? (
                <LoadingState lines={4} />
              ) : (
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap gap-3 text-sm">
                    <div>
                      <span className="text-text-muted">Anchor:</span>{' '}
                      <span className="font-mono">{fmt(trace.anchor_entity_id)}</span>
                    </div>
                    <div>
                      <span className="text-text-muted">Direction:</span>{' '}
                      <Badge variant="default">{fmt(trace.direction)}</Badge>
                    </div>
                    <div>
                      <span className="text-text-muted">Sources:</span>{' '}
                      {fmt((trace.source_nodes as unknown[])?.length ?? 0)}
                    </div>
                    <div>
                      <span className="text-text-muted">Sinks:</span>{' '}
                      {fmt((trace.sink_nodes as unknown[])?.length ?? 0)}
                    </div>
                  </div>
                  <FlowTracePaths traceId={traceId} />
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader><CardTitle>Recent Traces</CardTitle></CardHeader>
          <CardContent>
            {tracesLoading ? (
              <LoadingState lines={3} />
            ) : traceList.length === 0 ? (
              <EmptyState title="No traces yet" description="Create a trace above." />
            ) : (
              <div className="flex flex-col gap-1">
                {traceList.map((t, i) => (
                  <div
                    key={fmt(t.id) || i}
                    className="flex items-center justify-between px-2 py-1.5 text-xs hover:bg-surface-raised rounded cursor-pointer"
                    onClick={() => window.location.assign(`/fraud-networks/flow-trace/${fmt(t.id)}`)}
                  >
                    <span className="font-mono text-text-secondary">{fmt(t.anchor_entity_id)}</span>
                    <div className="flex gap-2">
                      <Badge variant="default">{fmt(t.direction)}</Badge>
                      {!!t.cycle_detected && <Badge variant="danger">Cycle</Badge>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PermissionGate>
  );
}
