import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import {
  Card, CardHeader, CardTitle, CardContent,
  Badge, Button, ScrollArea, DataTable,
  Tabs, TabsList, TabsTrigger, TabsContent,
  EmptyState,
} from '@shiki/components/system';
import { PageWrapper } from '@shiki/components/layout';
import { cn } from '@shiki/lib/utils';
import { GraphCanvas } from '@shiki/components/graph/graph-canvas';
import { GraphInspector } from '@shiki/components/graph/graph-inspector';
import { GraphToolbar } from '@shiki/components/graph/graph-toolbar';
import { GraphControls } from '@shiki/components/graph/graph-controls';
import { getMockGraphData } from '@shiki/fixtures/graph';
import type { GraphNode, GraphEdge, GraphCluster, GraphLayer, GraphOverlay, EntityType, GraphInspectorData } from '@shiki/types';

// ---------------------------------------------------------------------------
// Edge layer classification
// ---------------------------------------------------------------------------

const HUMAN_TYPES: ReadonlySet<string> = new Set(['customer', 'wallet', 'protocol', 'contract', 'cluster', 'external']);
const AGENT_TYPES: ReadonlySet<string> = new Set(['agent']);

function classifyEdgeLayer(edge: GraphEdge, nodeMap: Map<string, GraphNode>): GraphLayer | null {
  const src = nodeMap.get(edge.source);
  const tgt = nodeMap.get(edge.target);
  if (!src || !tgt) return null;
  const srcHuman = HUMAN_TYPES.has(src.type);
  const srcAgent = AGENT_TYPES.has(src.type);
  const tgtHuman = HUMAN_TYPES.has(tgt.type);
  const tgtAgent = AGENT_TYPES.has(tgt.type);
  if (srcHuman && tgtHuman) return 'h2h';
  if (srcHuman && tgtAgent) return 'h2a';
  if (srcAgent && tgtHuman) return 'a2h';
  if (srcAgent && tgtAgent) return 'a2a';
  return 'h2h';
}

// ---------------------------------------------------------------------------
// BFS shortest path
// ---------------------------------------------------------------------------

function bfsShortestPath(
  startId: string,
  endId: string,
  edges: GraphEdge[],
): { nodeIds: string[]; edgeIds: string[] } | null {
  if (startId === endId) return { nodeIds: [startId], edgeIds: [] };

  const adj = new Map<string, { neighborId: string; edgeId: string }[]>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source)!.push({ neighborId: e.target, edgeId: e.id });
    adj.get(e.target)!.push({ neighborId: e.source, edgeId: e.id });
  }

  const visited = new Set<string>([startId]);
  const queue: { nodeId: string; pathNodes: string[]; pathEdges: string[] }[] = [
    { nodeId: startId, pathNodes: [startId], pathEdges: [] },
  ];

  while (queue.length > 0) {
    const current = queue.shift()!;
    const neighbors = adj.get(current.nodeId) ?? [];
    for (const { neighborId, edgeId } of neighbors) {
      if (visited.has(neighborId)) continue;
      const newPathNodes = [...current.pathNodes, neighborId];
      const newPathEdges = [...current.pathEdges, edgeId];
      if (neighborId === endId) {
        return { nodeIds: newPathNodes, edgeIds: newPathEdges };
      }
      visited.add(neighborId);
      queue.push({ nodeId: neighborId, pathNodes: newPathNodes, pathEdges: newPathEdges });
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Time window helpers
// ---------------------------------------------------------------------------

function timeWindowMs(window: string): number {
  switch (window) {
    case '1h': return 60 * 60 * 1000;
    case '6h': return 6 * 60 * 60 * 1000;
    case '24h': return 24 * 60 * 60 * 1000;
    case '7d': return 7 * 24 * 60 * 60 * 1000;
    case '30d': return 30 * 24 * 60 * 60 * 1000;
    default: return 30 * 24 * 60 * 60 * 1000;
  }
}

// ---------------------------------------------------------------------------
// Node table columns
// ---------------------------------------------------------------------------

const NODE_TABLE_COLUMNS = [
  {
    key: 'label',
    header: 'Label',
    render: (row: GraphNode) => <span className="font-mono text-text-primary">{row.label}</span>,
  },
  {
    key: 'type',
    header: 'Type',
    render: (row: GraphNode) => <Badge>{row.type}</Badge>,
  },
  {
    key: 'trustScore',
    header: 'Trust',
    render: (row: GraphNode) => (
      <span className={cn('font-mono', (row.trustScore ?? 0) < 0.5 ? 'text-danger' : 'text-success')}>
        {row.trustScore?.toFixed(2) ?? '--'}
      </span>
    ),
  },
  {
    key: 'riskScore',
    header: 'Risk',
    render: (row: GraphNode) => (
      <span className={cn('font-mono', (row.riskScore ?? 0) > 0.5 ? 'text-danger' : 'text-success')}>
        {row.riskScore?.toFixed(2) ?? '--'}
      </span>
    ),
  },
  {
    key: 'anomalyScore',
    header: 'Anomaly',
    render: (row: GraphNode) => (
      <span className={cn('font-mono', (row.anomalyScore ?? 0) > 0.5 ? 'text-warning' : 'text-text-secondary')}>
        {row.anomalyScore?.toFixed(2) ?? '--'}
      </span>
    ),
  },
  {
    key: 'id',
    header: 'ID',
    render: (row: GraphNode) => <span className="font-mono text-text-muted text-xs truncate max-w-[120px] block">{row.id}</span>,
  },
];

// ---------------------------------------------------------------------------
// GOUF Page
// ---------------------------------------------------------------------------

export function GoufPage() {
  // ---- Source data ----
  const rawData = useMemo(() => getMockGraphData(), []);

  // ---- Graph state ----
  const [activeLayer, setActiveLayer] = useState<GraphLayer>('all');
  const [visibleEntityTypes, setVisibleEntityTypes] = useState<EntityType[]>([
    'customer', 'wallet', 'agent', 'protocol', 'contract', 'cluster',
  ]);
  const [activeOverlay, setActiveOverlay] = useState<GraphOverlay>('none');
  const [timeWindow, setTimeWindow] = useState('30d');
  const [viewMode, setViewMode] = useState<'graph' | 'table'>('graph');

  // ---- Selection state ----
  const [inspectorData, setInspectorData] = useState<GraphInspectorData | null>(null);

  // ---- Path mode ----
  const [pathMode, setPathMode] = useState(false);
  const [pathSource, setPathSource] = useState<string | null>(null);
  const [pathResult, setPathResult] = useState<{ nodeIds: string[]; edgeIds: string[] } | null>(null);

  // ---- Replay state ----
  const [isPlaying, setIsPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState('1');
  const [replayProgress, setReplayProgress] = useState(0);
  const replayIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- Node map ----
  const nodeMap = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const n of rawData.nodes) map.set(n.id, n);
    return map;
  }, [rawData.nodes]);

  // ---- Filter nodes by visible entity types (external is always shown if any type shown) ----
  const filteredNodes = useMemo(() => {
    return rawData.nodes.filter((n) => {
      if (n.type === 'external') return true;
      return visibleEntityTypes.includes(n.type as EntityType);
    });
  }, [rawData.nodes, visibleEntityTypes]);

  // ---- Filter edges by layer and visible nodes ----
  const filteredEdges = useMemo(() => {
    const visibleNodeIds = new Set(filteredNodes.map((n) => n.id));
    return rawData.edges.filter((e) => {
      if (!visibleNodeIds.has(e.source) || !visibleNodeIds.has(e.target)) return false;
      if (activeLayer === 'all') return true;
      const layer = classifyEdgeLayer(e, nodeMap);
      return layer === activeLayer;
    });
  }, [rawData.edges, filteredNodes, activeLayer, nodeMap]);

  // ---- Highlighted nodes (neighborhood of selected) ----
  const highlightedNodeIds = useMemo(() => {
    if (!inspectorData || inspectorData.type !== 'node') return undefined;
    const nodeId = (inspectorData.data as GraphNode).id;
    const ids = new Set<string>([nodeId]);
    for (const e of rawData.edges) {
      if (e.source === nodeId) ids.add(e.target);
      if (e.target === nodeId) ids.add(e.source);
    }
    return Array.from(ids);
  }, [inspectorData, rawData.edges]);

  // ---- Cluster highlighting ----
  const [highlightedClusterIds, setHighlightedClusterIds] = useState<string[] | null>(null);

  const effectiveHighlightIds = useMemo(() => {
    if (highlightedClusterIds) return highlightedClusterIds;
    return highlightedNodeIds;
  }, [highlightedClusterIds, highlightedNodeIds]);

  // ---- Get neighbors for a node ----
  const getNeighbors = useCallback((nodeId: string): GraphNode[] => {
    const neighborIds = new Set<string>();
    for (const e of rawData.edges) {
      if (e.source === nodeId) neighborIds.add(e.target);
      if (e.target === nodeId) neighborIds.add(e.source);
    }
    return rawData.nodes.filter((n) => neighborIds.has(n.id));
  }, [rawData]);

  // ---- Handle node selection ----
  const handleSelectNode = useCallback((node: GraphNode | null) => {
    if (!node) {
      if (!pathMode) {
        setInspectorData(null);
        setHighlightedClusterIds(null);
      }
      return;
    }

    // Path mode: collect two nodes and compute shortest path
    if (pathMode) {
      if (!pathSource) {
        setPathSource(node.id);
        setPathResult(null);
        return;
      }
      // Second node selected
      const result = bfsShortestPath(pathSource, node.id, rawData.edges);
      setPathResult(result);
      setPathSource(null);
      if (result) {
        setInspectorData({
          type: 'node',
          data: node,
          neighbors: getNeighbors(node.id),
          paths: [result.nodeIds],
        });
      }
      return;
    }

    // Normal mode
    setHighlightedClusterIds(null);
    setInspectorData({
      type: 'node',
      data: node,
      neighbors: getNeighbors(node.id),
    });
  }, [pathMode, pathSource, rawData.edges, getNeighbors]);

  // ---- Handle edge selection ----
  const handleSelectEdge = useCallback((edge: GraphEdge | null) => {
    if (!edge) {
      setInspectorData(null);
      return;
    }
    setHighlightedClusterIds(null);
    setInspectorData({ type: 'edge', data: edge });
  }, []);

  // ---- Handle cluster click from sidebar ----
  const handleClusterClick = useCallback((cluster: GraphCluster) => {
    setHighlightedClusterIds([...cluster.nodeIds]);
    setInspectorData({ type: 'cluster', data: cluster });
  }, []);

  // ---- Toggle entity type ----
  const handleToggleEntityType = useCallback((type: EntityType) => {
    setVisibleEntityTypes((prev) => {
      if (prev.includes(type)) {
        return prev.filter((t) => t !== type);
      }
      return [...prev, type];
    });
  }, []);

  // ---- Close inspector ----
  const handleCloseInspector = useCallback(() => {
    setInspectorData(null);
    setHighlightedClusterIds(null);
    setPathResult(null);
    setPathSource(null);
  }, []);

  // ---- Toggle path mode ----
  const handlePathModeChange = useCallback((enabled: boolean) => {
    setPathMode(enabled);
    if (!enabled) {
      setPathSource(null);
      setPathResult(null);
    }
  }, []);

  // ---- Replay controls ----
  const handlePlay = useCallback(() => {
    setIsPlaying(true);
    if (replayIntervalRef.current) clearInterval(replayIntervalRef.current);
    const speedMultiplier = parseFloat(replaySpeed);
    const interval = 100 / speedMultiplier;
    replayIntervalRef.current = setInterval(() => {
      setReplayProgress((prev) => {
        if (prev >= 100) {
          if (replayIntervalRef.current) clearInterval(replayIntervalRef.current);
          setIsPlaying(false);
          return 100;
        }
        return prev + 1;
      });
    }, interval);
  }, [replaySpeed]);

  const handlePause = useCallback(() => {
    setIsPlaying(false);
    if (replayIntervalRef.current) {
      clearInterval(replayIntervalRef.current);
      replayIntervalRef.current = null;
    }
  }, []);

  const handleStop = useCallback(() => {
    setIsPlaying(false);
    setReplayProgress(0);
    if (replayIntervalRef.current) {
      clearInterval(replayIntervalRef.current);
      replayIntervalRef.current = null;
    }
  }, []);

  // Cleanup replay interval on unmount
  useEffect(() => {
    return () => {
      if (replayIntervalRef.current) clearInterval(replayIntervalRef.current);
    };
  }, []);

  // Compute replay timestamp
  const replayTimestamp = useMemo(() => {
    const windowMs = timeWindowMs(timeWindow);
    const now = Date.now();
    const start = now - windowMs;
    const ts = new Date(start + (replayProgress / 100) * windowMs);
    return ts.toISOString();
  }, [replayProgress, timeWindow]);

  return (
    <PageWrapper
      title="GOUF"
      subtitle="Graph intelligence workspace -- topology, overlays, path exploration, and replay"
      actions={
        <div className="flex items-center gap-2">
          <Badge variant={viewMode === 'graph' ? 'accent' : 'default'}>
            {filteredNodes.length} nodes
          </Badge>
          <Badge variant="default">
            {filteredEdges.length} edges
          </Badge>
          <Button
            variant={viewMode === 'graph' ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => setViewMode('graph')}
          >
            Graph
          </Button>
          <Button
            variant={viewMode === 'table' ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => setViewMode('table')}
          >
            Table
          </Button>
        </div>
      }
    >
      {/* Toolbar */}
      <GraphToolbar
        activeLayer={activeLayer}
        onLayerChange={setActiveLayer}
        visibleEntityTypes={visibleEntityTypes}
        onToggleEntityType={handleToggleEntityType}
        activeOverlay={activeOverlay}
        onOverlayChange={setActiveOverlay}
        timeWindow={timeWindow}
        onTimeWindowChange={setTimeWindow}
        pathMode={pathMode}
        onPathModeChange={handlePathModeChange}
      />

      {/* Main Content Area */}
      <div className="flex gap-3" style={{ minHeight: '600px' }}>
        {/* Left: Graph/Table + Clusters */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {viewMode === 'graph' ? (
            <>
              {/* Path mode indicator */}
              {pathMode && (
                <div className="flex items-center gap-2 px-3 py-2 rounded bg-accent/10 border border-accent/30 text-xs text-accent">
                  {pathSource
                    ? <span>Source selected: <span className="font-mono font-bold">{pathSource}</span>. Click a second node to find the shortest path.</span>
                    : <span>Click a node to set the path source.</span>
                  }
                  {pathResult === null && pathSource === null && !pathMode ? null : null}
                </div>
              )}

              {/* Graph Canvas */}
              <GraphCanvas
                nodes={filteredNodes}
                edges={filteredEdges}
                overlay={activeOverlay}
                highlightedNodeIds={effectiveHighlightIds}
                pathNodeIds={pathResult?.nodeIds}
                pathEdgeIds={pathResult?.edgeIds}
                onSelectNode={handleSelectNode}
                onSelectEdge={handleSelectEdge}
                className="flex-1"
              />
            </>
          ) : (
            <Card className="flex-1">
              <CardHeader>
                <CardTitle>Node List</CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea maxHeight="520px">
                  <DataTable
                    columns={NODE_TABLE_COLUMNS}
                    data={filteredNodes}
                    keyExtractor={(row) => row.id}
                  />
                </ScrollArea>
              </CardContent>
            </Card>
          )}

          {/* Replay Controls */}
          <GraphControls
            isPlaying={isPlaying}
            onPlay={handlePlay}
            onPause={handlePause}
            onStop={handleStop}
            speed={replaySpeed}
            onSpeedChange={setReplaySpeed}
            currentTime={replayProgress}
            minTime={0}
            maxTime={100}
            onScrub={setReplayProgress}
            currentTimestamp={replayTimestamp}
          />

          {/* Cluster Overview */}
          <Card>
            <CardHeader>
              <CardTitle>Clusters</CardTitle>
            </CardHeader>
            <CardContent>
              {rawData.clusters.length === 0 ? (
                <EmptyState title="No clusters detected" />
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {rawData.clusters.map((cluster) => (
                    <button
                      key={cluster.id}
                      onClick={() => handleClusterClick(cluster)}
                      className={cn(
                        'text-left p-3 rounded border transition-colors',
                        highlightedClusterIds && inspectorData?.type === 'cluster' && (inspectorData.data as GraphCluster).id === cluster.id
                          ? 'border-accent bg-accent/10'
                          : 'border-border-subtle bg-surface-default hover:border-accent/40',
                      )}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-mono text-text-primary">{cluster.label}</span>
                        <Badge variant={cluster.anomalyCount > 0 ? 'danger' : 'success'}>
                          {cluster.size} nodes
                        </Badge>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-xs">
                        <div>
                          <span className="text-text-muted">Trust</span>
                          <div className={cn('font-mono font-bold', cluster.avgTrustScore < 0.5 ? 'text-danger' : 'text-success')}>
                            {cluster.avgTrustScore.toFixed(2)}
                          </div>
                        </div>
                        <div>
                          <span className="text-text-muted">Risk</span>
                          <div className={cn('font-mono font-bold', cluster.avgRiskScore > 0.5 ? 'text-danger' : 'text-success')}>
                            {cluster.avgRiskScore.toFixed(2)}
                          </div>
                        </div>
                        <div>
                          <span className="text-text-muted">Anomalies</span>
                          <div className={cn('font-mono font-bold', cluster.anomalyCount > 0 ? 'text-danger' : 'text-text-primary')}>
                            {cluster.anomalyCount}
                          </div>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right: Inspector (collapsible) */}
        {inspectorData && (
          <GraphInspector
            data={inspectorData}
            onClose={handleCloseInspector}
          />
        )}
      </div>
    </PageWrapper>
  );
}
