import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Button, Tabs, TabsList, TabsTrigger, TabsContent,
  EmptyState, LoadingState, ScrollArea,
} from '@aether/ui';
import { formatRelativeTime } from '@kyber/lib/utils';
import { useRewardsOpsView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asList(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }

function campaignStatusVariant(s: string): 'success' | 'warning' | 'danger' | 'default' {
  if (s === 'active') return 'success';
  if (s === 'paused') return 'warning';
  if (s === 'ended') return 'danger';
  return 'default';
}

export function RewardsPage() {
  const { campaigns, queueStats, processQueue } = useRewardsOpsView();

  const campaignData = asRecord(campaigns.data);
  const campaignList = asList(campaignData.campaigns ?? campaigns.data);
  const queueData = asRecord(queueStats.data);

  return (
    <PageWrapper
      title="Rewards Ops"
      subtitle="Manage reward campaigns and process queue"
      actions={
        <Button
          variant="secondary"
          size="sm"
          onClick={() => { void processQueue.mutate(undefined as unknown as void); }}
          disabled={processQueue.isLoading}
        >
          {processQueue.isLoading ? 'Processing…' : 'Process Queue'}
        </Button>
      }
    >
      {/* Queue stats */}
      {queueStats.isLoading ? <LoadingState lines={1} /> : (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
          {[
            { label: 'Pending', value: queueData.pending_count ?? queueData.size ?? 0 },
            { label: 'Processing', value: queueData.processing_count ?? 0 },
            { label: 'Failed', value: queueData.failed_count ?? 0 },
          ].map(({ label, value }) => (
            <div key={label} className="bg-surface-raised border border-border-default rounded px-3 py-2">
              <p className="text-[10px] text-text-muted font-mono">{label}</p>
              <p className="text-xl font-bold font-mono text-text-primary">{String(value)}</p>
            </div>
          ))}
        </div>
      )}

      <Tabs defaultValue="campaigns">
        <TabsList>
          <TabsTrigger value="campaigns">
            Campaigns
            <Badge variant="default" className="ml-1.5">{campaignList.length}</Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="campaigns">
          {campaigns.isLoading ? <LoadingState lines={4} /> : campaignList.length === 0 ? (
            <EmptyState title="No campaigns" description="No reward campaigns found." icon="○" />
          ) : (
            <ScrollArea maxHeight="600px">
              <div className="space-y-2">
                {campaignList.map((c) => {
                  const camp = asRecord(c);
                  const id = fmt(camp.campaign_id ?? camp.id);
                  const status = fmt(camp.status, 'draft');
                  return (
                    <Card key={id}>
                      <CardContent className="py-2 flex items-center justify-between">
                        <div className="space-y-0.5">
                          <div className="text-xs font-mono font-bold text-text-primary">{fmt(camp.name)}</div>
                          <div className="text-[10px] font-mono text-text-muted">
                            {id} · {formatRelativeTime(fmt(camp.created_at))}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {camp.total_rewards != null && (
                            <span className="text-xs font-mono text-text-secondary">{fmt(camp.total_rewards)} rewards</span>
                          )}
                          <Badge variant={campaignStatusVariant(status)}>{status}</Badge>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
