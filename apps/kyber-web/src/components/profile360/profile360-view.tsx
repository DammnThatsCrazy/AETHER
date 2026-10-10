import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, EntityAvatar, FreshnessIndicator, Icon, LoadingState, StatusIndicator, Tabs, TabsContent, TabsList, TabsTrigger, TerminalSeparator, TimeWindowSelector } from '@aether/ui';
import type { TimeWindow } from '@aether/ui';
import { GraphContextBar, useGraph, useGraphActions, useGraphContext } from '@aether/ui/exploration';
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
import { graphObjectRef, normalizeEvidence, refForEntity, temporalForWindow, withGraphContext } from '@kyber/features/profile360/profile360-context';

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
  const graph = useGraphContext();
  const graphApi = useGraph();
  const graphActions = useGraphActions();
  const [activeView, setActiveView] = useState<Profile360ViewId | 'social'>('identity');
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('30d');
  const { entity, sections, timeline, graph: profileGraph, highlightedNodeIds, isLoading, error, websocketStatus, actions } = useProfile360(type, id, timeWindow);

  const scopedRef = useCallback((ref: Profile360Reference) => refForEntity(graph.scope, ref.id, ref.type), [graph.scope]);
  const navigateWithContext = useCallback((path: string) => navigate(withGraphContext(path, graphApi.toQuery())), [graphApi, navigate]);

  // Keep the shared graph context's temporal authority aligned with the
  // Profile360 toolbar. The local store still owns presentation-only filtering;
  // temporal state is shared so graph -> profile -> graph retains the window.
  const onTimeWindowChange = useCallback((next: TimeWindow) => {
    setTimeWindow(next);
    graphActions.setGraphContext({ ...graph, temporal: temporalForWindow(next) });
  }, [graph, graphActions]);

  // Profile360 is a graph object too: seed the shared focus once the profile
  // has loaded, without replacing a focus carried by a deep link.
  useEffect(() => {
    if (!id || graph.selection.focused || !entity) return;
    graphActions.focusObject(refForEntity(graph.scope, entity.id, type));
  }, [entity, graph.scope, graph.selection.focused, graphActions, id, type]);

  // A successful profile response is backend evidence of the route's current
  // permission decision. If the response carries richer rights/evidence
  // metadata, retain it in GraphContext; otherwise keep rights unknown rather
  // than asserting a client-side grant.
  useEffect(() => {
    const raw = profileGraph && entity ? entity.metadata : null;
    if (!raw) return;
    const rightsRaw = raw.rights ?? raw.permission ?? raw.authorization;
    const rights = rightsRaw && typeof rightsRaw === 'object' ? rightsRaw as Record<string, unknown> : null;
    const evidence = normalizeEvidence(raw.evidence ?? raw.evidence_refs ?? raw.provenance);
    if (!rights && evidence.length === 0) return;
    const current = graphApi.toGraphQueryContext();
    const nextRights = rights && typeof rights.allowed === 'boolean' ? {
      allowed: rights.allowed,
      decision_id: typeof rights.decision_id === 'string' ? rights.decision_id : null,
      evaluated_at: typeof rights.evaluated_at === 'string' ? rights.evaluated_at : null,
      policy_version: typeof rights.policy_version === 'string' ? rights.policy_version : null,
    } : current.rights;
    const nextEvidence = evidence.length > 0 ? evidence : current.evidence;
    if (JSON.stringify(nextRights) === JSON.stringify(current.rights)
      && JSON.stringify(nextEvidence) === JSON.stringify(current.evidence)) return;
    graphActions.setGraphContext({ ...current, rights: nextRights ?? null, evidence: nextEvidence });
  }, [entity, graphActions, graphApi, profileGraph]);

  const onDrill = useCallback((reference: Profile360Reference) => {
    actions.pushDrill(reference);
    if (reference.id) {
      actions.highlightNodes([reference.id]);
      graphActions.focusObject(scopedRef(reference));
      graphActions.selectObject(scopedRef(reference));
    }
  }, [actions, graphActions, scopedRef]);

  const openReference = useCallback((reference: Profile360Reference) => {
    const ref = scopedRef(reference);
    graphActions.focusObject(ref);
    graphActions.selectObject(ref);
    navigateWithContext(profile360Path(reference.type, reference.id));
  }, [graphActions, navigateWithContext, scopedRef]);

  const headlineMetrics = useMemo(() => [
    { label: 'Events', value: timeline.length },
    { label: 'Nodes', value: profileGraph.nodes.length },
    { label: 'Edges', value: profileGraph.edges.length },
    { label: 'Signals', value: Object.keys(entity?.metadata ?? {}).length },
  ], [entity?.metadata, profileGraph.edges.length, profileGraph.nodes.length, timeline.length]);

  if (isLoading) return <LoadingState lines={8} className="p-8" />;
  if (error) return <EmptyState title="Profile360 failed to load" description={error} />;
  if (!entity) return <EmptyState title="Profile not found" description={`No attributable profile exists for ${id}.`} />;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            {onBack && <Button variant="ghost" size="sm" onClick={onBack}><Icon name="arrow-left-right" size="xs" decorative className="mr-1" />Back</Button>}
            <Badge variant="accent">Profile 360</Badge>
            <Badge>{entity.type}</Badge>
            <Badge variant={wsVariant(websocketStatus)}>{websocketStatus}</Badge>
          </div>
          <div className="flex items-center gap-2">
            <EntityAvatar entityType={entity.type} name={entity.displayLabel} size={32} />
            <h1 className="text-xl font-bold text-text-primary">{entity.displayLabel}</h1>
          </div>
          <div className="mt-1 flex items-center gap-3 text-xs text-text-secondary font-mono">
            <span>{entity.id}</span>
            <StatusIndicator status={entity.health.status} label={entity.health.status} />
          </div>
        </div>
        <div className="flex flex-col items-end gap-3">
          <TimeWindowSelector value={timeWindow} onChange={onTimeWindowChange} />
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

      <GraphContextBar
        workspaceLabel={graph.scope.workspace_id}
        environmentLabel={graph.scope.environment_id}
        timeLabel={graph.temporal.mode === 'window' && graph.temporal.range?.kind === 'instant'
          ? `${graph.temporal.range.start} → ${graph.temporal.range.endExclusive}`
          : graph.temporal.mode}
      />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Surfacing strategy</CardTitle>
            <p className="mt-1 text-xs text-text-secondary">Entity-first summaries keep the page dense while drill panels, graph selection, and timeline replay reveal deeper attribution only on demand.</p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => navigateWithContext('/noesis/graph')}>Back to graph</Button>
            <Button variant="secondary" size="sm" onClick={() => navigateWithContext(entityDetailPath(entity.type, entity.id))}>Legacy entity route</Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            <Badge variant={graph.rights?.allowed === false ? 'danger' : graph.rights?.allowed === true ? 'success' : 'warning'}>
              Rights: {graph.rights?.allowed === false ? 'denied' : graph.rights?.allowed === true ? 'allowed' : 'backend-enforced'}
            </Badge>
            <Badge>Evidence: {graph.evidence.length > 0 ? graph.evidence.length : 'not returned'}</Badge>
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
        <TabsContent value="attribution"><Profile360AttributionPanel sections={sections.attribution ?? []} profileId={id} /></TabsContent>
        <TabsContent value="cluster"><Profile360ClusterPanel sections={sections.cluster ?? []} /></TabsContent>
        <TabsContent value="agents"><Profile360AgentsPanel sections={sections.agents ?? []} /></TabsContent>
        <TabsContent value="intelligence"><Profile360IntelligencePanel sections={sections.intelligence ?? []} /></TabsContent>
        <TabsContent value="recommendations"><Profile360RecommendationsPanel sections={sections.recommendations ?? []} /></TabsContent>
        <TabsContent value="outcomes"><Profile360OutcomesPanel sections={sections.outcomes ?? []} /></TabsContent>
        <TabsContent value="consent"><Profile360ConsentPanel sections={sections.consent ?? []} /></TabsContent>
        <TabsContent value="provenance"><Profile360ProvenancePanel sections={sections.provenance ?? []} /></TabsContent>
        <TabsContent value="quality"><Profile360QualityPanel sections={sections.quality ?? []} /></TabsContent>
        <TabsContent value="graph"><Profile360GraphPanel graph={profileGraph} highlightedNodeIds={highlightedNodeIds} onHighlight={(nodeIds) => {
          actions.highlightNodes(nodeIds);
          if (nodeIds[0]) {
            const node = profileGraph.nodes.find((candidate) => candidate.id === nodeIds[0]);
            if (node) graphActions.focusObject(graphObjectRef(graph.scope, node));
          }
        }} onDrill={onDrill} onOpenReference={(reference) => {
          const ref = scopedRef(reference);
          graphActions.focusObject(ref);
          graphActions.selectObject(ref);
          navigateWithContext(profile360Path(reference.type, reference.id));
        }} /></TabsContent>
        <TabsContent value="timeline"><Profile360TimelinePanel events={timeline} onHighlight={actions.highlightNodes} onDrill={onDrill} /></TabsContent>
        <TabsContent value="analytics"><Profile360SectionGrid sections={sections.analytics ?? []} onDrill={onDrill} /></TabsContent>
        <TabsContent value="debug"><Profile360SectionGrid sections={sections.debug ?? []} onDrill={onDrill} /></TabsContent>
      </Tabs>

      <Profile360DrillStack onOpen={openReference} />
    </div>
  );
}
