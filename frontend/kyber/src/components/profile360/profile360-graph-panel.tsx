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

const typeOptions = [
  { value: 'all', label: 'All types' },
  { value: 'human', label: 'Human' },
  { value: 'agent', label: 'Agent' },
  { value: 'wallet', label: 'Wallet' },
  { value: 'session', label: 'Session' },
  { value: 'journey', label: 'Journey' },
  { value: 'transaction', label: 'Transaction' },
  { value: 'organization', label: 'Organization' },
];

const CHUNK_THRESHOLD = 150;
const CHUNK_SIZE = 150;

function chunkByDegree(nodes: readonly GraphNode[], edges: readonly GraphEdge[], limit: number): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  const sorted = [...nodes].sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0));
  const kept = new Set(sorted.slice(0, limit).map((n) => n.id));
  return {
    nodes: sorted.slice(0, limit),
    edges: edges.filter((e) => kept.has(e.source) && kept.has(e.target)),
  };
}

export function Profile360GraphPanel({ graph, highlightedNodeIds, onHighlight, onDrill }: Profile360GraphPanelProps) {
  const [overlay, setOverlay] = useState<GraphOverlay>('none');
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [chunkPage, setChunkPage] = useState(0);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);

  const filteredGraph = useMemo(() => {
    let nodes = graph.nodes as GraphNode[];
    let edges = graph.edges as GraphEdge[];
    if (typeFilter !== 'all') {
      const nodeIds = new Set(nodes.filter((n) => n.type === typeFilter).map((n) => n.id));
      nodes = nodes.filter((n) => nodeIds.has(n.id));
      edges = edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
    }
    if (query.trim()) {
      const q = query.toLowerCase();
      const nodeIds = new Set(nodes.filter((n) => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q) || n.type.toLowerCase().includes(q)).map((n) => n.id));
      nodes = nodes.filter((n) => nodeIds.has(n.id));
      edges = edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
    }
    return { nodes, edges };
  }, [graph, query, typeFilter]);

  const needsChunking = filteredGraph.nodes.length > CHUNK_THRESHOLD;
  const chunkLimit = (chunkPage + 1) * CHUNK_SIZE;
  const visibleGraph = useMemo(
    () => needsChunking ? chunkByDegree(filteredGraph.nodes, filteredGraph.edges, chunkLimit) : filteredGraph,
    [filteredGraph, needsChunking, chunkLimit],
  );
  const hasMoreChunks = needsChunking && chunkLimit < filteredGraph.nodes.length;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
      <Card className="min-h-[620px]">
        <CardHeader>
          <div>
            <CardTitle>Relationship graph</CardTitle>
            <p className="mt-1 text-xs text-text-secondary">Expand attribution paths, highlight ownership/delegation edges, and filter the timeline from node selections.</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search nodes" className="w-40" />
            <Select value={typeFilter} onChange={(value) => { setTypeFilter(value); setChunkPage(0); }} options={typeOptions} />
            <Select value={overlay} onChange={(value) => setOverlay(value as GraphOverlay)} options={overlayOptions} />
          </div>
        </CardHeader>
        <CardContent>
          {needsChunking && (
            <div className="mb-2 flex items-center justify-between text-xs text-text-muted border-b border-border-subtle pb-2">
              <span>Showing {visibleGraph.nodes.length} of {filteredGraph.nodes.length} nodes (sorted by degree)</span>
              {hasMoreChunks && <Button size="sm" variant="secondary" onClick={() => setChunkPage((p) => p + 1)}>Show {Math.min(CHUNK_SIZE, filteredGraph.nodes.length - chunkLimit)} more</Button>}
            </div>
          )}
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
