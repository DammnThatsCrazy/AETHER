import { useState } from 'react';
import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Button, Tabs, TabsList, TabsTrigger, TabsContent,
  EmptyState, ErrorState, LoadingState, ScrollArea,
} from '@aether/ui';
import { cn, formatRelativeTime } from '@kyber/lib/utils';
import { useResolutionView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asList(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }

function ConfidencePill({ value }: { value: unknown }) {
  const pct = Math.round(Number(value) * 100);
  const color = pct >= 90 ? 'bg-success/20 text-success' : pct >= 70 ? 'bg-warning/20 text-warning' : 'bg-danger/20 text-danger';
  return <span className={cn('px-2 py-0.5 rounded text-xs font-mono font-bold', color)}>{pct}%</span>;
}

export function ResolutionPage() {
  const { pending, config, approve, reject, runBatch } = useResolutionView();
  const [actionId, setActionId] = useState<string | null>(null);

  const pendingList = asList((pending.data as Record<string, unknown> | null)?.decisions ?? pending.data);

  const handleApprove = async (id: string) => {
    setActionId(id);
    await approve.mutate(id);
    setActionId(null);
  };

  const handleReject = async (id: string) => {
    setActionId(id);
    await reject.mutate(id);
    setActionId(null);
  };

  return (
    <PageWrapper
      title="Resolution"
      subtitle="Review and approve identity resolution decisions"
      actions={
        <Button
          variant="secondary"
          size="sm"
          onClick={() => runBatch.mutate(undefined as unknown as void)}
          disabled={runBatch.isLoading}
        >
          {runBatch.isLoading ? 'Running…' : 'Run Batch'}
        </Button>
      }
    >
      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">
            Queue
            {pendingList.length > 0 && (
              <Badge variant="warning" className="ml-1.5">{pendingList.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="config">Config</TabsTrigger>
        </TabsList>

        <TabsContent value="queue">
          {pending.isLoading ? (
            <LoadingState lines={4} />
          ) : pending.error ? (
            <ErrorState title="Failed to load queue" message={String(pending.error)} />
          ) : pendingList.length === 0 ? (
            <EmptyState title="Queue empty" description="No pending resolution decisions." icon="✓" />
          ) : (
            <ScrollArea maxHeight="600px">
              <div className="space-y-2">
                {pendingList.map((item) => {
                  const d = asRecord(item);
                  const id = fmt(d.decision_id ?? d.id);
                  const isActing = actionId === id;
                  return (
                    <Card key={id} className="border-l-4 border-l-accent">
                      <CardContent className="space-y-2">
                        <div className="flex items-center justify-between">
                          <div className="space-y-0.5">
                            <div className="text-xs font-mono font-bold text-text-primary">
                              {fmt(d.entity_a_id)} ↔ {fmt(d.entity_b_id)}
                            </div>
                            <div className="text-[10px] text-text-muted font-mono">
                              {fmt(d.resolution_type, 'merge')} · {formatRelativeTime(fmt(d.created_at))}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <ConfidencePill value={d.confidence ?? 0} />
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => { void handleReject(id); }}
                              disabled={isActing || approve.isLoading || reject.isLoading}
                            >
                              Reject
                            </Button>
                            <Button
                              size="sm"
                              variant="primary"
                              onClick={() => { void handleApprove(id); }}
                              disabled={isActing || approve.isLoading || reject.isLoading}
                            >
                              {isActing && approve.isLoading ? 'Approving…' : 'Approve'}
                            </Button>
                          </div>
                        </div>
                        {Boolean(d.shared_tissue) && (
                          <div className="flex flex-wrap gap-1">
                            {asList(d.shared_tissue).map((t, i) => (
                              <span key={i} className="text-[10px] bg-surface-raised px-1.5 py-0.5 rounded font-mono text-text-secondary">
                                {fmt(t)}
                              </span>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>

        <TabsContent value="config">
          {config.isLoading ? (
            <LoadingState lines={3} />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="font-mono text-xs">Resolution Config</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs font-mono text-text-secondary whitespace-pre-wrap">
                  {JSON.stringify(config.data, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
