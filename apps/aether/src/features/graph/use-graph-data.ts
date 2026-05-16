import { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '@aether-app/lib/api/endpoints';
import type { GraphNode, GraphEdge } from '@aether-app/components/graph/graph-canvas';

// ── GraphQL query — returns tenant-scoped graph ───────────────────────────────

const GRAPH_QUERY = `
  query TenantGraph {
    graph {
      nodes { id type label x y properties }
      edges { id source target type weight properties }
      clusters { id label nodeIds }
    }
  }
`;

// ── Response types ─────────────────────────────────────────────────────────────

interface GqlNode {
  id: string;
  type?: string;
  label?: string;
  properties?: Record<string, unknown>;
  [k: string]: unknown;
}

interface GqlEdge {
  id?: string;
  source: string;
  target: string;
  type?: string;
  weight?: number;
  properties?: Record<string, unknown>;
}

interface GqlCluster {
  id: string;
  label?: string;
  nodeIds: string[];
}

export interface GraphCluster {
  id: string;
  label: string;
  nodeIds: string[];
  size: number;
}

// ── Interaction class from edge type ─────────────────────────────────────────

function interactionClass(edgeType: string | undefined): string {
  if (!edgeType) return 'H2H';
  const t = edgeType.toUpperCase();
  if (t.startsWith('H2A')) return 'H2A';
  if (t.startsWith('A2H')) return 'A2H';
  if (t.startsWith('A2A')) return 'A2A';
  return 'H2H';
}

// ── Mappers ───────────────────────────────────────────────────────────────────

function mapNode(raw: GqlNode): GraphNode {
  const props = raw.properties ?? {};
  return {
    id: raw.id,
    label: raw.label ?? raw.id,
    kind: raw.type ?? 'unknown',
    ...(typeof props.trust_score === 'number' ? { trustScore: props.trust_score } : {}),
    ...(typeof props.risk_score === 'number' ? { riskScore: props.risk_score } : {}),
    metadata: props,
  };
}

function mapEdge(raw: GqlEdge, idx: number): GraphEdge {
  return {
    id: raw.id ?? `edge-${idx}`,
    source: raw.source,
    target: raw.target,
    relationType: raw.type ?? 'unknown',
    interactionClass: interactionClass(raw.type),
    weight: raw.weight ?? 1,
    metadata: raw.properties ?? {},
  };
}

// ── Layer filter ──────────────────────────────────────────────────────────────

export type GraphLayer = 'all' | 'H2H' | 'H2A' | 'A2H' | 'A2A';
export type GraphOverlay = 'none' | 'trust' | 'risk';

// ── BFS shortest path ─────────────────────────────────────────────────────────

export function bfsPath(
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
    const cur = queue.shift()!;
    for (const { neighborId, edgeId } of adj.get(cur.nodeId) ?? []) {
      if (visited.has(neighborId)) continue;
      const pNodes = [...cur.pathNodes, neighborId];
      const pEdges = [...cur.pathEdges, edgeId];
      if (neighborId === endId) return { nodeIds: pNodes, edgeIds: pEdges };
      visited.add(neighborId);
      queue.push({ nodeId: neighborId, pathNodes: pNodes, pathEdges: pEdges });
    }
  }
  return null;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useGraphData() {
  const [allNodes, setAllNodes] = useState<GraphNode[]>([]);
  const [allEdges, setAllEdges] = useState<GraphEdge[]>([]);
  const [clusters, setClusters] = useState<GraphCluster[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeLayer, setActiveLayer] = useState<GraphLayer>('all');
  const [overlay, setOverlay] = useState<GraphOverlay>('none');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    api.analytics.graphql(GRAPH_QUERY)
      .then(resp => {
        const r = resp as { data: { graph?: { nodes?: GqlNode[]; edges?: GqlEdge[]; clusters?: GqlCluster[] } } | null; errors?: { message: string }[] | null };
        if (r.errors?.length) throw new Error(r.errors[0]?.message ?? 'Graph query error');
        const g = r.data?.graph;
        setAllNodes((g?.nodes ?? []).map(mapNode));
        setAllEdges((g?.edges ?? []).map(mapEdge));
        setClusters((g?.clusters ?? []).map(c => ({ id: c.id, label: c.label ?? c.id, nodeIds: c.nodeIds, size: c.nodeIds.length })));
        setIsLoading(false);
      })
      .catch(err => {
        setError(err instanceof Error ? err.message : 'Failed to load graph');
        setIsLoading(false);
      });
  }, []);

  const nodes = useMemo(() => allNodes, [allNodes]);

  const edges = useMemo(() => {
    if (activeLayer === 'all') return allEdges;
    return allEdges.filter(e => e.interactionClass === activeLayer);
  }, [allEdges, activeLayer]);

  const getNeighbors = useCallback((nodeId: string): GraphNode[] => {
    const ids = new Set<string>();
    for (const e of allEdges) {
      if (e.source === nodeId) ids.add(e.target);
      if (e.target === nodeId) ids.add(e.source);
    }
    return allNodes.filter(n => ids.has(n.id));
  }, [allNodes, allEdges]);

  return {
    nodes, edges, clusters,
    isLoading, error,
    activeLayer, setActiveLayer,
    overlay, setOverlay,
    selectedNodeId, setSelectedNodeId,
    selectedEdgeId, setSelectedEdgeId,
    getNeighbors,
  };
}
