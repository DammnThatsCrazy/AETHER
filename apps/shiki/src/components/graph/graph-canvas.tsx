import { useRef, useEffect, useCallback } from 'react';
import cytoscape, { type Core, type EventObject } from 'cytoscape';
import { cn } from '@shiki/lib/utils';
import type { GraphNode, GraphEdge, GraphOverlay } from '@shiki/types';

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
// Props
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
  const cyRef = useRef<Core | null>(null);
  const onSelectNodeRef = useRef(onSelectNode);
  const onSelectEdgeRef = useRef(onSelectEdge);

  onSelectNodeRef.current = onSelectNode;
  onSelectEdgeRef.current = onSelectEdge;

  // ---- Initialize Cytoscape ----
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...nodes.map((n) => ({
          data: { id: n.id, label: n.label, type: n.type, trustScore: n.trustScore, riskScore: n.riskScore, anomalyScore: n.anomalyScore },
          classes: n.type,
        })),
        ...edges.map((e) => ({
          data: { id: e.id, source: e.source, target: e.target, label: e.label, weight: e.weight, edgeType: e.type },
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
            'width': 30,
            'height': 30,
            'color': '#e8e8f0',
            'text-outline-color': '#0a0a0f',
            'text-outline-width': 1,
          },
        },
        { selector: 'node.customer', style: { 'background-color': '#4a6cf7', 'shape': 'ellipse' } },
        { selector: 'node.wallet', style: { 'background-color': '#22c55e', 'shape': 'diamond' } },
        { selector: 'node.agent', style: { 'background-color': '#f59e0b', 'shape': 'rectangle' } },
        { selector: 'node.protocol', style: { 'background-color': '#8b5cf6', 'shape': 'hexagon' } },
        { selector: 'node.contract', style: { 'background-color': '#06b6d4', 'shape': 'triangle' } },
        { selector: 'node.cluster', style: { 'background-color': '#ec4899', 'shape': 'octagon' } },
        { selector: 'node.external', style: { 'background-color': '#64748b', 'shape': 'ellipse' } },
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
        { selector: 'edge.highlighted', style: { 'line-color': '#4a6cf7', 'width': 2, 'opacity': 1 } },
        { selector: 'edge.path', style: { 'line-color': '#a855f7', 'width': 3, 'opacity': 1 } },
      ],
      layout: { name: 'cose', animate: false, nodeDimensionsIncludeLabels: true },
      minZoom: 0.2,
      maxZoom: 5,
    });

    // Node click handler
    cy.on('tap', 'node', (evt: EventObject) => {
      const nodeData = evt.target.data();
      const matched = nodes.find((n) => n.id === nodeData.id);
      onSelectNodeRef.current?.(matched ?? null);
    });

    // Edge click handler
    cy.on('tap', 'edge', (evt: EventObject) => {
      const edgeData = evt.target.data();
      const matched = edges.find((e) => e.id === edgeData.id);
      onSelectEdgeRef.current?.(matched ?? null);
    });

    // Background click clears selection
    cy.on('tap', (evt: EventObject) => {
      if (evt.target === cy) {
        onSelectNodeRef.current?.(null);
        onSelectEdgeRef.current?.(null);
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges]);

  // ---- Apply overlay colors ----
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const data = node.data();
        let color: string;
        switch (overlay) {
          case 'trust':
            color = trustColor(data.trustScore);
            break;
          case 'risk':
            color = riskColor(data.riskScore);
            break;
          case 'anomaly':
            color = anomalyColor(data.anomalyScore);
            break;
          default:
            // Restore default colors by removing override — use class-based styles
            node.style('background-color', '');
            return;
        }
        node.style('background-color', color);
      });
    });
  }, [overlay]);

  // ---- Apply highlight classes ----
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      cy.nodes().removeClass('highlighted');
      if (highlightedNodeIds && highlightedNodeIds.length > 0) {
        for (const nid of highlightedNodeIds) {
          const n = cy.getElementById(nid);
          if (n.length) n.addClass('highlighted');
        }
      }
    });
  }, [highlightedNodeIds]);

  // ---- Apply path classes ----
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      cy.nodes().removeClass('path');
      cy.edges().removeClass('path');

      if (pathNodeIds && pathNodeIds.length > 0) {
        for (const nid of pathNodeIds) {
          const n = cy.getElementById(nid);
          if (n.length) n.addClass('path');
        }
      }
      if (pathEdgeIds && pathEdgeIds.length > 0) {
        for (const eid of pathEdgeIds) {
          const e = cy.getElementById(eid);
          if (e.length) e.addClass('path');
        }
      }
    });
  }, [pathNodeIds, pathEdgeIds]);

  return (
    <div
      ref={containerRef}
      className={cn('w-full h-full min-h-[500px] bg-surface-default rounded border border-border-default', className)}
    />
  );
}
