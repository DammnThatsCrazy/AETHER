import { useState, useEffect } from 'react';
import type { GraphNode, GraphEdge, GraphCluster, GraphLayer, GraphOverlay, EntityType } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockGraphData } from '@shiki/fixtures/graph';
import { api } from '@shiki/lib/api/endpoints';

interface GraphqlNode {
  id: string;
  type: string;
  label?: string;
  x?: number;
  y?: number;
  properties?: Record<string, unknown>;
  [key: string]: unknown;
}

interface GraphqlEdge {
  id?: string;
  source: string;
  target: string;
  type?: string;
  weight?: number;
  properties?: Record<string, unknown>;
  [key: string]: unknown;
}

interface GraphqlCluster {
  id: string;
  label?: string;
  nodeIds: string[];
  [key: string]: unknown;
}

interface GraphqlGraphResponse {
  data: {
    graph?: {
      nodes?: GraphqlNode[];
      edges?: GraphqlEdge[];
      clusters?: GraphqlCluster[];
    };
  } | null;
  errors?: { message: string }[] | null;
}

const GRAPH_QUERY = `
  query FullGraph {
    graph {
      nodes { id type label x y properties }
      edges { id source target type weight properties }
      clusters { id label nodeIds }
    }
  }
`;

function mapNode(raw: GraphqlNode): GraphNode {
  return {
    id: raw.id,
    type: (raw.type as EntityType | 'external') ?? 'customer',
    label: raw.label ?? raw.id,
    trustScore: raw.properties?.trust_score as number | undefined,
    riskScore: raw.properties?.risk_score as number | undefined,
    anomalyScore: raw.properties?.anomaly_score as number | undefined,
    metadata: raw.properties ?? {},
  };
}

function mapEdge(raw: GraphqlEdge, index: number): GraphEdge {
  return {
    id: raw.id ?? `edge-${index}`,
    source: raw.source,
    target: raw.target,
    type: raw.type ?? 'unknown',
    weight: raw.weight ?? 1,
    label: raw.properties?.label as string | undefined,
    metadata: raw.properties ?? {},
  };
}

function mapCluster(raw: GraphqlCluster): GraphCluster {
  const nodeIds = raw.nodeIds ?? [];
  return {
    id: raw.id,
    label: raw.label ?? raw.id,
    nodeIds,
    centroidNodeId: nodeIds[0] ?? raw.id,
    size: nodeIds.length,
    avgTrustScore: 0,
    avgRiskScore: 0,
    anomalyCount: 0,
  };
}

export function useGraphData() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [clusters, setClusters] = useState<GraphCluster[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeLayer, setActiveLayer] = useState<GraphLayer>('all');
  const [activeOverlay, setActiveOverlay] = useState<GraphOverlay>('none');
  const [visibleTypes, setVisibleTypes] = useState<EntityType[]>(['customer', 'wallet', 'agent', 'protocol', 'contract', 'cluster']);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      const data = getMockGraphData();
      setNodes(data.nodes);
      setEdges(data.edges);
      setClusters(data.clusters);
      setIsLoading(false);
      return;
    }

    // Live mode: fetch graph via GraphQL
    setIsLoading(true);
    setError(null);

    api.analytics.graphql(GRAPH_QUERY)
      .then((resp) => {
        const graphResp = resp as GraphqlGraphResponse;

        if (graphResp.errors?.length) {
          const firstErr = graphResp.errors[0];
          throw new Error(firstErr ? firstErr.message : 'Graph query error');
        }

        const graph = graphResp.data?.graph;
        setNodes((graph?.nodes ?? []).map(mapNode));
        setEdges((graph?.edges ?? []).map(mapEdge));
        setClusters((graph?.clusters ?? []).map(mapCluster));
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load graph data');
        setNodes([]);
        setEdges([]);
        setClusters([]);
        setIsLoading(false);
      });
  }, []);

  const filteredNodes = nodes.filter(n => visibleTypes.includes(n.type as EntityType));
  const filteredNodeIds = new Set(filteredNodes.map(n => n.id));
  const filteredEdges = edges.filter(e => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target));

  return {
    nodes: filteredNodes,
    edges: filteredEdges,
    clusters,
    isLoading,
    activeLayer,
    setActiveLayer,
    activeOverlay,
    setActiveOverlay,
    visibleTypes,
    setVisibleTypes,
    selectedNodeId,
    setSelectedNodeId,
    selectedEdgeId,
    setSelectedEdgeId,
  };
}
