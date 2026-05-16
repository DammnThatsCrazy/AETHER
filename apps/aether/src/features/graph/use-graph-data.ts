import { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '@aether-app/lib/api/endpoints';
import type { GraphNode, GraphEdge } from '@aether-app/components/graph/graph-canvas';

// ── Types ──────────────────────────────────────────────────────────────────────

export interface GraphCluster {
  id: string;
  label: string;
  nodeIds: string[];
  size: number;
}

export type GraphLayer = 'all' | 'H2H' | 'H2A' | 'A2H' | 'A2A';
export type GraphOverlay = 'none' | 'trust' | 'risk';

// ── Helpers ────────────────────────────────────────────────────────────────────

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function interactionClass(edgeType: string | undefined): string {
  if (!edgeType) return 'H2H';
  const t = edgeType.toUpperCase();
  if (t.startsWith('H2A')) return 'H2A';
  if (t.startsWith('A2H')) return 'A2H';
  if (t.startsWith('A2A')) return 'A2A';
  return 'H2H';
}

// ── Mappers ────────────────────────────────────────────────────────────────────

function mapNode(raw: unknown): GraphNode {
  const r = asRecord(raw);
  const props = asRecord(r.properties ?? r.metadata);
  const trustRaw = props.trust_score ?? r.trust_score;
  const riskRaw = props.risk_score ?? r.risk_score;
  const id = String(r.id ?? r.entity_id ?? '');
  return {
    id,
    label: String(r.label ?? r.name ?? r.display_name ?? id),
    kind: String(r.type ?? r.kind ?? r.entity_type ?? 'unknown'),
    ...(typeof trustRaw === 'number' ? { trustScore: trustRaw } : {}),
    ...(typeof riskRaw === 'number' ? { riskScore: riskRaw } : {}),
    metadata: props,
  };
}

function mapDelegationEdge(raw: unknown, idx: number): GraphEdge | null {
  const r = asRecord(raw);
  const source = String(r.grantor_entity_id ?? r.grantor_id ?? r.source ?? '');
  const target = String(r.grantee_entity_id ?? r.grantee_id ?? r.target ?? '');
  if (!source || !target) return null;
  const edgeType = String(r.relation_type ?? r.type ?? 'H2A');
  return {
    id: String(r.id ?? r.delegation_id ?? `del-${idx}`),
    source,
    target,
    relationType: edgeType,
    interactionClass: interactionClass(edgeType),
    weight: typeof r.weight === 'number' ? r.weight : 1,
    metadata: asRecord(r.properties ?? r.metadata),
  };
}

function mapLinkEdge(raw: unknown, entityId: string, idx: number): GraphEdge | null {
  const r = asRecord(raw);
  const otherId = String(r.entity_id ?? r.linked_entity_id ?? r.target_entity_id ?? '');
  if (!otherId || otherId === entityId) return null;
  const edgeType = String(r.relation_type ?? r.interaction_class ?? r.link_type ?? 'H2H');
  const confidence = typeof r.confidence === 'number' ? r.confidence : 0.5;
  return {
    id: String(r.id ?? r.link_id ?? `link-${entityId}-${idx}`),
    source: entityId,
    target: otherId,
    relationType: edgeType,
    interactionClass: interactionClass(edgeType),
    weight: typeof r.weight === 'number' ? r.weight : confidence,
    metadata: asRecord(r.properties ?? r.metadata),
  };
}

// ── Cluster derivation from entity properties ─────────────────────────────────

function deriveClusters(rawEntities: unknown[]): GraphCluster[] {
  const byCluster = new Map<string, string[]>();
  for (const raw of rawEntities) {
    const r = asRecord(raw);
    const props = asRecord(r.properties ?? r.metadata);
    const clusterId = String(props.cluster_id ?? r.cluster_id ?? '');
    const entityId = String(r.id ?? r.entity_id ?? '');
    if (!clusterId || !entityId) continue;
    if (!byCluster.has(clusterId)) byCluster.set(clusterId, []);
    byCluster.get(clusterId)!.push(entityId);
  }
  return Array.from(byCluster.entries())
    .filter(([, ids]) => ids.length > 1)
    .map(([id, nodeIds]) => ({
      id,
      label: `Cluster ${id.slice(0, 6)}`,
      nodeIds,
      size: nodeIds.length,
    }));
}

// ── BFS shortest path ──────────────────────────────────────────────────────────

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

// ── Hook ───────────────────────────────────────────────────────────────────────

const ENTITY_LINK_SAMPLE = 30;

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
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    async function fetchGraph(): Promise<{ nodes: GraphNode[]; edges: GraphEdge[]; clusters: GraphCluster[] }> {
      // 1. All entities → nodes
      const entitiesData = await api.entities.list({ limit: 200 });
      const rawEntities: unknown[] = entitiesData.entities;
      const nodes = rawEntities.map(mapNode).filter(n => n.id.length > 0);

      const edgeMap = new Map<string, GraphEdge>();
      const addEdge = (e: GraphEdge | null) => {
        if (e && !edgeMap.has(e.id)) edgeMap.set(e.id, e);
      };

      // 2. Delegation records → H2A / A2H / A2A edges
      try {
        const delData = await api.graph.delegations({ limit: 500 });
        const rawDels: unknown[] = [...(delData.granted ?? []), ...(delData.received ?? [])];
        rawDels.forEach((d, i) => addEdge(mapDelegationEdge(d, i)));
      } catch { /* delegation endpoint may be empty or unavailable */ }

      // 3. Identity links for a sample of entities → H2H edges
      const sampleIds = nodes.slice(0, ENTITY_LINK_SAMPLE).map(n => n.id);
      const linkResults = await Promise.allSettled(
        sampleIds.map(id => api.graph.links(id, 50)),
      );
      linkResults.forEach((result, i) => {
        if (result.status !== 'fulfilled') return;
        const entityId = sampleIds[i];
        if (!entityId) return;
        result.value.forEach((l, j) => addEdge(mapLinkEdge(l, entityId, j)));
      });

      // 4. Clusters derived from entity-level cluster_id property
      const derivedClusters = deriveClusters(rawEntities);

      return { nodes, edges: Array.from(edgeMap.values()), clusters: derivedClusters };
    }

    fetchGraph()
      .then(({ nodes, edges, clusters }) => {
        if (cancelled) return;
        setAllNodes(nodes);
        setAllEdges(edges);
        setClusters(clusters);
        setIsLoading(false);
      })
      .catch(err => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load graph');
        setIsLoading(false);
      });

    return () => { cancelled = true; };
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
