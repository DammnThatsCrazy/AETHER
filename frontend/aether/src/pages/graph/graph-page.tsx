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
  useGraphData, bfsPath,
  type GraphLayer, type GraphOverlay, type GraphCluster,
} from '@aether-app/features/graph/use-graph-data';
import type { GraphNode, GraphEdge } from '@aether-app/components/graph/graph-canvas';

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
        onClick={() => navigate(`/measurement/campaigns/${campaignId}`)}
      >
        View Campaign Attribution →
      </Button>
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

function Inspector({ data, onClose }: { data: InspectorPayload; onClose: () => void }) {
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
  const {
    nodes, edges, clusters,
    isLoading, error,
    activeLayer, setActiveLayer,
    overlay, setOverlay,
    getNeighbors,
  } = useGraphData();

  const [viewMode, setViewMode] = useState<'graph' | 'table'>('graph');
  const [inspector, setInspector] = useState<InspectorPayload | null>(null);
  const [pathMode, setPathMode] = useState(false);
  const [pathSource, setPathSource] = useState<string | null>(null);
  const [pathResult, setPathResult] = useState<{ nodeIds: string[]; edgeIds: string[] } | null>(null);
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

  const handleSelectNode = useCallback((node: GraphNode | null) => {
    if (!node) {
      if (!pathMode) { setInspector(null); setHighlightedCluster(null); }
      return;
    }
    if (pathMode) {
      if (!pathSource) { setPathSource(node.id); setPathResult(null); return; }
      const result = bfsPath(pathSource, node.id, edges);
      setPathResult(result);
      setPathSource(null);
      if (result) {
        setInspector({ type: 'node', node, neighbors: getNeighbors(node.id), paths: [result.nodeIds] });
      }
      return;
    }
    setHighlightedCluster(null);
    setInspector({ type: 'node', node, neighbors: getNeighbors(node.id) });
  }, [pathMode, pathSource, edges, getNeighbors]);

  useEffect(() => {
    if (!deepLinkedEntity || isLoading || error) return;
    const node = nodes.find(n => n.id === deepLinkedEntity);
    if (!node) return;
    setViewMode('graph');
    setHighlightedCluster(null);
    setInspector({ type: 'node', node, neighbors: getNeighbors(node.id) });
  }, [deepLinkedEntity, nodes, getNeighbors, isLoading, error]);

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
  }, []);

  const handlePathModeToggle = useCallback(() => {
    setPathMode(m => {
      if (m) { setPathSource(null); setPathResult(null); }
      return !m;
    });
  }, []);

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
          <Badge variant="accent">{nodes.length} nodes</Badge>
          <Badge>{edges.length} edges</Badge>
          <Button variant={viewMode === 'graph' ? 'primary' : 'ghost'} size="sm" onClick={() => setViewMode('graph')}>Graph</Button>
          <Button variant={viewMode === 'table' ? 'primary' : 'ghost'} size="sm" onClick={() => setViewMode('table')}>Table</Button>
        </div>
      </div>

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
      </div>

      {/* Path mode hint */}
      {pathMode && (
        <div className="text-xs px-3 py-2 rounded bg-accent/10 border border-accent/30 text-accent">
          {pathSource
            ? <>Source: <span className="font-mono font-bold">{pathSource}</span> — click a second node to trace the shortest path.</>
            : 'Click the first node to set the path source.'
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

        {/* Inspector */}
        {inspector && <Inspector data={inspector} onClose={handleClose} />}
      </div>
    </div>
  );
}
