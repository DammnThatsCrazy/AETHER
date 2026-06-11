import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, FreshnessIndicator, LoadingState, StatusIndicator, Tabs, TabsContent, TabsList, TabsTrigger, TerminalSeparator, TimeWindowSelector } from '@aether/ui';
import type { TimeWindow } from '@aether/ui';
import { useProfile360 } from '@kyber/features/profile360';
import type { Profile360EntityType, Profile360Reference, Profile360ViewId } from '@kyber/types';
import { entityDetailPath, profile360Path } from '@kyber/routes';
import { Profile360DrillStack } from './profile360-drill-stack';
import { Profile360GraphPanel } from './profile360-graph-panel';
import { Profile360SectionGrid } from './profile360-section-grid';
import { Profile360TimelinePanel } from './profile360-timeline-panel';
import {
  Profile360SessionsPanel,
  Profile360JourneysPanel,
  Profile360WalletsPanel,
  Profile360BehavioralPanel,
  Profile360AttributionPanel,
  Profile360ClusterPanel,
  Profile360AgentsPanel,
  Profile360ConsentPanel,
  Profile360QualityPanel,
  Profile360RecommendationsPanel,
  Profile360OutcomesPanel,
  Profile360IntelligencePanel,
  Profile360ProvenancePanel,
} from './profile360-contextual-panels';
import { KyberSocialIntelligencePanel } from './social-intelligence-panel';

interface Profile360ViewProps {
  readonly type: Profile360EntityType;
  readonly id: string;
  readonly onBack?: () => void;
}

const views: { id: Profile360ViewId | 'social'; label: string }[] = [
  { id: 'identity', label: 'Identity' },
  { id: 'system', label: 'System' },
  { id: 'financial', label: 'Financial' },
  { id: 'cluster', label: 'Cluster' },
  { id: 'sessions', label: 'Sessions' },
  { id: 'journeys', label: 'Journeys' },
  { id: 'social', label: 'Social' },
  { id: 'wallets', label: 'Web3' },
  { id: 'behavioral', label: 'Behavioral' },
  { id: 'attribution', label: 'Attribution' },
  { id: 'agents', label: 'Agents' },
  { id: 'intelligence', label: 'Intelligence' },
  { id: 'recommendations', label: 'Recommendations' },
  { id: 'outcomes', label: 'Outcomes' },
  { id: 'consent', label: 'Consent' },
  { id: 'provenance', label: 'Provenance' },
  { id: 'quality', label: 'Quality' },
  { id: 'graph', label: 'Graph' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'debug', label: 'Debug' },
];

function wsVariant(status: string) {
  if (status === 'connected') return 'success';
  if (status === 'connecting') return 'warning';
  if (status === 'error') return 'danger';
  return 'default';
}

export function Profile360View({ type, id, onBack }: Profile360ViewProps) {
  const navigate = useNavigate();
  const [activeView, setActiveView] = useState<Profile360ViewId | 'social'>('identity');
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('30d');
  const { entity, sections, timeline, graph, highlightedNodeIds, isLoading, error, websocketStatus, actions } = useProfile360(type, id);

  const onDrill = useCallback((reference: Profile360Reference) => {
    actions.pushDrill(reference);
    if (reference.id) actions.highlightNodes([reference.id]);
  }, [actions]);

  const openReference = useCallback((reference: Profile360Reference) => {
    navigate(profile360Path(reference.type, reference.id));
  }, [navigate]);

  const headlineMetrics = useMemo(() => [
    { label: 'Events', value: timeline.length },
    { label: 'Nodes', value: graph.nodes.length },
    { label: 'Edges', value: graph.edges.length },
    { label: 'Signals', value: Object.keys(entity?.metadata ?? {}).length },
  ], [entity?.metadata, graph.edges.length, graph.nodes.length, timeline.length]);

  if (isLoading) return <LoadingState lines={8} className="p-8" />;
  if (error) return <EmptyState title="Profile360 failed to load" description={error} />;
  if (!entity) return <EmptyState title="Profile not found" description={`No attributable profile exists for ${id}.`} />;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            {onBack && <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>}
            <Badge variant="accent">Profile 360</Badge>
            <Badge>{entity.type}</Badge>
            <Badge variant={wsVariant(websocketStatus)}>{websocketStatus}</Badge>
          </div>
          <h1 className="text-xl font-bold text-text-primary">{entity.displayLabel}</h1>
          <div className="mt-1 flex items-center gap-3 text-xs text-text-secondary font-mono">
            <span>{entity.id}</span>
            <StatusIndicator status={entity.health.status} label={entity.health.status} />
          </div>
        </div>
        <div className="flex flex-col items-end gap-3">
          <TimeWindowSelector value={timeWindow} onChange={setTimeWindow} />
          {Boolean(entity.metadata?.computed_at) && (
            <FreshnessIndicator computedAt={String(entity.metadata.computed_at)} />
          )}
          <div className="grid grid-cols-4 gap-2 min-w-[360px]">
            {headlineMetrics.map((metric) => (
              <div key={metric.label} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
                <div className="text-[10px] uppercase text-text-muted">{metric.label}</div>
                <div className="text-lg font-semibold font-mono text-text-primary">{metric.value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <TerminalSeparator />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Surfacing strategy</CardTitle>
            <p className="mt-1 text-xs text-text-secondary">Entity-first summaries keep the page dense while drill panels, graph selection, and timeline replay reveal deeper attribution only on demand.</p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => navigate(entityDetailPath(entity.type, entity.id))}>Legacy entity route</Button>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {['active hours', 'regions', 'spending', 'devices', 'browsers', 'platforms', 'protocols', 'rewards', 'automation ratio', 'trust/risk', 'wallet flows', 'execution traces'].map((label) => <Badge key={label}>{label}</Badge>)}
          </div>
        </CardContent>
      </Card>

      <Tabs value={activeView} onValueChange={(value) => setActiveView(value as Profile360ViewId | 'social')}>
        <TabsList className="overflow-x-auto">
          {views.map((view) => <TabsTrigger key={view.id} value={view.id}>{view.label}</TabsTrigger>)}
        </TabsList>

        <TabsContent value="identity"><Profile360SectionGrid sections={sections.identity ?? []} onDrill={onDrill} /></TabsContent>
        <TabsContent value="system"><Profile360SectionGrid sections={sections.system ?? []} onDrill={onDrill} /></TabsContent>
        <TabsContent value="financial"><Profile360SectionGrid sections={sections.financial ?? []} onDrill={onDrill} /></TabsContent>
        <TabsContent value="sessions"><Profile360SessionsPanel sections={sections.sessions ?? []} /></TabsContent>
        <TabsContent value="journeys"><Profile360JourneysPanel sections={sections.journeys ?? []} /></TabsContent>
        <TabsContent value="social"><KyberSocialIntelligencePanel entityId={id} window={timeWindow} /></TabsContent>
        <TabsContent value="wallets"><Profile360WalletsPanel sections={sections.wallets ?? []} /></TabsContent>
        <TabsContent value="behavioral"><Profile360BehavioralPanel sections={sections.behavioral ?? []} window={timeWindow} /></TabsContent>
        <TabsContent value="attribution"><Profile360AttributionPanel sections={sections.attribution ?? []} /></TabsContent>
        <TabsContent value="cluster"><Profile360ClusterPanel sections={sections.cluster ?? []} /></TabsContent>
        <TabsContent value="agents"><Profile360AgentsPanel sections={sections.agents ?? []} /></TabsContent>
        <TabsContent value="intelligence"><Profile360IntelligencePanel sections={sections.intelligence ?? []} /></TabsContent>
        <TabsContent value="recommendations"><Profile360RecommendationsPanel sections={sections.recommendations ?? []} /></TabsContent>
        <TabsContent value="outcomes"><Profile360OutcomesPanel sections={sections.outcomes ?? []} /></TabsContent>
        <TabsContent value="consent"><Profile360ConsentPanel sections={sections.consent ?? []} /></TabsContent>
        <TabsContent value="provenance"><Profile360ProvenancePanel sections={sections.provenance ?? []} /></TabsContent>
        <TabsContent value="quality"><Profile360QualityPanel sections={sections.quality ?? []} /></TabsContent>
        <TabsContent value="graph"><Profile360GraphPanel graph={graph} highlightedNodeIds={highlightedNodeIds} onHighlight={actions.highlightNodes} onDrill={onDrill} /></TabsContent>
        <TabsContent value="timeline"><Profile360TimelinePanel events={timeline} onHighlight={actions.highlightNodes} onDrill={onDrill} /></TabsContent>
        <TabsContent value="analytics"><Profile360SectionGrid sections={sections.analytics ?? []} onDrill={onDrill} /></TabsContent>
        <TabsContent value="debug"><Profile360SectionGrid sections={sections.debug ?? []} onDrill={onDrill} /></TabsContent>
      </Tabs>

      <Profile360DrillStack onOpen={openReference} />
    </div>
  );
}
