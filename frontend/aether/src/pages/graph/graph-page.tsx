import { useState, useCallback, useEffect, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  EmptyState, ErrorState, LoadingState, ScrollArea,
  DataTable, Tabs, TabsList, TabsTrigger, TabsContent,
  cn,
} from '@aether/ui';
import { GraphCanvas } from '@aether-app/components/graph/graph-canvas';
import {
  useGraphData,
  type GraphLayer, type GraphOverlay, type GraphCluster,
} from '@aether-app/features/graph/use-graph-data';
import type { GraphNode, GraphEdge } from '@aether-app/components/graph/graph-canvas';
import { PathInspector } from '@aether-app/components/graph/path-inspector';
import type { RelationshipPath, PathExplanation, PathMode } from '@aether/shared/operational-intelligence';
import { api } from '@aether-app/lib/api/endpoints';

// ── Tenant ID resolution ──────────────────────────────────────────────────────

function useTenantId(): string {
  const [tenantId, setTenantId] = useState('');
  useEffect(() => {
    api.me.profile().then(data => {
      const r = data as Record<string, unknown>;
      const id = String(r['tenant_id'] ?? r['tenantId'] ?? '');
      if (id) setTenantId(id);
    }).catch(() => {});
  }, []);
  return tenantId;
}

// ── Cluster Inspector ─────────────────────────────────────────────────────────

function ClusterInspector({ cluster }: { cluster: GraphCluster }) {
  const navigate = useNavigate();
  return (
    <div className="space-y-3 pt-2">
      <div className="flex items-center gap-2">
        <Badge variant="warning">cluster</Badge>
        <span className="text-sm font-mono text-text-primary">{cluster.label}</span>
      </div>
      <p className="text-xs text-text-secondary">{cluster.size} member entities</p>
      <Button
        variant="primary"
        size="sm"
        className="w-full"
        onClick={() => navigate(`/clusters/${cluster.id}`)}
      >
        Open Cluster360
      </Button>
      <div>
        <p className="text-xs font-medium text-text-secondary mb-1">Member IDs</p>
        <ScrollArea maxHeight="140px">
          <div className="space-y-1">
            {cluster.nodeIds.map(id => (
              <div key={id} className="py-1 px-2 rounded bg-surface-raised text-[10px] font-mono text-text-primary truncate">
                {id}
              </div>
            ))}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}

// ── Campaign drill-down ───────────────────────────────────────────────────────

function CampaignDrillDown({ campaignId }: { campaignId: string }) {
  const navigate = useNavigate();
  return (
    <div className="p-2 rounded border border-border-subtle bg-surface-raised space-y-1">
      <p className="text-xs text-text-muted">Campaign attribution</p>
      <code className="text-[10px] font-mono text-text-primary block truncate">{campaignId}</code>
      <Button
        variant="ghost"
        size="sm"
        className="w-full text-xs"
        onClick={() => navigate(`/campaigns/${campaignId}`)}
      >
        View Campaign Attribution →
      </Button>
    </div>
  );
}

// ── Fraud investigation action ────────────────────────────────────────────────

function FraudInvestigationAction({ nodeId, nodeLabel, tenantId }: { nodeId: string; nodeLabel: string; tenantId: string }) {
  const [sent, setSent] = useState(false);
  const [creating, setCreating] = useState(false);

  async function handleCreate() {
    setCreating(true);
    try {
      const { api } = await import('@aether-app/lib/api/endpoints');
      await api.investigations.create({
        tenantId,
        title: `Risk investigation — ${nodeLabel}`,
        subjects: [{ kind: 'entity', id: nodeId }],
        createdBy: 'analyst',
      });
      setSent(true);
    } catch {
      setSent(false);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="p-2 rounded border border-border-subtle bg-surface-raised space-y-1">
      <p className="text-xs text-text-muted">Risk signals detected</p>
      {sent ? (
        <p className="text-xs text-success">Investigation case created</p>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          className="w-full text-xs"
          onClick={handleCreate}
          disabled={creating}
        >
          {creating ? 'Creating…' : 'Add to Investigation →'}
        </Button>
      )}
    </div>
  );
}

// ── Inspector ─────────────────────────────────────────────────────────────────

function ScoreBar({ label, value, colorFn }: { label: string; value: number | undefined; colorFn: (v: number) => string }) {
  const v = value ?? 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="font-mono text-text-primary">{v.toFixed(2)}</span>
      </div>
      <div className="h-1.5 w-full bg-surface-overlay rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${v * 100}%`, backgroundColor: colorFn(v) }} />
      </div>
    </div>
  );
}

function trustColor(v: number): string { return v >= 0.8 ? '#22c55e' : v >= 0.5 ? '#eab308' : '#ef4444'; }
function riskColor(v: number): string { return v >= 0.7 ? '#ef4444' : v >= 0.4 ? '#eab308' : '#22c55e'; }

type InspectorPayload =
  | { type: 'node'; node: GraphNode; neighbors: GraphNode[]; paths?: string[][] }
  | { type: 'edge'; edge: GraphEdge }
  | { type: 'cluster'; cluster: GraphCluster };

function Inspector({ data, onClose, tenantId }: { data: InspectorPayload; onClose: () => void; tenantId: string }) {
  return (
    <Card className="w-72 flex-shrink-0 overflow-hidden">
      <CardHeader>
        <CardTitle>
          <div className="flex items-center justify-between w-full">
            <span>Inspector</span>
            <Button variant="ghost" size="sm" onClick={onClose}>×</Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea maxHeight="calc(100vh - 280px)">
          {data.type === 'node' && (
            <Tabs defaultValue="details">
              <TabsList>
                <TabsTrigger value="details">Details</TabsTrigger>
                {data.neighbors.length > 0 && <TabsTrigger value="neighbors">Neighbors</TabsTrigger>}
                {data.paths && data.paths.length > 0 && <TabsTrigger value="paths">Path</TabsTrigger>}
              </TabsList>
              <TabsContent value="details">
                <div className="space-y-4 pt-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="accent">{data.node.kind}</Badge>
                    <span className="text-sm font-mono text-text-primary truncate">{data.node.label}</span>
                  </div>
                  <code className="text-xs text-text-muted break-all block">{data.node.id}</code>
                  <ScoreBar label="Trust" value={data.node.trustScore} colorFn={trustColor} />
                  <ScoreBar label="Risk" value={data.node.riskScore} colorFn={riskColor} />
                  {(typeof data.node.metadata.attributed_campaign_id === 'string' || typeof data.node.metadata.campaign_id === 'string') && (
                    <CampaignDrillDown
                      campaignId={String(data.node.metadata.attributed_campaign_id ?? data.node.metadata.campaign_id)}
                    />
                  )}
                  {(data.node.riskScore !== undefined && data.node.riskScore >= 0.4) && (
                    <FraudInvestigationAction nodeId={data.node.id} nodeLabel={data.node.label} tenantId={tenantId} />
                  )}
                  {typeof data.node.metadata.observation_class === 'string' && (
                    <div className="flex items-center gap-2">
                      <Badge variant={
                        data.node.metadata.observation_class === 'observed' ? 'success' :
                        data.node.metadata.observation_class === 'predicted' ? 'warning' :
                        'default'
                      } size="sm">{data.node.metadata.observation_class}</Badge>
                      {data.node.metadata.observation_class === 'predicted' && (
                        <span className="text-[10px] text-text-muted italic">unverified prediction</span>
                      )}
                    </div>
                  )}
                  {(data.node.kind === 'Recommendation' || data.node.kind === 'Prediction') && (
                    <div className="space-y-1 p-2 rounded border border-border-subtle bg-surface-raised">
                      <p className="text-xs font-medium text-text-secondary">Outcome</p>
                      {typeof data.node.metadata.result_state === 'string' && (
                        <div className="flex items-center gap-2">
                          <Badge size="sm" variant={
                            data.node.metadata.result_state === 'converted' ? 'success' :
                            data.node.metadata.result_state === 'churned' ? 'danger' : 'default'
                          }>{data.node.metadata.result_state}</Badge>
                        </div>
                      )}
                      {typeof data.node.metadata.observed_outcome === 'string' && (
                        <p className="text-xs text-text-muted">{data.node.metadata.observed_outcome}</p>
                      )}
                      {typeof data.node.metadata.model_id === 'string' && (
                        <div className="text-[10px] text-text-muted font-mono">
                          {data.node.metadata.model_id}
                          {typeof data.node.metadata.model_version === 'string' && ` v${data.node.metadata.model_version}`}
                        </div>
                      )}
                    </div>
                  )}
                  {Object.keys(data.node.metadata).length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-text-secondary mb-2">Properties</p>
                      <div className="space-y-1">
                        {Object.entries(data.node.metadata).map(([k, v]) => (
                          <div key={k} className="flex justify-between text-xs">
                            <span className="text-text-muted">{k}</span>
                            <span className="text-text-primary font-mono truncate max-w-[120px]">{String(v)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </TabsContent>
              {data.neighbors.length > 0 && (
                <TabsContent value="neighbors">
                  <div className="space-y-1 pt-2">
                    {data.neighbors.map(n => (
                      <div key={n.id} className="flex items-center gap-2 py-1.5 px-2 rounded bg-surface-raised text-xs border border-border-subtle">
                        <Badge>{n.kind}</Badge>
                        <div className="flex-1 min-w-0">
                          <div className="text-text-primary truncate">{n.label}</div>
                          <div className="text-text-muted font-mono truncate text-[10px]">{n.id}</div>
                        </div>
                        {n.trustScore !== undefined && (
                          <span className="font-mono text-text-secondary">{n.trustScore.toFixed(2)}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </TabsContent>
              )}
              {data.paths && data.paths.length > 0 && (
                <TabsContent value="paths">
                  {data.paths.map((path, i) => (
                    <div key={i} className="space-y-1 pt-2">
                      <p className="text-xs text-text-secondary">{path.length} hops</p>
                      <div className="flex flex-wrap items-center gap-1">
                        {path.map((nodeId, j) => (
                          <span key={`${nodeId}-${j}`} className="inline-flex items-center gap-1">
                            <span className="text-[10px] font-mono text-accent bg-accent/10 px-1.5 py-0.5 rounded">{nodeId}</span>
                            {j < path.length - 1 && <span className="text-text-muted text-xs">→</span>}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </TabsContent>
              )}
            </Tabs>
          )}

          {data.type === 'edge' && (
            <div className="space-y-3 pt-2">
              <div className="flex items-center gap-2">
                <Badge variant="info">{data.edge.interactionClass}</Badge>
                <span className="text-sm text-text-primary">{data.edge.relationType}</span>
              </div>
              <div className="space-y-2 text-xs">
                {[['Source', data.edge.source], ['Target', data.edge.target]].map(([label, val]) => (
                  <div key={label} className="flex justify-between">
                    <span className="text-text-secondary">{label}</span>
                    <code className="text-text-primary font-mono truncate max-w-[160px]">{val}</code>
                  </div>
                ))}
                <div className="flex justify-between">
                  <span className="text-text-secondary">Weight</span>
                  <span className="font-mono text-text-primary">{data.edge.weight.toFixed(2)}</span>
                </div>
              </div>
              {Object.keys(data.edge.metadata).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-text-secondary mb-2">Properties</p>
                  <div className="space-y-1">
                    {Object.entries(data.edge.metadata).map(([k, v]) => (
                      <div key={k} className="flex justify-between text-xs">
                        <span className="text-text-muted">{k}</span>
                        <span className="text-text-primary font-mono truncate max-w-[120px]">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {data.type === 'cluster' && (
            <ClusterInspector cluster={data.cluster} />
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

// ── Toolbar ───────────────────────────────────────────────────────────────────

const LAYERS: { value: GraphLayer; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'H2H', label: 'H↔H' },
  { value: 'H2A', label: 'H→A' },
  { value: 'A2H', label: 'A→H' },
  { value: 'A2A', label: 'A↔A' },
];

const OVERLAYS: { value: GraphOverlay; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'trust', label: 'Trust' },
  { value: 'risk', label: 'Risk' },
  { value: 'campaign', label: 'Campaign' },
  { value: 'economic', label: 'Economic' },
  { value: 'fraud', label: 'Fraud' },
];

// ── Node table ────────────────────────────────────────────────────────────────

const NODE_COLUMNS = [
  { key: 'label', header: 'Entity', render: (n: GraphNode) => <span className="font-mono text-text-primary text-xs">{n.label}</span> },
  { key: 'kind', header: 'Kind', render: (n: GraphNode) => <Badge size="sm">{n.kind}</Badge> },
  { key: 'trust', header: 'Trust', render: (n: GraphNode) => <span className={cn('font-mono text-xs', (n.trustScore ?? 0) >= 0.5 ? 'text-success' : 'text-danger')}>{n.trustScore?.toFixed(2) ?? '—'}</span> },
  { key: 'risk', header: 'Risk', render: (n: GraphNode) => <span className={cn('font-mono text-xs', (n.riskScore ?? 0) >= 0.5 ? 'text-danger' : 'text-success')}>{n.riskScore?.toFixed(2) ?? '—'}</span> },
  { key: 'id', header: 'ID', render: (n: GraphNode) => <code className="text-[10px] text-text-muted truncate max-w-[120px] block">{n.id}</code> },
];

// ── Page ──────────────────────────────────────────────────────────────────────

export function GraphPage() {
  const [searchParams] = useSearchParams();
  const deepLinkedEntity = searchParams.get('entity') ?? searchParams.get('selected_entity');
  const deepLinkedCluster = searchParams.get('cluster');

  // Declared before useGraphData so they can be passed as options
  const [replayDate, setReplayDate] = useState<string | null>(null);
  const tenantId = useTenantId();

  const {
    nodes, edges, clusters,
    isLoading, error,
    activeLayer, setActiveLayer,
    overlay, setOverlay,
    getNeighbors,
  } = useGraphData({ asOf: replayDate, tenantId });

  const [viewMode, setViewMode] = useState<'graph' | 'table'>('graph');
  const [inspector, setInspector] = useState<InspectorPayload | null>(null);
  const [pathMode, setPathMode] = useState(false);
  const [traversalMode, setTraversalMode] = useState<PathMode>('shortest');
  const [kPaths, setKPaths] = useState(3);
  const [pathSource, setPathSource] = useState<string | null>(null);
  const [pathResult, setPathResult] = useState<{ nodeIds: string[]; edgeIds: string[] } | null>(null);
  const [activePaths, setActivePaths] = useState<RelationshipPath[]>([]);
  const [activePathIndex, setActivePathIndex] = useState(0);
  const [pathExplanations, setPathExplanations] = useState<Record<string, PathExplanation>>({});
  const [pathLoading, setPathLoading] = useState(false);
  const [pathError, setPathError] = useState<string | null>(null);
  const [highlightedCluster, setHighlightedCluster] = useState<string[] | null>(null);

  const highlightedNodeIds = useMemo(() => {
    if (highlightedCluster) return highlightedCluster;
    if (inspector?.type !== 'node') return undefined;
    const id = inspector.node.id;
    const ids = new Set([id]);
    for (const e of edges) {
      if (e.source === id) ids.add(e.target);
      if (e.target === id) ids.add(e.source);
    }
    return Array.from(ids);
  }, [inspector, edges, highlightedCluster]);

  const handleSelectNode = useCallback(async (node: GraphNode | null) => {
    if (!node) {
      if (!pathMode) { setInspector(null); setHighlightedCluster(null); }
      return;
    }
    if (pathMode) {
      if (!pathSource) {
        setPathSource(node.id);
        setPathResult(null);
        setActivePaths([]);
        setPathError(null);
        return;
      }
      setPathLoading(true);
      setPathError(null);
      try {
        const resp = await api.graphIntelligence.paths({
          tenant_id: tenantId,
          source_id: pathSource,
          target_id: node.id,
          mode: traversalMode,
          ...(traversalMode === 'k_shortest' && kPaths !== undefined ? { k: kPaths } : {}),
          include_explanation: true,
          save_snapshot: true,
        });
        const data = (resp as { data?: { paths?: RelationshipPath[]; explanations?: PathExplanation[] } }).data;
        const paths: RelationshipPath[] = data?.paths ?? [];
        const explanations: PathExplanation[] = data?.explanations ?? [];

        setActivePaths(paths);
        setActivePathIndex(0);
        if (paths.length > 0) {
          const firstPath = paths[0]!;
          setPathResult({ nodeIds: firstPath.ordered_node_ids, edgeIds: firstPath.ordered_edge_ids });
          const explanationMap: Record<string, PathExplanation> = {};
          for (const exp of explanations) {
            explanationMap[exp.path_id] = exp;
          }
          setPathExplanations(explanationMap);
        } else {
          setPathResult(null);
          setPathError('No path found between the selected nodes.');
        }
      } catch (err) {
        setPathError(err instanceof Error ? err.message : 'Failed to find path.');
        setPathResult(null);
      } finally {
        setPathLoading(false);
        setPathSource(null);
      }
      return;
    }
    setHighlightedCluster(null);
    setInspector({ type: 'node', node, neighbors: getNeighbors(node.id) });
  }, [pathMode, pathSource, traversalMode, kPaths, tenantId, getNeighbors]);

  useEffect(() => {
    if (!deepLinkedEntity || isLoading || error) return;
    const node = nodes.find(n => n.id === deepLinkedEntity);
    if (!node) return;
    setViewMode('graph');
    setHighlightedCluster(null);
    setInspector({ type: 'node', node, neighbors: getNeighbors(node.id) });
  }, [deepLinkedEntity, nodes, getNeighbors, isLoading, error]);

  // Deep link from cluster-360 (/graph?cluster=<id>) — seed the cluster
  // selection so the incoming context is preserved, not silently dropped.
  useEffect(() => {
    if (!deepLinkedCluster || isLoading || error) return;
    const cluster = clusters.find(c => c.id === deepLinkedCluster);
    if (!cluster) return;
    setViewMode('graph');
    setHighlightedCluster([...cluster.nodeIds]);
    setInspector({ type: 'cluster', cluster });
  }, [deepLinkedCluster, clusters, isLoading, error]);

  const handleSelectEdge = useCallback((edge: GraphEdge | null) => {
    if (!edge) { setInspector(null); return; }
    setHighlightedCluster(null);
    setInspector({ type: 'edge', edge });
  }, []);

  const handleClusterClick = useCallback((cluster: GraphCluster) => {
    setHighlightedCluster([...cluster.nodeIds]);
    setInspector({ type: 'cluster', cluster });
  }, []);

  const handleClose = useCallback(() => {
    setInspector(null);
    setHighlightedCluster(null);
    setPathResult(null);
    setPathSource(null);
    setActivePaths([]);
    setPathError(null);
  }, []);

  const handlePathModeToggle = useCallback(() => {
    setPathMode(m => {
      if (m) { setPathSource(null); setPathResult(null); setActivePaths([]); setPathError(null); }
      return !m;
    });
  }, []);

  const handlePathTabChange = useCallback((idx: number) => {
    setActivePathIndex(idx);
    const path = activePaths[idx];
    if (path) {
      setPathResult({ nodeIds: path.ordered_node_ids, edgeIds: path.ordered_edge_ids });
    }
  }, [activePaths]);

  const handleLoadExplanation = useCallback(async (pathId: string) => {
    if (pathExplanations[pathId]) return;
    try {
      const resp = await api.graphIntelligence.explain({ tenant_id: tenantId, path_id: pathId });
      const exp = (resp as { data?: PathExplanation }).data;
      if (exp) setPathExplanations(prev => ({ ...prev, [pathId]: exp }));
    } catch { /* ignore */ }
  }, [pathExplanations, tenantId]);

  const handleSaveToInvestigation = useCallback(async (pathId: string, snapshotId?: string) => {
    try {
      await api.investigations.create({
        tenantId,
        title: `Path investigation — ${pathId.slice(0, 8)}`,
        subjects: [],
        createdBy: 'analyst',
      });
      if (snapshotId) {
        // Best-effort: attach snapshot to new case (would need caseId from create response)
      }
    } catch { /* ignore */ }
  }, [tenantId]);

  if (error) {
    return (
      <div className="p-8">
        <ErrorState title="Failed to load graph" message={error} />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-8">
        <LoadingState lines={6} />
      </div>
    );
  }

  // ── Summary stats derived from current graph data ─────────────────────────
  const riskAlertCount = useMemo(
    () => nodes.filter(n => (n.riskScore ?? 0) >= 0.7).length,
    [nodes],
  );

  return (
    <div className="p-6 space-y-4 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Entity Graph</h1>
          <p className="text-sm text-text-secondary mt-0.5">
            H2H / H2A / A2H / A2A connections across your user base
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant={viewMode === 'graph' ? 'primary' : 'ghost'} size="sm" onClick={() => setViewMode('graph')}>Graph</Button>
          <Button variant={viewMode === 'table' ? 'primary' : 'ghost'} size="sm" onClick={() => setViewMode('table')}>Table</Button>
        </div>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-3 rounded-md border border-border-default bg-surface-raised text-center">
          <p className="text-lg font-semibold text-text-primary">{nodes.length}</p>
          <p className="text-xs text-text-muted">Entities</p>
        </div>
        <div className="p-3 rounded-md border border-border-default bg-surface-raised text-center">
          <p className="text-lg font-semibold text-text-primary">{edges.length}</p>
          <p className="text-xs text-text-muted">Relationships</p>
        </div>
        <div className="p-3 rounded-md border border-border-default bg-surface-raised text-center">
          <p className="text-lg font-semibold text-text-primary">{clusters.length}</p>
          <p className="text-xs text-text-muted">Clusters</p>
        </div>
        <div className={cn('p-3 rounded-md border text-center', riskAlertCount > 0 ? 'border-danger/40 bg-danger/5' : 'border-border-default bg-surface-raised')}>
          <p className={cn('text-lg font-semibold', riskAlertCount > 0 ? 'text-danger' : 'text-text-primary')}>{riskAlertCount}</p>
          <p className="text-xs text-text-muted">Risk alerts</p>
        </div>
      </div>

      {/* Truncation warning */}
      {nodes.length >= 500 && (
        <div className="text-xs px-3 py-2 rounded bg-warning/10 border border-warning/30 text-warning">
          Graph shows the first 500 entities. Relationships may be partial. Use filters or zoom to a specific cluster to see complete data.
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-4 flex-wrap border border-border-default rounded-md px-3 py-2 bg-surface-raised">
        {/* Layer filter */}
        <div className="flex items-center gap-1">
          <span className="text-xs text-text-muted mr-1">Layer:</span>
          {LAYERS.map(l => (
            <Button
              key={l.value}
              variant={activeLayer === l.value ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setActiveLayer(l.value)}
            >
              {l.label}
            </Button>
          ))}
        </div>

        {/* Overlay */}
        <div className="flex items-center gap-1">
          <span className="text-xs text-text-muted mr-1">Overlay:</span>
          {OVERLAYS.map(o => (
            <Button
              key={o.value}
              variant={overlay === o.value ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setOverlay(o.value)}
            >
              {o.label}
            </Button>
          ))}
        </div>

        {/* Path mode */}
        <Button
          variant={pathMode ? 'primary' : 'ghost'}
          size="sm"
          onClick={handlePathModeToggle}
        >
          {pathMode ? 'Exit path mode' : 'Path finder'}
        </Button>

        {/* Traversal mode (only when path mode is on) */}
        {pathMode && (
          <>
            {(['shortest', 'strongest', 'k_shortest'] as PathMode[]).map(mode => (
              <Button
                key={mode}
                variant={traversalMode === mode ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setTraversalMode(mode)}
                aria-pressed={traversalMode === mode}
              >
                {mode === 'shortest' ? 'Shortest' : mode === 'strongest' ? 'Strongest' : 'K-Shortest'}
              </Button>
            ))}
            {traversalMode === 'k_shortest' && (
              <div className="flex items-center gap-1">
                <span className="text-xs text-text-muted">K:</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={kPaths}
                  onChange={e => setKPaths(Math.max(1, Math.min(10, Number(e.target.value))))}
                  className="w-14 h-7 text-xs bg-surface-base border border-border-default rounded px-2 text-text-primary"
                  aria-label="Number of paths"
                />
              </div>
            )}
          </>
        )}

        {/* Replay control */}
        <div className="flex items-center gap-1 ml-auto">
          <span className="text-xs text-text-muted">As of:</span>
          <input
            type="date"
            className="text-xs bg-surface-base border border-border-default rounded px-2 py-1 text-text-primary"
            value={replayDate ?? ''}
            onChange={e => setReplayDate(e.target.value || null)}
            aria-label="Replay graph as of date"
          />
          {replayDate && (
            <Button variant="ghost" size="sm" onClick={() => setReplayDate(null)}>
              Live
            </Button>
          )}
        </div>
      </div>

      {/* Replay mode banner */}
      {replayDate && (
        <div className="text-xs px-3 py-2 rounded bg-accent/10 border border-accent/30 text-accent flex items-center justify-between">
          <span>Viewing graph as of <span className="font-mono font-bold">{replayDate}</span> — historical replay mode. Point-in-time filtering applies.</span>
          <Button variant="ghost" size="sm" onClick={() => setReplayDate(null)}>Exit replay</Button>
        </div>
      )}

      {/* Path mode hint */}
      {pathMode && (
        <div className="text-xs px-3 py-2 rounded bg-accent/10 border border-accent/30 text-accent">
          {pathLoading
            ? 'Finding path…'
            : pathError
            ? <span className="text-danger">{pathError}</span>
            : pathSource
            ? <>Source: <span className="font-mono font-bold">{pathSource}</span> — click a target node to find the path.</>
            : 'Click the source node to begin.'
          }
        </div>
      )}

      {/* Main area */}
      <div className="flex gap-3 flex-1 min-h-0" style={{ minHeight: '560px' }}>
        {/* Canvas / table */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {viewMode === 'graph' ? (
            nodes.length === 0 ? (
              <EmptyState
                title="No graph data"
                description="No entity relationships have been recorded yet."
              />
            ) : (
              <GraphCanvas
                nodes={nodes}
                edges={edges}
                overlay={overlay}
                highlightedNodeIds={highlightedNodeIds}
                pathNodeIds={pathResult?.nodeIds}
                pathEdgeIds={pathResult?.edgeIds}
                onSelectNode={handleSelectNode}
                onSelectEdge={handleSelectEdge}
                className="flex-1"
              />
            )
          ) : (
            <Card className="flex-1">
              <CardHeader><CardTitle>Entity list</CardTitle></CardHeader>
              <CardContent>
                <ScrollArea maxHeight="520px">
                  <DataTable
                    columns={NODE_COLUMNS}
                    data={nodes}
                    keyExtractor={n => n.id}
                    onRowClick={n => handleSelectNode(n)}
                  />
                </ScrollArea>
              </CardContent>
            </Card>
          )}

          {/* Clusters */}
          {clusters.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Identity clusters</CardTitle></CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {clusters.map(cluster => (
                    <button
                      key={cluster.id}
                      onClick={() => handleClusterClick(cluster)}
                      className={cn(
                        'text-left p-3 rounded border transition-colors',
                        inspector?.type === 'cluster' && inspector.cluster.id === cluster.id
                          ? 'border-accent bg-accent/10'
                          : 'border-border-subtle bg-surface-raised hover:border-accent/40',
                      )}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-mono text-text-primary truncate">{cluster.label}</span>
                        <Badge size="sm">{cluster.size}</Badge>
                      </div>
                      <p className="text-[10px] text-text-muted">{cluster.nodeIds.length} entities</p>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Path Inspector — shown when paths are available from the API */}
        {activePaths.length > 0 && (
          <div className="w-80 flex-shrink-0 flex flex-col gap-2 overflow-hidden">
            {activePaths.length > 1 && (
              <Tabs
                value={String(activePathIndex)}
                onValueChange={v => handlePathTabChange(Number(v))}
              >
                <TabsList>
                  {activePaths.map((p, i) => (
                    <TabsTrigger key={p.path_id} value={String(i)}>
                      Path {i + 1}
                      <span className="ml-1 text-[10px] text-text-muted font-mono">
                        {Math.round(p.path_confidence * 100)}%
                      </span>
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            )}
            {(() => {
              const currentPath = activePaths[activePathIndex];
              if (!currentPath) return null;
              const currentExplanation = pathExplanations[currentPath.path_id];
              return (
                <PathInspector
                  path={currentPath}
                  {...(currentExplanation !== undefined ? { explanation: currentExplanation } : {})}
                  onLoadExplanation={() => handleLoadExplanation(currentPath.path_id)}
                  onSaveToInvestigation={handleSaveToInvestigation}
                  onClose={handleClose}
                  className="flex-1 overflow-hidden"
                />
              );
            })()}
          </div>
        )}

        {/* Node/edge/cluster Inspector — shown when no path is active */}
        {activePaths.length === 0 && inspector && <Inspector data={inspector} onClose={handleClose} tenantId={tenantId} />}
      </div>
    </div>
  );
}
