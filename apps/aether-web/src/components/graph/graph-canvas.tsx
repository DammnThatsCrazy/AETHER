import { useRef, useEffect, useMemo } from 'react';
import { cn } from '@aether/ui';
import { useGraphRuntime, type RuntimeElement } from '@aether/ui/graph';
import type { StylesheetJson } from 'cytoscape';

// ── Color helpers ─────────────────────────────────────────────────────────────

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

// ── Types (public API — unchanged) ────────────────────────────────────────────

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  trustScore?: number;
  riskScore?: number;
  metadata: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationType: string;
  interactionClass: string;
  weight: number;
  metadata: Record<string, unknown>;
}

export type GraphOverlay = 'none' | 'trust' | 'risk' | 'campaign' | 'economic' | 'fraud';

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

// ── Style (with semantic-zoom label visibility) ───────────────────────────────

const GRAPH_STYLE: StylesheetJson = [
  {
    selector: 'node',
    style: {
      'label': 'data(label)',
      'font-size': '10px',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'background-color': '#4a6cf7',
      'width': 28,
      'height': 28,
      'color': '#e8e8f0',
      'text-outline-color': '#0a0a0f',
      'text-outline-width': 1,
    },
  },
  { selector: 'node.human', style: { 'background-color': '#4a6cf7', 'shape': 'ellipse' } },
  { selector: 'node.user', style: { 'background-color': '#4a6cf7', 'shape': 'ellipse' } },
  { selector: 'node.agent', style: { 'background-color': '#f59e0b', 'shape': 'rectangle' } },
  { selector: 'node.organization', style: { 'background-color': '#38bdf8', 'shape': 'round-rectangle' } },
  { selector: 'node.wallet', style: { 'background-color': '#22c55e', 'shape': 'diamond' } },
  { selector: 'node.device', style: { 'background-color': '#84cc16', 'shape': 'vee' } },
  { selector: 'node.session', style: { 'background-color': '#14b8a6', 'shape': 'barrel' } },
  { selector: 'node.contract', style: { 'background-color': '#06b6d4', 'shape': 'triangle' } },
  { selector: 'node.protocol', style: { 'background-color': '#8b5cf6', 'shape': 'hexagon' } },
  { selector: 'node.bot', style: { 'background-color': '#ef4444', 'shape': 'cut-rectangle' } },
  { selector: 'node.unknown', style: { 'background-color': '#64748b', 'shape': 'ellipse' } },
  { selector: 'node.highlighted', style: { 'border-width': 3, 'border-color': '#4a6cf7' } },
  { selector: 'node.path', style: { 'border-width': 3, 'border-color': '#a855f7' } },
  { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#ffffff' } },
  // ObservationClass visual treatment — never show predictions with the same weight as observations
  { selector: 'node.obs-observed', style: { 'border-width': 2, 'border-color': '#22c55e', 'border-style': 'solid' } },
  { selector: 'node.obs-deterministic', style: { 'border-width': 2, 'border-color': '#4a6cf7', 'border-style': 'solid' } },
  { selector: 'node.obs-probabilistic', style: { 'border-width': 2, 'border-color': '#eab308', 'border-style': 'dashed' } },
  { selector: 'node.obs-derived', style: { 'opacity': 0.7, 'border-width': 1, 'border-color': '#64748b', 'border-style': 'dashed' } },
  { selector: 'node.obs-predicted', style: { 'opacity': 0.55, 'border-width': 2, 'border-color': '#a855f7', 'border-style': 'dotted' } },
  { selector: 'node.obs-simulated', style: { 'opacity': 0.45, 'border-width': 1, 'border-color': '#f97316', 'border-style': 'dotted' } },
  { selector: 'node.obs-manually_asserted', style: { 'border-width': 2, 'border-color': '#f59e0b', 'border-style': 'solid' } },
  { selector: 'node.obs-externally_enriched', style: { 'border-width': 1, 'border-color': '#38bdf8', 'border-style': 'dashed' } },
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
  { selector: 'edge.H2H', style: { 'line-color': '#4a6cf7', 'opacity': 0.7 } },
  { selector: 'edge.H2A', style: { 'line-color': '#f59e0b', 'opacity': 0.7 } },
  { selector: 'edge.A2H', style: { 'line-color': '#22c55e', 'opacity': 0.7 } },
  { selector: 'edge.A2A', style: { 'line-color': '#ef4444', 'opacity': 0.7 } },
  { selector: 'edge.highlighted', style: { 'line-color': '#4a6cf7', 'width': 2, 'opacity': 1 } },
  { selector: 'edge.path', style: { 'line-color': '#a855f7', 'width': 3, 'opacity': 1 } },
];

function toElements(nodes: readonly GraphNode[], edges: readonly GraphEdge[]): RuntimeElement[] {
  const nodeEls: RuntimeElement[] = nodes.map((n) => {
    const obsClass = typeof n.metadata.observation_class === 'string' ? n.metadata.observation_class : '';
    const classes = [n.kind, obsClass ? `obs-${obsClass}` : ''].filter(Boolean).join(' ');
    return {
      group: 'nodes',
      data: {
        id: n.id,
        label: n.label,
        kind: n.kind,
        trustScore: n.trustScore,
        riskScore: n.riskScore,
        observationClass: obsClass,
      },
      classes,
    };
  });
  const edgeEls: RuntimeElement[] = edges.map((e) => ({
    group: 'edges',
    data: {
      id: e.id,
      source: e.source,
      target: e.target,
      relationType: e.relationType,
      interactionClass: e.interactionClass,
      weight: e.weight,
    },
    classes: e.interactionClass,
  }));
  return [...nodeEls, ...edgeEls];
}

// ── Component ─────────────────────────────────────────────────────────────────

export function GraphCanvas({
  nodes, edges, overlay,
  highlightedNodeIds, pathNodeIds, pathEdgeIds,
  onSelectNode, onSelectEdge, className,
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
        const d = node.data();
        if (overlay === 'trust') node.style('background-color', trustColor(d.trustScore as number | undefined));
        else if (overlay === 'risk') node.style('background-color', riskColor(d.riskScore as number | undefined));
        else node.style('background-color', '');
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
      className={cn('w-full h-full min-h-[500px] bg-surface-base rounded border border-border-default', className)}
    />
  );
}
