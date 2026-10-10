import { useRef, useEffect, useMemo } from 'react';
import { cn } from '@kyber/lib/utils';
import type { GraphNode, GraphEdge, GraphOverlay } from '@kyber/types';
import { useGraphRuntime, type RuntimeElement } from '@aether/ui/graph';
import type { StylesheetJson } from 'cytoscape';

// ---------------------------------------------------------------------------
// Overlay color helpers
// ---------------------------------------------------------------------------

function trustColor(score: number | undefined): string {
  if (score === undefined) return '#4a6cf7';
  if (score >= 0.8) return '#22c55e';
  if (score >= 0.5) return '#eab308';
  return '#ef4444';
}

function riskColor(score: number | undefined): string {
  if (score === undefined) return '#4a6cf7';
  if (score >= 0.7) return '#ef4444';
  if (score >= 0.4) return '#eab308';
  return '#22c55e';
}

function anomalyColor(score: number | undefined): string {
  if (score === undefined) return '#4a6cf7';
  if (score >= 0.7) return '#ef4444';
  if (score >= 0.4) return '#f97316';
  return '#4a6cf7';
}

// ---------------------------------------------------------------------------
// Props (public API — unchanged)
// ---------------------------------------------------------------------------

interface GraphCanvasProps {
  readonly nodes: GraphNode[];
  readonly edges: GraphEdge[];
  readonly overlay: GraphOverlay;
  readonly highlightedNodeIds?: readonly string[] | undefined;
  readonly pathNodeIds?: readonly string[] | undefined;
  readonly pathEdgeIds?: readonly string[] | undefined;
  readonly onSelectNode?: ((node: GraphNode | null) => void) | undefined;
  readonly onSelectEdge?: ((edge: GraphEdge | null) => void) | undefined;
  readonly className?: string | undefined;
}

// ---------------------------------------------------------------------------
// Style (with semantic-zoom label visibility)
// ---------------------------------------------------------------------------

const GRAPH_STYLE: StylesheetJson = [
  {
    selector: 'node',
    style: {
      'label': 'data(label)',
      'font-size': '10px',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'background-color': '#4a6cf7',
      'width': 30,
      'height': 30,
      'color': '#e8e8f0',
      'text-outline-color': '#0a0a0f',
      'text-outline-width': 1,
    },
  },
  { selector: 'node.human', style: { 'background-color': '#4a6cf7', 'shape': 'ellipse' } },
  { selector: 'node.customer', style: { 'background-color': '#4a6cf7', 'shape': 'ellipse' } },
  { selector: 'node.organization', style: { 'background-color': '#38bdf8', 'shape': 'round-rectangle' } },
  { selector: 'node.wallet', style: { 'background-color': '#22c55e', 'shape': 'diamond' } },
  { selector: 'node.agent', style: { 'background-color': '#f59e0b', 'shape': 'rectangle' } },
  { selector: 'node.journey', style: { 'background-color': '#a855f7', 'shape': 'round-tag' } },
  { selector: 'node.session', style: { 'background-color': '#14b8a6', 'shape': 'barrel' } },
  { selector: 'node.protocol', style: { 'background-color': '#8b5cf6', 'shape': 'hexagon' } },
  { selector: 'node.platform', style: { 'background-color': '#0ea5e9', 'shape': 'round-diamond' } },
  { selector: 'node.device', style: { 'background-color': '#84cc16', 'shape': 'vee' } },
  { selector: 'node.browser', style: { 'background-color': '#10b981', 'shape': 'vee' } },
  { selector: 'node.reward', style: { 'background-color': '#eab308', 'shape': 'star' } },
  { selector: 'node.financial_activity', style: { 'background-color': '#22c55e', 'shape': 'tag' } },
  { selector: 'node.delegation', style: { 'background-color': '#f97316', 'shape': 'rhomboid' } },
  { selector: 'node.relationship', style: { 'background-color': '#94a3b8', 'shape': 'ellipse' } },
  { selector: 'node.contract', style: { 'background-color': '#06b6d4', 'shape': 'triangle' } },
  { selector: 'node.cluster', style: { 'background-color': '#ec4899', 'shape': 'octagon' } },
  { selector: 'node.external', style: { 'background-color': '#64748b', 'shape': 'ellipse' } },
  { selector: 'node.highlighted', style: { 'border-width': 3, 'border-color': '#4a6cf7' } },
  { selector: 'node.path', style: { 'border-width': 3, 'border-color': '#a855f7' } },
  { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#ffffff' } },
  // Semantic zoom: hide labels when zoomed out, restore full detail when zoomed in.
  { selector: 'node.zoom-macro', style: { 'text-opacity': 0 } },
  { selector: 'node.zoom-meso', style: { 'text-opacity': 0.65 } },
  { selector: 'node.zoom-detail', style: { 'text-opacity': 1 } },
  {
    selector: 'edge',
    style: {
      'width': 1,
      'line-color': '#2a2a3a',
      'target-arrow-color': '#2a2a3a',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'opacity': 0.6,
    },
  },
  { selector: 'edge.highlighted', style: { 'line-color': '#4a6cf7', 'width': 2, 'opacity': 1 } },
  { selector: 'edge.path', style: { 'line-color': '#a855f7', 'width': 3, 'opacity': 1 } },
];

function toElements(nodes: readonly GraphNode[], edges: readonly GraphEdge[]): RuntimeElement[] {
  const nodeEls: RuntimeElement[] = nodes.map((n) => ({
    group: 'nodes',
    data: {
      id: n.id,
      label: n.label,
      type: n.type,
      trustScore: n.trustScore,
      riskScore: n.riskScore,
      anomalyScore: n.anomalyScore,
    },
    classes: n.type,
  }));
  const edgeEls: RuntimeElement[] = edges.map((e) => ({
    group: 'edges',
    data: {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      weight: e.weight,
      edgeType: e.type,
    },
  }));
  return [...nodeEls, ...edgeEls];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GraphCanvas({
  nodes,
  edges,
  overlay,
  highlightedNodeIds,
  pathNodeIds,
  pathEdgeIds,
  onSelectNode,
  onSelectEdge,
  className,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const nodesById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const edgesById = useMemo(() => new Map(edges.map((e) => [e.id, e])), [edges]);

  const runtimeRef = useGraphRuntime(containerRef, {
    style: GRAPH_STYLE,
    minZoom: 0.2,
    maxZoom: 5,
    onSelectNode: (id) => onSelectNode?.(id ? nodesById.get(id) ?? null : null),
    onSelectEdge: (id) => onSelectEdge?.(id ? edgesById.get(id) ?? null : null),
  });

  // Data changes → diff + batch apply on the persistent instance.
  useEffect(() => {
    runtimeRef.current?.setElements(toElements(nodes, edges));
  }, [runtimeRef, nodes, edges]);

  // Overlay recolours existing nodes in place (re-applied after data changes).
  useEffect(() => {
    const cy = runtimeRef.current?.cy();
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const data = node.data();
        switch (overlay) {
          case 'trust':
            node.style('background-color', trustColor(data.trustScore as number | undefined));
            break;
          case 'risk':
            node.style('background-color', riskColor(data.riskScore as number | undefined));
            break;
          case 'anomaly':
            node.style('background-color', anomalyColor(data.anomalyScore as number | undefined));
            break;
          default:
            node.style('background-color', '');
        }
      });
    });
  }, [runtimeRef, overlay, nodes, edges]);

  useEffect(() => {
    runtimeRef.current?.setNodeClass('highlighted', highlightedNodeIds ?? []);
  }, [runtimeRef, highlightedNodeIds]);

  useEffect(() => {
    const handle = runtimeRef.current;
    if (!handle) return;
    handle.setNodeClass('path', pathNodeIds ?? []);
    handle.setEdgeClass('path', pathEdgeIds ?? []);
  }, [runtimeRef, pathNodeIds, pathEdgeIds]);

  return (
    <div
      ref={containerRef}
      className={cn('w-full h-full min-h-[500px] bg-surface-default rounded border border-border-default', className)}
    />
  );
}
