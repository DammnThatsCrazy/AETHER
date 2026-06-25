import { useRef, useEffect } from 'react';
import cytoscape, { type Core, type EventObject } from 'cytoscape';
import { cn } from '@aether/ui';

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

// ── Types ─────────────────────────────────────────────────────────────────────

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

export type GraphOverlay = 'none' | 'trust' | 'risk' | 'campaign';

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

// ── Component ─────────────────────────────────────────────────────────────────

export function GraphCanvas({
  nodes, edges, overlay,
  highlightedNodeIds, pathNodeIds, pathEdgeIds,
  onSelectNode, onSelectEdge, className,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectNodeRef = useRef(onSelectNode);
  const onSelectEdgeRef = useRef(onSelectEdge);
  const overlayRef = useRef(overlay);
  onSelectNodeRef.current = onSelectNode;
  onSelectEdgeRef.current = onSelectEdge;
  overlayRef.current = overlay;

  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...nodes.map(n => ({
          data: { id: n.id, label: n.label, kind: n.kind, trustScore: n.trustScore, riskScore: n.riskScore },
          classes: n.kind,
        })),
        ...edges.map(e => ({
          data: { id: e.id, source: e.source, target: e.target, relationType: e.relationType, interactionClass: e.interactionClass, weight: e.weight },
          classes: e.interactionClass,
        })),
      ],
      style: [
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
      ],
      layout: { name: 'cose', animate: false, nodeDimensionsIncludeLabels: true },
      minZoom: 0.2,
      maxZoom: 5,
    });

    cy.on('tap', 'node', (evt: EventObject) => {
      const nd = evt.target.data();
      onSelectNodeRef.current?.(nodes.find(n => n.id === nd.id) ?? null);
    });
    cy.on('tap', 'edge', (evt: EventObject) => {
      const ed = evt.target.data();
      onSelectEdgeRef.current?.(edges.find(e => e.id === ed.id) ?? null);
    });
    cy.on('tap', (evt: EventObject) => {
      if (evt.target === cy) {
        onSelectNodeRef.current?.(null);
        onSelectEdgeRef.current?.(null);
      }
    });

    // Re-apply overlay immediately so colors survive canvas rebuilds triggered by layer changes
    const currentOverlay = overlayRef.current;
    if (currentOverlay !== 'none') {
      cy.batch(() => {
        cy.nodes().forEach(node => {
          const d = node.data();
          if (currentOverlay === 'trust') node.style('background-color', trustColor(d.trustScore as number | undefined));
          else node.style('background-color', riskColor(d.riskScore as number | undefined));
        });
      });
    }

    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  }, [nodes, edges]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().forEach(node => {
        const d = node.data();
        if (overlay === 'trust') node.style('background-color', trustColor(d.trustScore));
        else if (overlay === 'risk') node.style('background-color', riskColor(d.riskScore));
        else node.style('background-color', '');
      });
    });
  }, [overlay]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().removeClass('highlighted');
      (highlightedNodeIds ?? []).forEach(id => {
        const n = cy.getElementById(id);
        if (n.length) n.addClass('highlighted');
      });
    });
  }, [highlightedNodeIds]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().removeClass('path');
      cy.edges().removeClass('path');
      (pathNodeIds ?? []).forEach(id => { const n = cy.getElementById(id); if (n.length) n.addClass('path'); });
      (pathEdgeIds ?? []).forEach(id => { const e = cy.getElementById(id); if (e.length) e.addClass('path'); });
    });
  }, [pathNodeIds, pathEdgeIds]);

  return (
    <div
      ref={containerRef}
      className={cn('w-full h-full min-h-[500px] bg-surface-base rounded border border-border-default', className)}
    />
  );
}
