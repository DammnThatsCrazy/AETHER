import { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle, LoadingState, ErrorState, Badge } from '@aether/ui';
import { useCampaign360Graph } from '../use-campaign-360';

interface Props {
  campaignId: string;
  timeStart?: string;
  timeEnd?: string;
}

export function Campaign360Graph({ campaignId, timeStart, timeEnd }: Props) {
  const [population, setPopulation] = useState('observed');
  const [depth, setDepth] = useState(2);
  const [submitted, setSubmitted] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const cyRef = useRef<HTMLDivElement>(null);
  const cyInstance = useRef<unknown>(null);

  const time_range = (timeStart && timeEnd) ? { start: timeStart, end: timeEnd } : undefined;

  const { data, loading, error } = useCampaign360Graph(
    submitted
      ? {
          campaignId,
          population,
          depth,
          ...(time_range !== undefined ? { time_range } : {}),
          max_nodes: 200,
          max_edges: 600,
        }
      : { campaignId: '', population: 'observed' },
  );

  const graphData = data as Record<string, unknown> | null;

  useEffect(() => {
    if (!graphData || !cyRef.current) return;

    const nodes = (graphData.nodes as Array<Record<string, unknown>> | undefined) ?? [];
    const edges = (graphData.edges as Array<Record<string, unknown>> | undefined) ?? [];

    setRenderError(null);
    import('cytoscape').then(({ default: cytoscape }) => {
      if (cyInstance.current) {
        (cyInstance.current as { destroy(): void }).destroy();
      }
      cyInstance.current = cytoscape({
        container: cyRef.current!,
        elements: [
          ...nodes.map(n => ({ data: { id: String(n.id), label: String(n.label), type: String(n.type) } })),
          ...edges.map(e => ({ data: { id: String(e.id), source: String(e.source), target: String(e.target), label: String(e.type) } })),
        ],
        style: [
          { selector: 'node', style: { label: 'data(label)', 'font-size': '10px', 'background-color': '#6366f1', color: '#fff', 'text-valign': 'center', 'text-halign': 'center', width: 30, height: 30 } },
          { selector: 'node[type="Campaign"]', style: { 'background-color': '#f59e0b', width: 40, height: 40 } },
          { selector: 'edge', style: { width: 1, 'line-color': '#94a3b8', 'target-arrow-color': '#94a3b8', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier' } },
        ],
        layout: { name: 'cose' },
      });
    }).catch((cause: unknown) => {
      setRenderError(cause instanceof Error ? cause.message : 'graph renderer unavailable');
    });
  }, [graphData]);

  useEffect(() => {
    return () => {
      if (cyInstance.current) {
        (cyInstance.current as { destroy(): void }).destroy();
      }
    };
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div>
          <label className="text-xs text-text-muted mr-2">Population:</label>
          <select value={population} onChange={e => setPopulation(e.target.value)} className="text-xs bg-surface-secondary border border-border rounded px-2 py-1">
            {['observed', 'resolved', 'engaged', 'converted', 'attributed'].map(p => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-text-muted mr-2">Depth:</label>
          <select value={depth} onChange={e => setDepth(Number(e.target.value))} className="text-xs bg-surface-secondary border border-border rounded px-2 py-1">
            {[1, 2, 3].map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => setSubmitted(true)}
          className="px-4 py-1.5 text-xs bg-accent text-white rounded"
        >
          Load graph
        </button>
      </div>

      {submitted && loading && <LoadingState lines={3} />}
      {submitted && error && <ErrorState title="Graph unavailable" message={error} />}
      {submitted && renderError && <ErrorState title="Graph renderer unavailable" message={renderError} />}
      {submitted && graphData && !loading && !renderError && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">Campaign graph</CardTitle>
              <div className="flex gap-2">
                {!!graphData.truncated && <Badge variant="warning">Truncated: {String(graphData.truncation_reason ?? '')}</Badge>}
                <Badge variant="default">{Number(graphData.node_count ?? 0)} nodes</Badge>
                <Badge variant="default">{Number(graphData.edge_count ?? 0)} edges</Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div ref={cyRef} style={{ height: 480, border: '1px solid var(--border)' }} />
          </CardContent>
        </Card>
      )}

      {!submitted && (
        <Card>
          <CardContent className="pt-8 pb-8 text-center text-text-muted text-sm">
            Configure the graph parameters above and click "Load graph" to explore the campaign graph.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
