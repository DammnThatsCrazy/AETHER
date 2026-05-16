import { useMemo, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Select } from '@aether/ui';
import { GraphCanvas } from '@kyber/components/graph';
import type { GraphEdge, GraphNode, GraphOverlay, Profile360Graph, Profile360Reference } from '@kyber/types';

interface Profile360GraphPanelProps {
  readonly graph: Profile360Graph;
  readonly highlightedNodeIds: readonly string[];
  readonly onHighlight: (nodeIds: readonly string[]) => void;
  readonly onDrill: (reference: Profile360Reference) => void;
}

const overlayOptions = [
  { value: 'none', label: 'Default' },
  { value: 'trust', label: 'Trust' },
  { value: 'risk', label: 'Risk' },
  { value: 'anomaly', label: 'Anomaly' },
];

export function Profile360GraphPanel({ graph, highlightedNodeIds, onHighlight, onDrill }: Profile360GraphPanelProps) {
  const [overlay, setOverlay] = useState<GraphOverlay>('none');
  const [query, setQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);

  const visibleGraph = useMemo(() => {
    if (!query.trim()) return graph;
    const q = query.toLowerCase();
    const nodes = graph.nodes.filter((node) => node.label.toLowerCase().includes(q) || node.id.toLowerCase().includes(q) || node.type.toLowerCase().includes(q));
    const nodeIds = new Set(nodes.map((node) => node.id));
    return { ...graph, nodes, edges: graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)) };
  }, [graph, query]);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
      <Card className="min-h-[620px]">
        <CardHeader>
          <div>
            <CardTitle>Relationship graph</CardTitle>
            <p className="mt-1 text-xs text-text-secondary">Expand attribution paths, highlight ownership/delegation edges, and filter the timeline from node selections.</p>
          </div>
          <div className="flex items-center gap-2">
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search nodes" className="w-48" />
            <Select value={overlay} onChange={(value) => setOverlay(value as GraphOverlay)} options={overlayOptions} />
          </div>
        </CardHeader>
        <CardContent>
          <GraphCanvas
            nodes={[...visibleGraph.nodes]}
            edges={[...visibleGraph.edges]}
            overlay={overlay}
            highlightedNodeIds={highlightedNodeIds}
            onSelectNode={(node) => {
              setSelectedNode(node);
              setSelectedEdge(null);
              onHighlight(node ? [node.id] : []);
            }}
            onSelectEdge={(edge) => {
              setSelectedEdge(edge);
              setSelectedNode(null);
              onHighlight(edge ? [edge.source, edge.target] : []);
            }}
            className="min-h-[540px]"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Graph inspector</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-xs">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded bg-surface-raised p-2"><div className="text-text-muted">Nodes</div><div className="font-mono text-text-primary">{graph.nodes.length}</div></div>
            <div className="rounded bg-surface-raised p-2"><div className="text-text-muted">Edges</div><div className="font-mono text-text-primary">{graph.edges.length}</div></div>
          </div>
          {selectedNode && (
            <div className="space-y-2">
              <div className="flex items-center gap-2"><Badge>{selectedNode.type}</Badge><span className="font-medium text-text-primary">{selectedNode.label}</span></div>
              <pre className="max-h-64 overflow-auto rounded bg-surface-raised p-2 text-[10px] text-text-secondary">{JSON.stringify(selectedNode.metadata, null, 2)}</pre>
              <Button size="sm" className="w-full" onClick={() => onDrill({ id: selectedNode.id, type: selectedNode.type === 'external' ? 'human' : selectedNode.type, label: selectedNode.label, metadata: selectedNode.metadata })}>Drill into node</Button>
            </div>
          )}
          {selectedEdge && (
            <div className="space-y-2">
              <div className="flex items-center gap-2"><Badge>{selectedEdge.type}</Badge><span className="font-medium text-text-primary">{selectedEdge.source} → {selectedEdge.target}</span></div>
              <pre className="max-h-64 overflow-auto rounded bg-surface-raised p-2 text-[10px] text-text-secondary">{JSON.stringify(selectedEdge.metadata, null, 2)}</pre>
            </div>
          )}
          {!selectedNode && !selectedEdge && <div className="text-text-muted">Select a node or edge to inspect relationship metadata.</div>}
        </CardContent>
      </Card>
    </div>
  );
}
