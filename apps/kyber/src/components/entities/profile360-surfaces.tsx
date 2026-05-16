import { useMemo, useState } from 'react';
import type { Entity, EntityNeighborhood, Profile360Analytics, Profile360DrillItem, Profile360Metric, Profile360Relationship, TimelineEvent } from '@kyber/types';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Tabs, TabsContent, TabsList, TabsTrigger } from '@aether/ui';
import { GraphCanvas } from '@kyber/components/graph';
import { cn, formatRelativeTime } from '@kyber/lib/utils';
import { eventToDrillItem, relationshipToDrillItem } from './profile360-utils';

interface DrillHandlerProps {
  readonly onDrill: (item: Profile360DrillItem) => void;
}

function severityVariant(severity: string): 'default' | 'info' | 'warning' | 'danger' | 'success' {
  if (severity === 'P0' || severity === 'P1') return 'danger';
  if (severity === 'P2') return 'warning';
  if (severity === 'P3') return 'info';
  return 'default';
}

export function UnifiedTemporalActivityTimeline({ timeline, onDrill }: { readonly timeline: readonly TimelineEvent[] } & DrillHandlerProps) {
  const [filter, setFilter] = useState('all');
  const [grouped, setGrouped] = useState(false);
  const filtered = useMemo(() => filter === 'all' ? timeline : timeline.filter((event) => event.type.includes(filter)), [filter, timeline]);
  const groups = useMemo(() => filtered.reduce<Record<string, TimelineEvent[]>>((acc, event) => {
    const key = grouped ? (event.causalityId ?? event.type) : event.id;
    return { ...acc, [key]: [...(acc[key] ?? []), event] };
  }, {}), [filtered, grouped]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Unified Temporal Activity</CardTitle>
        <div className="flex items-center gap-2">
          <Input value={filter} onChange={(event) => setFilter(event.target.value || 'all')} className="h-7 w-36 text-xs" />
          <Button variant="ghost" onClick={() => setGrouped(!grouped)} className="text-xs">{grouped ? 'Ungroup' : 'Group'}</Button>
        </div>
      </CardHeader>
      <CardContent>
        {filtered.length === 0 ? <div className="py-6 text-center text-sm text-neutral-500">No timeline events match this filter.</div> : (
          <div className="space-y-3">
            {Object.entries(groups).map(([groupId, events]) => (
              <div key={groupId} className="border-l border-border-default pl-3">
                {grouped && events.length > 1 && <div className="mb-2 text-[10px] uppercase tracking-wider text-blue-400">causality chain {groupId} · {events.length} events</div>}
                <div className="space-y-2">
                  {events.map((event) => (
                    <button
                      key={event.id}
                      type="button"
                      onClick={() => onDrill(eventToDrillItem(event))}
                      className="w-full rounded border border-border-subtle bg-neutral-950/20 p-3 text-left transition-colors hover:border-accent/40 hover:bg-neutral-900/40"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={severityVariant(event.severity)} className="text-[10px]">{event.type}</Badge>
                            <span className="text-sm font-medium text-neutral-100">{event.title}</span>
                            {event.traceId && <Badge variant="accent" className="text-[10px]">trace</Badge>}
                          </div>
                          <p className="mt-1 text-xs text-neutral-400">{event.description}</p>
                          {event.relatedEntityIds && event.relatedEntityIds.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1">
                              {event.relatedEntityIds.slice(0, 5).map((id) => <Badge key={id} variant="default" className="text-[10px]">{id}</Badge>)}
                            </div>
                          )}
                        </div>
                        <span className="shrink-0 text-xs text-neutral-500">{formatRelativeTime(event.timestamp)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function RelationshipGraphSurface({ relationships, onDrill }: { readonly relationships: readonly Profile360Relationship[] } & DrillHandlerProps) {
  const [filter, setFilter] = useState('');
  const visible = useMemo(() => relationships.filter((rel) => `${rel.relationshipType} ${rel.targetLabel} ${rel.targetType}`.toLowerCase().includes(filter.toLowerCase())), [filter, relationships]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Relationship Graph Surface</CardTitle>
        <Input placeholder="Search graph" value={filter} onChange={(event) => setFilter(event.target.value)} className="h-7 w-36 text-xs" />
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {visible.map((relationship) => (
            <button key={relationship.id} type="button" onClick={() => onDrill(relationshipToDrillItem(relationship))} className="w-full rounded border border-border-subtle bg-neutral-950/20 px-3 py-2 text-left hover:border-accent/40">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Badge variant="default" className="text-[10px]">{relationship.targetType}</Badge>
                  <span className="truncate text-sm text-neutral-100">{relationship.targetLabel}</span>
                  <span className="text-xs text-neutral-500">{relationship.relationshipType}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs font-mono">
                  <span className="text-blue-400">S:{relationship.strength.toFixed(2)}</span>
                  {relationship.trustScore !== undefined && <span className={relationship.trustScore > 0.7 ? 'text-green-400' : 'text-yellow-400'}>T:{relationship.trustScore.toFixed(2)}</span>}
                  {relationship.riskScore !== undefined && <span className={relationship.riskScore < 0.3 ? 'text-green-400' : 'text-red-400'}>R:{relationship.riskScore.toFixed(2)}</span>}
                </div>
              </div>
              <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-neutral-500">
                {relationship.firstSeen && <span>first {formatRelativeTime(relationship.firstSeen)}</span>}
                {relationship.lastSeen && <span>last {formatRelativeTime(relationship.lastSeen)}</span>}
              </div>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function RealtimeEventIntelligenceFeed({ events, onDrill }: { readonly events: readonly TimelineEvent[] } & DrillHandlerProps) {
  const recent = events.slice(0, 8);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Realtime Event Intelligence</CardTitle>
        <Badge variant="success" className="text-[10px]">incremental</Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        {recent.map((event) => (
          <button key={event.id} type="button" onClick={() => onDrill(eventToDrillItem(event))} className="flex w-full items-center justify-between gap-3 rounded border border-border-subtle px-2 py-1.5 text-left hover:bg-neutral-900/50">
            <div className="min-w-0">
              <div className="truncate text-xs text-neutral-200">{event.title}</div>
              <div className="truncate text-[11px] text-neutral-500">{event.description}</div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {event.causalityId && <Badge variant="accent" className="text-[10px]">chain</Badge>}
              <span className="text-[11px] text-neutral-500">{formatRelativeTime(event.timestamp)}</span>
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

function AnalyticsBucket({ title, values }: { readonly title: string; readonly values: readonly Profile360Metric[] }) {
  return (
    <div className="rounded border border-border-subtle bg-neutral-950/20 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-neutral-500">{title}</div>
      <div className="space-y-1">
        {values.map((item) => (
          <div key={`${title}-${item.label}`} className="flex justify-between gap-2 text-xs">
            <span className="truncate text-neutral-400">{item.label}</span>
            <span className={cn('font-mono text-neutral-100', item.tone === 'good' && 'text-green-400', item.tone === 'warn' && 'text-yellow-400', item.tone === 'bad' && 'text-red-400')}>{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Profile360AnalyticsPanel({ analytics }: { readonly analytics: Profile360Analytics }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <AnalyticsBucket title="Active hours" values={analytics.activeHours} />
      <AnalyticsBucket title="Regions" values={analytics.regions} />
      <AnalyticsBucket title="Devices" values={analytics.devices} />
      <AnalyticsBucket title="Browsers" values={analytics.browsers} />
      <AnalyticsBucket title="Protocols" values={analytics.protocols} />
      <AnalyticsBucket title="Platforms" values={analytics.platforms} />
      <AnalyticsBucket title="Spending" values={analytics.spendingPatterns} />
      <AnalyticsBucket title="Rewards" values={analytics.rewardOpportunities} />
      <AnalyticsBucket title="Trust / risk" values={analytics.trustSignals} />
      <AnalyticsBucket title="Anomalies" values={analytics.anomalyIndicators} />
    </div>
  );
}

export function Profile360GraphView({ entity, neighborhood, onDrill }: { readonly entity: Entity; readonly neighborhood: EntityNeighborhood | null } & DrillHandlerProps) {
  const [selected, setSelected] = useState<string | null>(null);
  if (!neighborhood) return <div className="py-6 text-center text-sm text-neutral-500">No graph data available.</div>;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card>
        <CardHeader>
          <CardTitle>Graph Visualization</CardTitle>
          <a href={`/noesis?focus=${entity.id}`} className="text-sm text-blue-400 hover:text-blue-300 underline">Open in Noesis →</a>
        </CardHeader>
        <CardContent>
          <div className="h-[420px]">
            <GraphCanvas
              nodes={[...neighborhood.nodes]}
              edges={[...neighborhood.edges]}
              overlay="none"
              highlightedNodeIds={selected ? [selected] : [entity.id]}
              onSelectNode={(node) => {
                setSelected(node?.id ?? null);
                if (node) onDrill({ id: node.id, kind: node.type === 'external' ? 'relationship' : node.type, label: node.label, entityId: node.id, metadata: node.metadata });
              }}
            />
          </div>
        </CardContent>
      </Card>
      <RelationshipGraphSurface relationships={neighborhood.edges.map((edge) => ({
        id: edge.id,
        sourceId: edge.source,
        targetId: edge.source === entity.id ? edge.target : edge.source,
        targetType: neighborhood.nodes.find((node) => node.id === (edge.source === entity.id ? edge.target : edge.source))?.type ?? 'external',
        targetLabel: neighborhood.nodes.find((node) => node.id === (edge.source === entity.id ? edge.target : edge.source))?.label ?? edge.target,
        relationshipType: edge.label ?? edge.type,
        strength: edge.weight,
        trustScore: neighborhood.nodes.find((node) => node.id === (edge.source === entity.id ? edge.target : edge.source))?.trustScore,
        riskScore: neighborhood.nodes.find((node) => node.id === (edge.source === entity.id ? edge.target : edge.source))?.riskScore,
        metadata: edge.metadata,
      }))} onDrill={onDrill} />
    </div>
  );
}

export function Profile360Views({ entity, timeline, neighborhood, analytics, relationships, onDrill }: {
  readonly entity: Entity;
  readonly timeline: readonly TimelineEvent[];
  readonly neighborhood: EntityNeighborhood | null;
  readonly analytics: Profile360Analytics;
  readonly relationships: readonly Profile360Relationship[];
} & DrillHandlerProps) {
  return (
    <Tabs defaultValue="identity">
      <TabsList className="overflow-x-auto">
        <TabsTrigger value="identity">Identity</TabsTrigger>
        <TabsTrigger value="system">System</TabsTrigger>
        <TabsTrigger value="financial">Financial</TabsTrigger>
        <TabsTrigger value="graph">Graph</TabsTrigger>
        <TabsTrigger value="analytics">Analytics</TabsTrigger>
        <TabsTrigger value="debug">Debug</TabsTrigger>
      </TabsList>
      <TabsContent value="identity"><RelationshipGraphSurface relationships={relationships} onDrill={onDrill} /></TabsContent>
      <TabsContent value="system"><UnifiedTemporalActivityTimeline timeline={timeline.filter((e) => /agent|delegation|execution|permission|protocol/.test(e.type))} onDrill={onDrill} /></TabsContent>
      <TabsContent value="financial"><UnifiedTemporalActivityTimeline timeline={timeline.filter((e) => /wallet|transaction|reward|financial|spend/.test(e.type))} onDrill={onDrill} /></TabsContent>
      <TabsContent value="graph"><Profile360GraphView entity={entity} neighborhood={neighborhood} onDrill={onDrill} /></TabsContent>
      <TabsContent value="analytics"><Profile360AnalyticsPanel analytics={analytics} /></TabsContent>
      <TabsContent value="debug"><UnifiedTemporalActivityTimeline timeline={timeline.filter((e) => e.traceId || /debug|trace|execution|replay/.test(e.type))} onDrill={onDrill} /></TabsContent>
    </Tabs>
  );
}
