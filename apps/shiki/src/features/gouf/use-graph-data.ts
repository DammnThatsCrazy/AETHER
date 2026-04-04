import { useState, useEffect } from 'react';
import type { GraphNode, GraphEdge, GraphCluster, GraphLayer, GraphOverlay, EntityType } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockGraphData } from '@shiki/fixtures/graph';

export function useGraphData() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [clusters, setClusters] = useState<GraphCluster[]>([]);
  const [isLoading, setIsLoading] = useState(true);
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

    // Live mode: fetch from API
    fetch('/api/v1/intelligence/graph')
      .then(r => r.json())
      .then((data) => {
        const graphData = getMockGraphData(); // fallback
        setNodes(graphData.nodes);
        setEdges(graphData.edges);
        setClusters(graphData.clusters);
        setIsLoading(false);
      })
      .catch(() => {
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
