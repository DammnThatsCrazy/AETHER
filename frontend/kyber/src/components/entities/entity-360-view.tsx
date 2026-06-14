import { useState, useMemo, useCallback } from 'react';
import type {
  Entity,
  NeedsHelpCard,
  TimelineEvent,
  Intervention,
  EntityRecommendation,
  EntityNote,
  EntityNeighborhood,
  Profile360DrillItem,
} from '@kyber/types';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
  Badge,
  SeverityBadge,
  StatusIndicator,
  Button,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  ScrollArea,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Input,
  TerminalSeparator,
  useToast,
} from '@aether/ui';
import { cn, formatRelativeTime, formatTimestamp } from '@kyber/lib/utils';
import { PermissionGate } from '@kyber/features/permissions';
import { api } from '@kyber/lib/api/endpoints';
import { EntityScoreCard } from './entity-score-card';
import { NeedsHelpPanel } from './needs-help-panel';
import { Profile360SummaryCard } from './profile360-summary-card';
import { Profile360DrillStack } from './profile360-drill-stack';
import { Profile360Views, RealtimeEventIntelligenceFeed } from './profile360-surfaces';
import { getAnalytics, getProfile360Summary, getRelationships } from './profile360-utils';
import { GraphCanvas } from '@kyber/components/graph';
import type { GraphNode, GraphOverlay } from '@kyber/types';

// ── Recommendations panel ─────────────────────────────────────────────────────

function RecommendationsPanel({ recommendations }: { recommendations: readonly EntityRecommendation[] }) {
  const { toast } = useToast();
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  async function handleApprove(id: string) {
    setLoadingId(id);
    try {
      await api.resolution.approve(id);
      toast.success('Recommendation approved');
    } catch {
      toast.error('Failed to approve recommendation');
    } finally {
      setLoadingId(null);
      setApprovingId(null);
    }
  }

  async function handleReject(id: string) {
    setLoadingId(id);
    try {
      await api.resolution.reject(id);
      toast.info('Recommendation rejected');
    } catch {
      toast.error('Failed to reject recommendation');
    } finally {
      setLoadingId(null);
      setRejectingId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recommendations</CardTitle>
      </CardHeader>
      <CardContent>
        {recommendations.length === 0 ? (
          <div className="text-text-muted text-sm py-6 text-center font-mono">No active recommendations.</div>
        ) : (
          <div className="space-y-3">
            {recommendations.map((rec) => (
              <div key={rec.id} className="border border-accent/30 rounded p-3 space-y-2 bg-surface-raised">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <span className="text-sm font-medium text-text-primary">{rec.title}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant="default" size="sm">Class {rec.actionClass}</Badge>
                    <Badge variant={rec.reversible ? 'default' : 'danger'} size="sm">
                      {rec.reversible ? 'Reversible' : 'Irreversible'}
                    </Badge>
                  </div>
                </div>
                <p className="text-xs text-text-secondary">{rec.description}</p>
                <div className="flex items-center gap-4 text-xs text-text-muted font-mono">
                  <span>Confidence: <span className="text-text-secondary">{(rec.confidence * 100).toFixed(0)}%</span></span>
                </div>
                <div>
                  <div className="text-[10px] uppercase text-text-muted font-mono">Rationale</div>
                  <p className="text-xs text-text-secondary mt-0.5">{rec.rationale}</p>
                </div>
                <PermissionGate requires="canApprove" actionClass={rec.actionClass as import('@kyber/types').ActionClass}>
                  <div className="flex items-center gap-2 pt-1 border-t border-border-subtle">
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={loadingId === rec.id}
                      onClick={() => setRejectingId(rec.id)}
                    >
                      Reject
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={loadingId === rec.id}
                      onClick={() => setApprovingId(rec.id)}
                    >
                      Approve
                    </Button>
                  </div>
                </PermissionGate>
              </div>
            ))}
          </div>
        )}
      </CardContent>

      {/* Approve confirm modal */}
      {approvingId && (
        <Modal open onClose={() => setApprovingId(null)}>
          <ModalHeader>Confirm approval</ModalHeader>
          <ModalBody>
            <p className="text-sm text-text-secondary">
              This action cannot be undone. The recommendation will be submitted for execution.
            </p>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setApprovingId(null)}>Cancel</Button>
            <Button
              variant="primary"
              size="sm"
              disabled={loadingId === approvingId}
              onClick={() => void handleApprove(approvingId)}
            >
              Confirm approval
            </Button>
          </ModalFooter>
        </Modal>
      )}

      {/* Reject confirm modal */}
      {rejectingId && (
        <Modal open onClose={() => setRejectingId(null)}>
          <ModalHeader>Confirm rejection</ModalHeader>
          <ModalBody>
            <p className="text-sm text-text-secondary">
              Reject this recommendation? It will be dismissed and removed from the queue.
            </p>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setRejectingId(null)}>Cancel</Button>
            <Button
              variant="danger"
              size="sm"
              disabled={loadingId === rejectingId}
              onClick={() => void handleReject(rejectingId)}
            >
              Confirm rejection
            </Button>
          </ModalFooter>
        </Modal>
      )}
    </Card>
  );
}

interface Entity360ViewProps {
  readonly entity: Entity;
  readonly timeline: readonly TimelineEvent[];
  readonly neighborhood: EntityNeighborhood | null;
  readonly interventions: readonly Intervention[];
  readonly recommendations: readonly EntityRecommendation[];
  readonly notes: readonly EntityNote[];
  readonly needsHelpCard: NeedsHelpCard | null;
  readonly onBack?: (() => void) | undefined;
}

export function Entity360View({
  entity,
  timeline,
  neighborhood,
  interventions,
  recommendations,
  notes,
  needsHelpCard,
  onBack,
}: Entity360ViewProps) {
  const [noteModalOpen, setNoteModalOpen] = useState(false);
  const [newNoteContent, setNewNoteContent] = useState('');
  const [drillStack, setDrillStack] = useState<Profile360DrillItem[]>([]);
  const [graphOverlay, setGraphOverlay] = useState<GraphOverlay>('none');
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<readonly string[]>([]);

  const connectedEntities = useMemo(() => {
    if (!neighborhood) return [];
    return neighborhood.nodes.filter((n) => n.id !== entity.id);
  }, [neighborhood, entity.id]);

  const profile360Summary = useMemo(() => getProfile360Summary(entity, timeline, neighborhood), [entity, timeline, neighborhood]);
  const profile360Relationships = useMemo(() => getRelationships(entity, neighborhood), [entity, neighborhood]);
  const profile360Analytics = useMemo(() => getAnalytics(entity, timeline, neighborhood), [entity, timeline, neighborhood]);
  const pushDrill = (item: Profile360DrillItem) => {
    setDrillStack((prev) => [...prev, item]);
  };

  const onSelectGraphNode = useCallback((node: GraphNode | null) => {
    if (!node) { setHighlightedNodeIds([]); return; }
    setHighlightedNodeIds([node.id]);
    pushDrill({
      id: node.id,
      kind: (node.type === 'external' ? 'human' : node.type) as Profile360DrillItem['kind'],
      label: node.label,
      entityId: node.id,
      metadata: node.metadata ?? {},
    });
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        {onBack && (
          <Button variant="ghost" onClick={onBack} className="text-sm">
            &larr; Back
          </Button>
        )}
        <span className="text-xs text-neutral-500 font-mono">Profile360 / compact drillable identity</span>
      </div>

      <Profile360SummaryCard entity={entity} summary={profile360Summary} />
      <Profile360DrillStack
        stack={drillStack}
        onPop={() => setDrillStack((prev) => prev.slice(0, -1))}
        onReset={() => setDrillStack([])}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Profile360Views
          entity={entity}
          timeline={timeline}
          neighborhood={neighborhood}
          analytics={profile360Analytics}
          relationships={profile360Relationships}
          onDrill={pushDrill}
        />
        <RealtimeEventIntelligenceFeed events={timeline} onDrill={pushDrill} />
      </div>

      <TerminalSeparator />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
          <TabsTrigger value="trust-risk">Trust &amp; Risk</TabsTrigger>
          <TabsTrigger value="notes">Notes</TabsTrigger>
          <TabsTrigger value="actions">Actions</TabsTrigger>
        </TabsList>

        {/* ================================================================ */}
        {/* OVERVIEW TAB                                                      */}
        {/* ================================================================ */}
        <TabsContent value="overview">
          <div className="space-y-4">
            {/* Score Cards */}
            <div className="grid grid-cols-3 gap-3">
              <EntityScoreCard label="Trust Score" value={entity.trustScore} />
              <EntityScoreCard label="Risk Score" value={entity.riskScore} inverted />
              <EntityScoreCard label="Anomaly Score" value={entity.anomalyScore} inverted />
            </div>

            {/* Identity / Context Summary */}
            <Card>
              <CardHeader>
                <CardTitle>Identity &amp; Context</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                  <div>
                    <span className="text-neutral-500">Name:</span>{' '}
                    <span className="text-neutral-200">{entity.name}</span>
                  </div>
                  <div>
                    <span className="text-neutral-500">Type:</span>{' '}
                    <span className="text-neutral-200">{entity.type}</span>
                  </div>
                  <div>
                    <span className="text-neutral-500">ID:</span>{' '}
                    <span className="text-neutral-200 font-mono text-xs">{entity.id}</span>
                  </div>
                  <div>
                    <span className="text-neutral-500">Health:</span>{' '}
                    <StatusIndicator status={entity.health.status} />
                    {entity.health.message && (
                      <span className="text-neutral-400 text-xs ml-2">{entity.health.message}</span>
                    )}
                  </div>
                  <div>
                    <span className="text-neutral-500">Created:</span>{' '}
                    <span className="text-neutral-400 text-xs">{formatTimestamp(entity.createdAt)}</span>
                  </div>
                  <div>
                    <span className="text-neutral-500">Updated:</span>{' '}
                    <span className="text-neutral-400 text-xs">{formatRelativeTime(entity.updatedAt)}</span>
                  </div>
                  <div className="col-span-2">
                    <span className="text-neutral-500">Tags:</span>{' '}
                    <span className="inline-flex gap-1 flex-wrap ml-1">
                      {entity.tags.map((tag) => (
                        <Badge key={tag} variant="default" className="text-xs">{tag}</Badge>
                      ))}
                    </span>
                  </div>
                  {Object.entries(entity.metadata).map(([key, value]) => (
                    <div key={key}>
                      <span className="text-neutral-500">{key}:</span>{' '}
                      <span className="text-neutral-300 text-xs font-mono">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Needs Help Card */}
            {needsHelpCard && <NeedsHelpPanel card={needsHelpCard} />}

            {/* Internal vs Customer Interpretation */}
            <Card>
              <CardHeader>
                <CardTitle>Interpretation</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-xs uppercase tracking-wider text-neutral-500 mb-2">
                      What the entity experienced
                    </div>
                    <p className="text-sm text-neutral-300">
                      {entity.needsHelp
                        ? `Service disruption detected. ${entity.health.message ?? 'Health status is not nominal.'} The entity may be experiencing degraded functionality or delayed responses.`
                        : `Normal operation. All interactions are proceeding within expected parameters. No user-facing impact detected.`}
                    </p>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wider text-neutral-500 mb-2">
                      What KYBER detected
                    </div>
                    <p className="text-sm text-neutral-300">
                      {entity.needsHelp
                        ? `${entity.needsHelpReason ?? 'Anomaly detected.'} Trust: ${entity.trustScore.toFixed(2)}, Risk: ${entity.riskScore.toFixed(2)}, Anomaly: ${entity.anomalyScore.toFixed(2)}. Automated triage has flagged this entity for human review.`
                        : `Entity is within normal operating bounds. Trust score is ${entity.trustScore >= 0.7 ? 'strong' : 'moderate'} at ${entity.trustScore.toFixed(2)}. Risk indicators are ${entity.riskScore < 0.3 ? 'low' : 'elevated'}.`}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Explanation Trace */}
            {(entity.needsHelp || entity.anomalyScore > 0.4) && (
              <Card className="border-amber-400/20">
                <CardHeader>
                  <CardTitle className="text-amber-400">Explanation Trace</CardTitle>
                </CardHeader>
                <CardContent>
                  <ol className="list-decimal list-inside space-y-2 text-sm text-neutral-300">
                    <li>
                      Entity <span className="font-mono text-neutral-200">{entity.id}</span> flagged by anomaly detector
                      (score: {entity.anomalyScore.toFixed(2)})
                    </li>
                    <li>
                      Trust score evaluated at {entity.trustScore.toFixed(2)}{' '}
                      {entity.trustScore < 0.7 ? '(below threshold)' : '(within bounds)'}
                    </li>
                    <li>
                      Risk assessment: {entity.riskScore.toFixed(2)}{' '}
                      {entity.riskScore > 0.5 ? '-- elevated risk triggers review' : '-- within acceptable range'}
                    </li>
                    {entity.needsHelp && (
                      <li>
                        Needs-help flag set: {entity.needsHelpReason ?? 'Automated triage determined assistance required'}
                      </li>
                    )}
                    {needsHelpCard && (
                      <li>
                        Recommended action: {needsHelpCard.recommendedAction} (confidence:{' '}
                        {(needsHelpCard.confidence * 100).toFixed(0)}%)
                      </li>
                    )}
                  </ol>
                  {needsHelpCard && (
                    <div className="mt-3">
                      <a
                        href={needsHelpCard.traceLink}
                        className="text-sm text-blue-400 hover:text-blue-300 underline font-mono"
                      >
                        View full trace: {needsHelpCard.traceLink}
                      </a>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* ================================================================ */}
        {/* TIMELINE TAB                                                      */}
        {/* ================================================================ */}
        <TabsContent value="timeline">
          <Card>
            <CardHeader>
              <CardTitle>Timeline</CardTitle>
            </CardHeader>
            <CardContent>
              {timeline.length === 0 ? (
                <div className="text-neutral-500 text-sm py-6 text-center">
                  No timeline events recorded for this entity.
                </div>
              ) : (
                <ScrollArea className="h-[480px]">
                  <div className="space-y-3">
                    {timeline.map((event) => (
                      <div
                        key={event.id}
                        className="border border-neutral-800 rounded p-3 space-y-1"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <SeverityBadge severity={event.severity} />
                            <span className="text-sm font-medium text-neutral-200">
                              {event.title}
                            </span>
                          </div>
                          <span className="text-xs text-neutral-500">
                            {formatRelativeTime(event.timestamp)}
                          </span>
                        </div>
                        <p className="text-sm text-neutral-400">{event.description}</p>
                        <div className="flex items-center gap-4 text-xs text-neutral-500">
                          <span>Type: {event.type}</span>
                          {event.controller && <span>Controller: {event.controller}</span>}
                          {event.traceId && (
                            <a
                              href={`/traces/${event.traceId}`}
                              className="text-blue-400 hover:text-blue-300 underline font-mono"
                            >
                              {event.traceId}
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ================================================================ */}
        {/* GRAPH TAB                                                         */}
        {/* ================================================================ */}
        <TabsContent value="graph">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Graph Neighborhood</CardTitle>
                <a
                  href={`/noesis?focus=${encodeURIComponent(entity.id)}`}
                  className="text-sm text-blue-400 hover:text-blue-300 underline"
                >
                  View in Noesis &rarr;
                </a>
              </div>
            </CardHeader>
            <CardContent>
              {neighborhood ? (
                <div className="space-y-4">
                  <div className="flex gap-6 text-sm">
                    <div>
                      <span className="text-neutral-500">Nodes:</span>{' '}
                      <span className="font-mono text-neutral-200">{neighborhood.nodes.length}</span>
                    </div>
                    <div>
                      <span className="text-neutral-500">Edges:</span>{' '}
                      <span className="font-mono text-neutral-200">{neighborhood.edges.length}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-xs text-neutral-500 mb-2">
                    <span>Overlay:</span>
                    {(['none', 'trust', 'risk', 'anomaly'] as const).map((o) => (
                      <button
                        key={o}
                        onClick={() => setGraphOverlay(o)}
                        className={cn(
                          'px-2 py-0.5 rounded border text-xs capitalize',
                          graphOverlay === o
                            ? 'border-accent text-accent'
                            : 'border-neutral-700 text-neutral-400 hover:border-neutral-500',
                        )}
                      >
                        {o}
                      </button>
                    ))}
                  </div>
                  <GraphCanvas
                    nodes={[...neighborhood.nodes]}
                    edges={[...neighborhood.edges]}
                    overlay={graphOverlay}
                    highlightedNodeIds={highlightedNodeIds}
                    onSelectNode={onSelectGraphNode}
                    className="min-h-[400px] rounded border border-neutral-800"
                  />

                  {connectedEntities.length > 0 && (
                    <div>
                      <div className="text-xs uppercase tracking-wider text-neutral-500 mb-2">
                        Connected Entities
                      </div>
                      <div className="space-y-1">
                        {connectedEntities.map((node) => (
                          <div
                            key={node.id}
                            className="flex items-center justify-between border border-neutral-800 rounded px-3 py-1.5 text-sm"
                          >
                            <div className="flex items-center gap-2">
                              <Badge variant="default" className="text-xs">{node.type}</Badge>
                              <span className="text-neutral-200">{node.label}</span>
                            </div>
                            <div className="flex items-center gap-3 text-xs font-mono">
                              {node.trustScore !== undefined && (
                                <span className={cn(
                                  node.trustScore > 0.7 ? 'text-green-400' :
                                  node.trustScore >= 0.4 ? 'text-yellow-400' : 'text-red-400'
                                )}>
                                  T:{node.trustScore.toFixed(2)}
                                </span>
                              )}
                              {node.riskScore !== undefined && (
                                <span className={cn(
                                  node.riskScore < 0.3 ? 'text-green-400' :
                                  node.riskScore <= 0.6 ? 'text-yellow-400' : 'text-red-400'
                                )}>
                                  R:{node.riskScore.toFixed(2)}
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-neutral-500 text-sm py-6 text-center">
                  No neighborhood data available for this entity.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ================================================================ */}
        {/* TRUST & RISK TAB                                                  */}
        {/* ================================================================ */}
        <TabsContent value="trust-risk">
          <div className="space-y-4">
            {/* Detailed Score Display */}
            <div className="grid grid-cols-3 gap-3">
              <EntityScoreCard label="Trust Score" value={entity.trustScore} />
              <EntityScoreCard label="Risk Score" value={entity.riskScore} inverted />
              <EntityScoreCard label="Anomaly Score" value={entity.anomalyScore} inverted />
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Score Analysis</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Trust Score</div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 bg-neutral-800 rounded-full h-2">
                      <div
                        className={cn(
                          'h-2 rounded-full',
                          entity.trustScore > 0.7 ? 'bg-green-400' :
                          entity.trustScore >= 0.4 ? 'bg-yellow-400' : 'bg-red-400',
                        )}
                        style={{ width: `${entity.trustScore * 100}%` }}
                      />
                    </div>
                    <span className="text-sm font-mono w-12 text-right">{entity.trustScore.toFixed(2)}</span>
                  </div>
                  <p className="text-xs text-neutral-500 mt-1">
                    {entity.trustScore > 0.7
                      ? 'Entity trust is within healthy bounds. Historical behavior is consistent and verified.'
                      : entity.trustScore >= 0.4
                        ? 'Entity trust is moderate. Some behaviors or associations warrant monitoring.'
                        : 'Entity trust is critically low. Immediate review recommended.'}
                  </p>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Risk Score</div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 bg-neutral-800 rounded-full h-2">
                      <div
                        className={cn(
                          'h-2 rounded-full',
                          entity.riskScore < 0.3 ? 'bg-green-400' :
                          entity.riskScore <= 0.6 ? 'bg-yellow-400' : 'bg-red-400',
                        )}
                        style={{ width: `${entity.riskScore * 100}%` }}
                      />
                    </div>
                    <span className="text-sm font-mono w-12 text-right">{entity.riskScore.toFixed(2)}</span>
                  </div>
                  <p className="text-xs text-neutral-500 mt-1">
                    {entity.riskScore < 0.3
                      ? 'Risk indicators are low. No concerning patterns detected.'
                      : entity.riskScore <= 0.6
                        ? 'Moderate risk detected. Some indicators elevated above baseline.'
                        : 'High risk. Multiple risk indicators are triggered. Escalation may be required.'}
                  </p>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Anomaly Score</div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 bg-neutral-800 rounded-full h-2">
                      <div
                        className={cn(
                          'h-2 rounded-full',
                          entity.anomalyScore < 0.3 ? 'bg-green-400' :
                          entity.anomalyScore <= 0.6 ? 'bg-yellow-400' : 'bg-red-400',
                        )}
                        style={{ width: `${entity.anomalyScore * 100}%` }}
                      />
                    </div>
                    <span className="text-sm font-mono w-12 text-right">{entity.anomalyScore.toFixed(2)}</span>
                  </div>
                  <p className="text-xs text-neutral-500 mt-1">
                    {entity.anomalyScore < 0.3
                      ? 'Behavior is within expected norms. No anomalies detected.'
                      : entity.anomalyScore <= 0.6
                        ? 'Mild anomalous patterns detected. May be transient or require investigation.'
                        : 'Significant anomalous behavior detected. Entity deviates substantially from expected patterns.'}
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* Needs Help detail */}
            {needsHelpCard && <NeedsHelpPanel card={needsHelpCard} />}
          </div>
        </TabsContent>

        {/* ================================================================ */}
        {/* NOTES TAB                                                         */}
        {/* ================================================================ */}
        <TabsContent value="notes">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Notes &amp; Assignments</CardTitle>
                <PermissionGate requires="canWriteNotes">
                  <Button variant="secondary" onClick={() => setNoteModalOpen(true)}>
                    Add Note
                  </Button>
                </PermissionGate>
              </div>
            </CardHeader>
            <CardContent>
              {notes.length === 0 ? (
                <div className="text-neutral-500 text-sm py-6 text-center">
                  No notes for this entity.
                </div>
              ) : (
                <div className="space-y-3">
                  {notes.map((note) => (
                    <div
                      key={note.id}
                      className="border border-neutral-800 rounded p-3 space-y-1"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-neutral-200">{note.author}</span>
                        <span className="text-xs text-neutral-500">
                          {formatRelativeTime(note.createdAt)}
                        </span>
                      </div>
                      <p className="text-sm text-neutral-300">{note.content}</p>
                      {note.updatedAt !== note.createdAt && (
                        <span className="text-xs text-neutral-600">
                          edited {formatRelativeTime(note.updatedAt)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Add Note Modal */}
          {noteModalOpen && (
            <Modal open={noteModalOpen} onClose={() => setNoteModalOpen(false)}>
              <ModalHeader>Add Note for {entity.displayLabel}</ModalHeader>
              <ModalBody>
                <textarea
                  className="w-full h-32 bg-neutral-900 border border-neutral-700 rounded p-3 text-sm text-neutral-200 resize-none focus:outline-none focus:border-neutral-500"
                  placeholder="Enter your note..."
                  value={newNoteContent}
                  onChange={(e) => setNewNoteContent(e.target.value)}
                />
              </ModalBody>
              <ModalFooter>
                <Button variant="ghost" onClick={() => setNoteModalOpen(false)}>
                  Cancel
                </Button>
                <Button
                  variant="secondary"
                  disabled={newNoteContent.trim().length === 0}
                  onClick={() => {
                    // In a real implementation this would call an API
                    setNoteModalOpen(false);
                    setNewNoteContent('');
                  }}
                >
                  Save Note
                </Button>
              </ModalFooter>
            </Modal>
          )}
        </TabsContent>

        {/* ================================================================ */}
        {/* ACTIONS TAB                                                       */}
        {/* ================================================================ */}
        <TabsContent value="actions">
          <div className="space-y-4">
            {/* Interventions */}
            <Card>
              <CardHeader>
                <CardTitle>Past Interventions</CardTitle>
              </CardHeader>
              <CardContent>
                {interventions.length === 0 ? (
                  <div className="text-neutral-500 text-sm py-6 text-center">
                    No interventions recorded for this entity.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {interventions.map((intv) => (
                      <div
                        key={intv.id}
                        className="border border-neutral-800 rounded p-3 space-y-1"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Badge variant="default" className="text-xs">{intv.type}</Badge>
                            <span className="text-sm font-medium text-neutral-200">
                              {intv.description}
                            </span>
                          </div>
                          <span className="text-xs text-neutral-500">
                            {formatRelativeTime(intv.performedAt)}
                          </span>
                        </div>
                        <div className="flex items-center gap-4 text-xs text-neutral-500">
                          <span>By: {intv.performedBy}</span>
                          <span>
                            Reversible:{' '}
                            <span className={intv.reversible ? 'text-green-400' : 'text-red-400'}>
                              {intv.reversible ? 'Yes' : 'No'}
                            </span>
                          </span>
                          {intv.outcome && <span>Outcome: {intv.outcome}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Recommendations */}
            <RecommendationsPanel recommendations={recommendations} />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
