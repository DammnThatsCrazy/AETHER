import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Tabs, TabsList, TabsTrigger, TabsContent,
  LoadingState, EmptyState, ScrollArea,
} from '@aether/ui';
import { usePopulationView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asList(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }
function fmtNum(v: unknown): string { return v == null ? '—' : Number(v).toLocaleString(); }

export function PopulationPage() {
  const { summary, groups } = usePopulationView();

  const summaryData = asRecord(summary.data);
  const byType = asRecord(summaryData.by_type);
  const groupData = asRecord(groups.data);
  const groupList = asList(groupData.groups ?? groups.data);

  return (
    <PageWrapper title="Population" subtitle="Segment overview and group analytics">
      {summary.isLoading ? <LoadingState lines={2} /> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="bg-surface-raised border border-border-default rounded px-3 py-2">
            <p className="text-[10px] text-text-muted font-mono">Total Groups</p>
            <p className="text-xl font-bold font-mono text-text-primary">{fmtNum(summaryData.total_groups)}</p>
          </div>
          <div className="bg-surface-raised border border-border-default rounded px-3 py-2">
            <p className="text-[10px] text-text-muted font-mono">Total Members</p>
            <p className="text-xl font-bold font-mono text-text-primary">{fmtNum(summaryData.total_members)}</p>
          </div>
          {Object.entries(byType).slice(0, 2).map(([type, count]) => (
            <div key={type} className="bg-surface-raised border border-border-default rounded px-3 py-2">
              <p className="text-[10px] text-text-muted font-mono capitalize">{type}</p>
              <p className="text-xl font-bold font-mono text-text-primary">{fmtNum(count)}</p>
            </div>
          ))}
        </div>
      )}

      <Tabs defaultValue="groups">
        <TabsList>
          <TabsTrigger value="groups">Groups</TabsTrigger>
          <TabsTrigger value="breakdown">By Type</TabsTrigger>
        </TabsList>

        <TabsContent value="groups">
          {groups.isLoading ? <LoadingState lines={5} /> : groupList.length === 0 ? (
            <EmptyState title="No groups" description="No population groups found." icon="○" />
          ) : (
            <ScrollArea maxHeight="600px">
              <div className="space-y-2">
                {groupList.map((g, i) => {
                  const group = asRecord(g);
                  return (
                    <Card key={i}>
                      <CardContent className="flex items-center justify-between py-2">
                        <div className="space-y-0.5">
                          <div className="text-xs font-mono font-bold text-text-primary">{fmt(group.name ?? group.population_id)}</div>
                          <div className="text-[10px] font-mono text-text-muted">{fmt(group.population_type)} · {fmtNum(group.member_count)} members</div>
                        </div>
                        <Badge variant="default">{fmt(group.population_type)}</Badge>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>

        <TabsContent value="breakdown">
          <Card>
            <CardHeader><CardTitle className="font-mono text-xs">Distribution by Type</CardTitle></CardHeader>
            <CardContent>
              {Object.keys(byType).length === 0 ? (
                <p className="text-xs text-text-muted font-mono">No breakdown data available.</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(byType).map(([type, count]) => {
                    const total = Object.values(byType).reduce<number>((s, v) => s + Number(v), 0);
                    const pct = total > 0 ? Math.round((Number(count) / total) * 100) : 0;
                    return (
                      <div key={type} className="space-y-1">
                        <div className="flex justify-between text-xs font-mono">
                          <span className="text-text-secondary capitalize">{type}</span>
                          <span className="text-text-primary">{fmtNum(count)} <span className="text-text-muted">({pct}%)</span></span>
                        </div>
                        <div className="h-1.5 bg-surface-overlay rounded-full overflow-hidden">
                          <div className="h-full bg-accent rounded-full" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
